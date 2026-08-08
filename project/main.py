"""FastAPI application: single-process autonomous publisher backend.

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
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
# API
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