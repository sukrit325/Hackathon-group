"""FastAPI application for the autonomous publisher backend."""
from __future__ import annotations

import asyncio
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
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

import db
import worker
from config import get_settings
from schemas import AgentInitRequest, AgentInitResponse, FeedResponse, PostOut

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("main")

app = FastAPI(title="Autonomous Publisher Backend")
scheduler = AsyncIOScheduler(timezone=timezone.utc)
_job_ids: set[str] = set()


class TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_sec: float) -> None:
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate_per_sec = refill_rate_per_sec
        self.updated_at = time.monotonic()

    def consume(self, amount: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.updated_at
        self.updated_at = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate_per_sec)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


_bucket = TokenBucket(120, 2.0)


def _assert_single_process() -> None:
    if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
        raise RuntimeError("WEB_CONCURRENCY > 1 is not supported")
    if "--workers" in sys.argv:
        index = sys.argv.index("--workers") + 1
        if index < len(sys.argv) and int(sys.argv[index]) > 1:
            raise RuntimeError("Multiple workers are not supported")


async def _rate_limited(request: Request) -> None:
    if not _bucket.consume(1):
        raise HTTPException(status_code=429, detail="rate limited")


def _require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    settings = get_settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def _job_id(agent_id: str) -> str:
    return f"agent:{agent_id}"


async def schedule_agent(agent_id: str, run_now: bool = False) -> None:
    _assert_single_process()
    if _job_id(agent_id) in _job_ids:
        return
    scheduler.add_job(
        worker.run_worker_tick,
        args=[agent_id],
        trigger=IntervalTrigger(minutes=get_settings().worker_interval_minutes),
        id=_job_id(agent_id),
        max_instances=1,
        coalesce=True,
    )
    _job_ids.add(_job_id(agent_id))
    if run_now:
        asyncio.create_task(worker.run_worker_tick(agent_id))


async def unschedule_agent(agent_id: str) -> None:
    scheduler.remove_job(_job_id(agent_id))
    _job_ids.discard(_job_id(agent_id))


async def _restore_active_agents() -> None:
    db.init_db()
    agents = db.list_active_agents()
    for index, agent in enumerate(agents):
        delay_seconds = min(index * 2, 60)
        asyncio.get_running_loop().call_later(delay_seconds, lambda aid=agent["id"]: asyncio.create_task(schedule_agent(aid)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_single_process()
    db.init_db()
    if not scheduler.running:
        scheduler.start()
    await _restore_active_agents()
    yield
    scheduler.shutdown(wait=True)


app = FastAPI(title="Autonomous Publisher Backend", lifespan=lifespan)


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.post("/api/agent/init", response_model=AgentInitResponse)
async def init_agent(
    payload: AgentInitRequest,
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
    idempotency_key: Optional[str] = Header(default=None),
) -> AgentInitResponse:
    _require_api_key(x_api_key)
    await _rate_limited(request)
    db.init_db()
    if idempotency_key and db.has_idempotency_key(idempotency_key):
        existing_agent_id = db.get_idempotency_agent(idempotency_key)
        if existing_agent_id:
            return AgentInitResponse(agentId=existing_agent_id)
    agent_id = f"agent-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{os.urandom(4).hex()}"
    db.insert_agent(agent_id, payload.persona.name, payload.persona.domain)
    if idempotency_key:
        db.insert_idempotency_key(idempotency_key, agent_id)
    await schedule_agent(agent_id, run_now=True)
    return AgentInitResponse(agentId=agent_id)


@app.get("/api/agent/feed", response_model=FeedResponse)
async def read_feed(
    agent_id: str = Query(...),
    request: Request,
    limit: int = Query(default=50),
    x_api_key: Optional[str] = Header(default=None),
) -> FeedResponse:
    _require_api_key(x_api_key)
    await _rate_limited(request)
    db.init_db()
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    posts = db.list_posts(agent_id, limit=limit)
    return FeedResponse(posts=[PostOut(**post) for post in posts])


@app.delete("/api/agent/{agent_id}")
async def delete_agent(agent_id: str, request: Request, x_api_key: Optional[str] = Header(default=None)) -> dict[str, str]:
    _require_api_key(x_api_key)
    await _rate_limited(request)
    db.init_db()
    db.delete_agent(agent_id)
    await unschedule_agent(agent_id)
    return {"status": "deleted"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


current_dir = Path(__file__).resolve().parent
static_dir = current_dir / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
