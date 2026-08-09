"""FastAPI application: autonomous publisher backend (single-request pipeline)."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from uvicorn import lifespan

import db
import worker
from config import get_settings
from schemas import (
    AgentInitRequest,
    AgentInitResponse,
    FeedPost,
    FeedResponse,
)

# REMOVE THIS IMPORT - worker.py handles the agent
# from Agents.src.news_editor import build_system_prompt, call_llm, validate_decision

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    s = get_settings()
    if not s.api_key:
        return
    if not x_api_key or x_api_key != s.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )


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
# API Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/agent/init", response_model=AgentInitResponse)
async def init_agent(
    body: AgentInitRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_api_key),
):
    """
    Initialize an agent and immediately run the complete publishing pipeline.
    This request blocks until the first generation finishes.
    """
    # Idempotency replay
    if idempotency_key:
        cached = db.lookup_idempotency(idempotency_key)
        if cached is not None:
            return AgentInitResponse(agentId=cached["agent_id"])

    # Rate limiting
    s = get_settings()
    if db.count_active_agents() >= s.max_active_agents:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"max active agents ({s.max_active_agents}) reached",
        )

    # Create agent
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

    # Run the publishing pipeline immediately (blocking)
    try:
        logger.info(f"Running publishing pipeline for agent {agent_id}")
        await worker.run_pipeline(agent_id)
        logger.info(f"Pipeline completed for agent {agent_id}")
    except Exception as e:
        logger.exception(f"Pipeline failed for agent {agent_id}: {e}")
        # Mark agent as inactive if pipeline fails
        db.set_agent_active(agent_id, 0)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Publishing pipeline failed: {str(e)}"
        )

    return AgentInitResponse(agentId=agent_id)


@app.get("/api/agent/feed", response_model=FeedResponse)
async def get_feed(
    agentId: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    before_created_at: Optional[str] = Query(default=None),
    before_id: Optional[str] = Query(default=None),
    _: None = Depends(require_api_key),
):
    """
    Strictly passive feed endpoint.
    No generation, no side effects.
    Read only from SQLite.
    """
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
    """Deactivate an agent (soft delete)."""
    agent = db.get_agent(agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    db.set_agent_active(agent_id, 0)
    return {"ok": True}


# Mount static files LAST so API routes take precedence.
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False, workers=1)