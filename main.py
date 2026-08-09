"""FastAPI application: autonomous publisher backend."""
from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import db
import worker
from config import get_settings
from schemas import (
    AgentInitRequest,
    AgentInitResponse,
    FeedPost,
    FeedResponse,
    GenerateRequest,
    GenerateResponse,
    GenerationStatusResponse,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Database initialized on startup.")
    yield

app = FastAPI(lifespan=lifespan)

def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    s = get_settings()
    if not s.api_key:
        return
    if not x_api_key or x_api_key != s.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error"},
    )

@app.post("/api/agent/curate", dependencies=[Depends(require_api_key)])
def curate_agent():
    return {"status": "healthy"}

async def _execute_pipeline_task(agent_id: str, generation_id: Optional[str] = None) -> None:
    try:
        logger.info(f"Running background publishing pipeline for agent {agent_id}")
        await worker.run_pipeline(agent_id, generation_id=generation_id, trigger="SCHEDULED")
        logger.info(f"Pipeline completed for agent {agent_id}")
    except Exception as e:
        logger.exception(f"Pipeline background execution failed for agent {agent_id}: {e}")

@app.post(
    "/api/agent/init",
    response_model=AgentInitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def init_agent(
    body: AgentInitRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_api_key),
):
    if idempotency_key:
        cached = db.lookup_idempotency(idempotency_key)
        if cached is not None:
            return AgentInitResponse(agentId=cached["agent_id"])

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

    background_tasks.add_task(_execute_pipeline_task, agent_id)
    return AgentInitResponse(agentId=agent_id)

@app.post(
    "/api/agent/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_post(
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
):
    agent = db.get_agent(body.agentId)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if not agent.get("active", 1):
        raise HTTPException(status_code=400, detail="agent is not active")

    active_gen = db.get_active_generation_for_agent(body.agentId)
    if active_gen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A generation task is already queued or running for this agent",
        )

    generation_id = db.new_uuid()
    created_at = db.now_utc_iso()
    db.insert_generation(
        generation_id=generation_id,
        agent_id=body.agentId,
        status="QUEUED",
        created_at=created_at,
    )

    background_tasks.add_task(
        worker.run_pipeline,
        agent_id=body.agentId,
        generation_id=generation_id,
        trigger="MANUAL",
    )

    return GenerateResponse(generationId=generation_id, status="QUEUED")

@app.get(
    "/api/agent/generation/{generationId}",
    response_model=GenerationStatusResponse,
)
async def get_generation_status(
    generationId: str,
    _: None = Depends(require_api_key),
):
    gen = db.get_generation(generationId)
    if gen is None:
        raise HTTPException(status_code=404, detail="generation not found")

    return GenerationStatusResponse(
        generationId=gen["id"],
        status=gen["status"],
        postId=gen.get("post_id"),
        error=gen.get("error_message"),
    )

@app.get("/api/agent/feed", response_model=FeedResponse)
async def get_feed(
    agentId: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    before_created_at: Optional[str] = Query(default=None),
    before_id: Optional[str] = Query(default=None),
    _: None = Depends(require_api_key),
):
    agent = db.get_agent(agentId)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    if bool(before_created_at) != bool(before_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'before_created_at' and 'before_id' must be provided together for pagination.",
        )

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
        raise HTTPException(status_code=404, detail="agent not found")
    db.set_agent_active(agent_id, 0)
    return {"ok": True}

static_path = Path("Agents/src/static")
if static_path.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_path), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False, workers=1)
