"""FastAPI application: single-process autonomous publisher backend with integrated agent.

IMPORTANT: This application owns an in-process APScheduler. It MUST run as
exactly one scheduler-owning process. Do NOT use:
  - uvicorn --workers N (with N>1)
  - gunicorn with multiple application workers
  - multiple independent instances against the same SQLite database

The application refuses to start if WEB_CONCURRENCY > 1 or if --workers > 1
is detected in argv, to fail loudly rather than silently corrupt state.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

import db
import worker
from config import get_settings
from llm import LLMError, get_provider
from schemas import (
    AgentInitRequest,
    AgentInitResponse,
    FeedPost,
    FeedResponse,
)
from urllib.parse import urlparse

# Import agent modules
sys.path.insert(0, str(Path(__file__).parent / "Agents" / "tech-news-editor" / "src"))
from Agents.src.news_editor import build_system_prompt, call_llm, parse_input_data, validate_decision

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Single-process enforcement
# ---------------------------------------------------------------------------

def _assert_single_process() -> None:
    # WEB_CONCURRENCY is what gunicorn/uvicorn workers commonly read.
    wc = os.environ.get("WEB_CONCURRENCY", "1")
    try:
        if int(wc) > 1:
            raise RuntimeError(
                "WEB_CONCURRENCY > 1 is forbidden: this application owns an "
                "in-process APScheduler and must run as exactly one process."
            )
    except ValueError:
        pass
    # Detect `uvicorn --workers N` style invocation.
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--workers" and i + 1 < len(argv):
            try:
                if int(argv[i + 1]) > 1:
                    raise RuntimeError(
                        "uvicorn --workers > 1 is forbidden for this application "
                        "(in-process APScheduler)."
                    )
            except ValueError:
                pass
        # gunicorn -w N
        if arg in ("-w", "--workers") and i + 1 < len(argv):
            try:
                if int(argv[i + 1]) > 1:
                    raise RuntimeError(
                        "gunicorn -w > 1 is forbidden for this application."
                    )
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# In-process rate limiter (single-process only; documented limitation)
# ---------------------------------------------------------------------------

class TokenBucket:
    def __init__(self, rate_per_minute: int):
        self.capacity = rate_per_minute
        self.tokens = float(rate_per_minute)
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.last = now
            self.tokens = min(self.capacity, self.tokens + elapsed * (self.capacity / 60.0))
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


_agent_create_bucket: Optional[TokenBucket] = None


def _get_bucket() -> TokenBucket:
    global _agent_create_bucket
    if _agent_create_bucket is None:
        s = get_settings()
        _agent_create_bucket = TokenBucket(s.agent_create_per_minute)
    return _agent_create_bucket


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    s = get_settings()
    if not s.api_key:
        # Auth explicitly disabled (dev/internal). Documented in README.
        return
    if not x_api_key or x_api_key != s.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

scheduler: Optional[AsyncIOScheduler] = None
_restored_job_ids: set[str] = set()


def _job_id(agent_id: str) -> str:
    return f"agent:{agent_id}"


def schedule_agent(agent_id: str, run_now: bool = False) -> None:
    """Register (or replace) the periodic job for an agent."""
    assert scheduler is not None, "scheduler not initialized"
    s = get_settings()
    jid = _job_id(agent_id)

    # Avoid duplicate jobs within the same process.
    if jid in _restored_job_ids or scheduler.get_job(jid) is not None:
        return
    _restored_job_ids.add(jid)

    trigger = IntervalTrigger(minutes=s.worker_interval_minutes, timezone="UTC")
    scheduler.add_job(
        worker.run_worker_tick,
        trigger=trigger,
        args=[agent_id],
        id=jid,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        # Do not pile up missed runs from a long downtime.
    )
    if run_now:
        # Immediate first run as a background task on the same loop. The
        # per-agent asyncio.Lock prevents overlap with the scheduled job.
        asyncio.create_task(worker.run_worker_tick(agent_id))


def unschedule_agent(agent_id: str) -> None:
    assert scheduler is not None
    jid = _job_id(agent_id)
    try:
        scheduler.remove_job(jid)
    except Exception:
        pass
    _restored_job_ids.discard(jid)


async def _restore_active_agents() -> None:
    agents = db.list_active_agents()
    # Stagger startup to avoid a thundering herd of LLM/discovery calls.
    s = get_settings()
    base = 2.0
    for i, a in enumerate(agents):
        schedule_agent(a["id"], run_now=False)
        # Stagger immediate runs by a few seconds up to a cap.
        delay = min(i * base, 60.0)
        asyncio.get_event_loop().call_later(
            delay, lambda aid=a["id"]: asyncio.create_task(worker.run_worker_tick(aid))
        )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    _assert_single_process()
    logger.info("initializing database")
    db.init_db()
    # Validate LLM provider config at startup (fail fast).
    try:
        get_provider()
    except LLMError as exc:
        logger.warning("LLM provider not ready at startup: %s", exc)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    logger.info("scheduler started (UTC)")
    await _restore_active_agents()
    try:
        yield
    finally:
        logger.info("shutdown requested; stopping scheduler")
        if scheduler is not None:
            scheduler.shutdown(wait=True)
        logger.info("shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Autonomous Publisher", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error"},
    )


# ---------------------------------------------------------------------------
# Agent Integration Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/agent/run")
async def run_agent_directly(
    request: Request,
    _: None = Depends(require_api_key),
):
    """
    Run the agent on provided candidates and return decision.
    """
    try:
        body = await request.json()
        agent_name = body.get("agent_name", "TechSage")
        agent_domain = body.get("agent_domain", "technology")
        candidates = body.get("candidates", [])
        
        if not candidates:
            raise HTTPException(400, "No candidates provided")
        
        # Get posting history from database
        posting_history = []
        # Optionally fetch from db if agent_id provided
        agent_id = body.get("agent_id")
        if agent_id:
            posts = db.list_posts(agent_id, limit=50)
            posting_history = [
                {"text": p["text"], "sources": p["sources"]}
                for p in posts
            ]
        
        # Build agent input
        agent_input = {
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "current_utc_time": datetime.now(timezone.utc).isoformat(),
            "posting_history": posting_history,
            "candidates": candidates
        }
        
        # Build prompt and call agent
        system_prompt = build_system_prompt(
            agent_name=agent_input["agent_name"],
            agent_domain=agent_input["agent_domain"],
            current_utc_time=agent_input["current_utc_time"],
            posting_history=agent_input["posting_history"],
            candidates=agent_input["candidates"]
        )
        
        response_text = call_llm(system_prompt)
        decision = json.loads(response_text)
        
        # Validate decision
        if not validate_decision(decision, candidates):
            return {
                "decision": "REJECT",
                "reasoning": "Validation failed - invalid decision format",
                "selectedCandidateId": None,
                "post": None
            }
        
        # If publish, save to database if agent_id provided
        if decision["decision"] == "PUBLISH" and agent_id:
            selected = next(c for c in candidates if c["id"] == decision["selectedCandidateId"])
            db.insert_post(
                agent_id=agent_id,
                text=decision["post"]["text"],
                rationale=decision["post"]["rationale"],
                sources=decision["post"]["sources"],
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        
        return decision
        
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body")
    except Exception as e:
        logger.exception("Agent run failed")
        return {
            "decision": "ERROR",
            "reasoning": str(e),
            "selectedCandidateId": None,
            "post": None
        }


@app.post("/api/agent/curate")
async def curate_with_agent(
    request: Request,
    _: None = Depends(require_api_key),
):
    """
    Fetch candidates from RSS, run agent, return curated result.
    """
    try:
        body = await request.json() or {}
        agent_id = body.get("agent_id")
        category = body.get("category", "all")
        persona = body.get("persona", "ai_architect")
        
        # Fetch candidates from RSS
        candidates = fetch_rss_candidates(category)
        
        if not candidates:
            return {
                "decision": "REJECT",
                "reasoning": "No RSS candidates found",
                "selectedCandidateId": None,
                "post": None,
                "candidates": []
            }
        
        # Run agent on candidates
        agent_input = {
            "agent_name": persona.replace("_", " ").title(),
            "agent_domain": "technology news",
            "current_utc_time": datetime.now(timezone.utc).isoformat(),
            "posting_history": [],
            "candidates": candidates
        }
        
        if agent_id:
            posts = db.list_posts(agent_id, limit=50)
            agent_input["posting_history"] = [
                {"text": p["text"], "sources": p["sources"]}
                for p in posts
            ]
        
        system_prompt = build_system_prompt(**agent_input)
        response_text = call_llm(system_prompt)
        decision = json.loads(response_text)
        
        # Validate and save
        if validate_decision(decision, candidates) and decision["decision"] == "PUBLISH":
            if agent_id:
                selected = next(c for c in candidates if c["id"] == decision["selectedCandidateId"])
                db.insert_post(
                    agent_id=agent_id,
                    text=decision["post"]["text"],
                    rationale=decision["post"]["rationale"],
                    sources=decision["post"]["sources"],
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            return {
                "decision": decision["decision"],
                "selectedCandidateId": decision["selectedCandidateId"],
                "post": decision["post"],
                "candidates": candidates
            }
        
        return {
            "decision": decision["decision"],
            "reasoning": decision.get("reasoning", "No candidate passed threshold"),
            "selectedCandidateId": None,
            "post": None,
            "candidates": candidates
        }
        
    except Exception as e:
        logger.exception("Curate failed")
        return {
            "decision": "ERROR",
            "reasoning": str(e),
            "selectedCandidateId": None,
            "post": None,
            "candidates": []
        }


def fetch_rss_candidates(category: str) -> list:
    """Fetch candidates from RSS feed."""
    import urllib.request
    import xml.etree.ElementTree as ET
    from bs4 import BeautifulSoup
    
    url = "https://news.ycombinator.com/rss"
    candidates = []
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read()
        root = ET.fromstring(html)
        
        for idx, item in enumerate(root.findall('.//item')[:20]):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            
            if not title or not link:
                continue
            
            # Scrape content
            content = scrape_article_text(link)
            
            candidates.append({
                "id": f"cand_{idx}",
                "title": title,
                "summary": content[:500],
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sources": [link]
            })
            
    except Exception as e:
        logger.error(f"Error fetching RSS: {e}")
        
    return candidates


def scrape_article_text(url: str) -> str:
    """Scrape article text from URL."""
    import urllib.request
    from bs4 import BeautifulSoup
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read()
        soup = BeautifulSoup(html, 'html.parser')
        
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.extract()
            
        paragraphs = [p.get_text().strip() for p in soup.find_all('p') if len(p.get_text().strip()) > 40]
        text_content = " ".join(paragraphs[:8])
        return text_content[:3500] if text_content else "No descriptive article text available."
    except Exception:
        return "Context extraction unavailable due to source site network or access restrictions."


# ---------------------------------------------------------------------------
# Original API endpoints
# ---------------------------------------------------------------------------

@app.post("/api/agent/init", response_model=AgentInitResponse)
async def init_agent(
    body: AgentInitRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_api_key),
):
    # Idempotency replay
    if idempotency_key:
        cached = db.lookup_idempotency(idempotency_key)
        if cached is not None:
            return AgentInitResponse(agentId=cached["agent_id"])

    # Rate limit
    bucket = _get_bucket()
    if not await bucket.take():
        raise HTTPException(429, "agent creation rate limit exceeded")

    s = get_settings()
    if db.count_active_agents() >= s.max_active_agents:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"max active agents ({s.max_active_agents}) reached",
        )

    agent_id = db.new_uuid()
    created_at = db.now_utc_iso()
    db.insert_agent(
        agent_id=agent_id,
        name=body.persona.name,
        domain=body.persona.domain,
        created_at=created_at,
    )
    if idempotency_key:
        resp = {"agentId": agent_id}
        db.save_idempotency(idempotency_key, agent_id, resp, created_at)

    # Schedule + immediate first run (non-blocking)
    schedule_agent(agent_id, run_now=True)
    return AgentInitResponse(agentId=agent_id)


@app.get("/api/agent/feed", response_model=FeedResponse)
async def get_feed(
    agentId: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    before_created_at: Optional[str] = Query(default=None),
    before_id: Optional[str] = Query(default=None),
    _: None = Depends(require_api_key),
):
    """Strictly passive feed endpoint. No generation, no side effects."""
    agent = db.get_agent(agentId)
    if agent is None:
        raise HTTPException(404, "agent not found")

    before = None
    if before_created_at and before_id:
        before = (before_created_at, before_id)

    posts = db.list_posts(agentId, limit=limit, before=before)
    return FeedResponse(
        posts=[
            FeedPost(
                id=p["id"],
                createdAt=p["created_at"],
                text=p["text"],
                rationale=p["rationale"],
                sources=p["sources"],
            )
            for p in posts
        ]
    )


@app.delete("/api/agent/{agent_id}")
async def deactivate_agent(agent_id: str, _: None = Depends(require_api_key)):
    agent = db.get_agent(agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    db.set_agent_active(agent_id, 0)
    unschedule_agent(agent_id)
    return {"ok": True}


# Mount static files LAST so API routes take precedence.
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# Allow `python main.py` for development. NOTE: --reload spawns a reloader
# subprocess; we still enforce single worker, but reload is acceptable.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False, workers=1)