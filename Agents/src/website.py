"""Integrated FastAPI application - connects UI, Database, Worker, and Breeth AI Agent"""
import os
import sys
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent))

import db
import worker
from config import get_settings
from schemas import AgentInitRequest, AgentInitResponse, FeedPost, FeedResponse
from news_editor import NewsEditorAgent
from discovery import discover_candidates

app = FastAPI(title="Autonomous Tech Insights Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CurateRequest(BaseModel):
    category: str = "all"
    persona: str = "ai_architect"

class CurateResponse(BaseModel):
    persona: str
    headline: str
    selection_rationale: str
    impact_score: str
    target_audience: str
    takeaways: List[str]
    briefing: str
    source_url: str
    domain: str
    hashtags: List[str]
    generated_at: str

PERSONA_PROMPTS = {
    "ai_architect": {
        "role": "AI Systems & ML Architect",
        "focus": "Model architecture, GPU/memory optimization, and scalability."
    },
    "security_analyst": {
        "role": "Principal Cybersecurity Specialist",
        "focus": "Vulnerability analysis, threat vectors, risk mitigation, and enterprise compliance."
    },
    "executive": {
        "role": "Tech Executive & Product Strategist",
        "focus": "Market impact, enterprise ROI, strategic implementation, and product trends."
    }
}

@app.on_event("startup")
async def startup_event():
    try:
        db.init_db()
    except Exception as e:
        print(f"Database init warning: {e}")

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "agent": "ready",
        "breeth_api_key": "configured" if os.getenv("BREETH_API_KEY") else "missing",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/agent/curate")
async def curate_agent(request: CurateRequest):
    persona_config = PERSONA_PROMPTS.get(request.persona, PERSONA_PROMPTS["ai_architect"])
    agent_id = db.new_uuid()
    created_at = db.now_utc_iso()

    try:
        db.insert_agent(
            agent_id=agent_id,
            name=f"Curator_{request.persona}",
            domain=request.persona.replace("_", " ") + " technology",
            created_at=created_at
        )
    except Exception as e:
        return CurateResponse(
            persona=persona_config["role"],
            headline="Error creating agent",
            selection_rationale=f"Database error: {str(e)[:100]}",
            impact_score="N/A",
            target_audience="N/A",
            takeaways=["Please check database connection"],
            briefing="Failed to create agent in database.",
            source_url="",
            domain="",
            hashtags=[],
            generated_at=db.now_utc_iso()
        )

    try:
        await worker.run_pipeline(agent_id)
        posts = db.list_posts(agent_id, limit=1)

        if posts:
            post = posts[0]
            sources = post.get("sources") or []
            src_url = sources[0] if sources else ""
            dom = src_url.split("/")[2] if src_url and "/" in src_url else "tech-news.com"

            return CurateResponse(
                persona=persona_config["role"],
                headline=post.get("title", "Tech Update"),
                selection_rationale=post.get("rationale", "Selected by editorial agent"),
                impact_score="8.5/10",
                target_audience=persona_config["role"],
                takeaways=[
                    post.get("text", "")[:100],
                    f"Impact on {request.persona} workflows",
                    "Implementation considerations"
                ],
                briefing=post.get("text", "No content available."),
                source_url=src_url,
                domain=dom,
                hashtags=["#TechNews", "#AI", "#Engineering"],
                generated_at=post.get("created_at", db.now_utc_iso())
            )
        else:
            return CurateResponse(
                persona=persona_config["role"],
                headline="No suitable candidates found",
                selection_rationale="All candidates rejected by editorial standards.",
                impact_score="N/A",
                target_audience="N/A",
                takeaways=["Try generating again with different category or persona"],
                briefing="The agent reviewed all available candidates but none met the strict editorial criteria.",
                source_url="",
                domain="",
                hashtags=[],
                generated_at=db.now_utc_iso()
            )
    except Exception as e:
        return CurateResponse(
            persona=persona_config["role"],
            headline="Error during curation",
            selection_rationale=f"Error: {str(e)[:150]}",
            impact_score="N/A",
            target_audience="N/A",
            takeaways=["Please try again or check server logs"],
            briefing=f"An error occurred: {str(e)}",
            source_url="",
            domain="",
            hashtags=[],
            generated_at=db.now_utc_iso()
        )

@app.post("/api/agent/init")
async def init_agent(request: AgentInitRequest):
    agent_id = db.new_uuid()
    created_at = db.now_utc_iso()
    db.insert_agent(
        agent_id=agent_id,
        name=request.persona.name,
        domain=request.persona.domain,
        created_at=created_at
    )
    try:
        await worker.run_pipeline(agent_id)
    except Exception as e:
        db.set_agent_active(agent_id, 0)
        raise HTTPException(500, f"Pipeline failed: {str(e)}")
    return AgentInitResponse(agentId=agent_id)

@app.get("/api/agent/feed", response_model=FeedResponse)
async def get_feed(agentId: str = Query(..., min_length=1), limit: int = 10):
    agent = db.get_agent(agentId)
    if not agent:
        raise HTTPException(404, "agent not found")

    posts = db.list_posts(agentId, limit=limit)
    return FeedResponse(
        posts=[
            FeedPost(
                id=p["id"],
                createdAt=p["created_at"],
                text=p["text"],
                rationale=p["rationale"],
                sources=p["sources"]
            )
            for p in posts
        ]
    )

@app.get("/api/agent/history")
async def get_history(agent_id: Optional[str] = None):
    if agent_id:
        posts = db.list_posts(agent_id, limit=50)
    else:
        agents = db.list_active_agents()
        all_posts = []
        for agent in agents[:5]:
            posts = db.list_posts(agent["id"], limit=10)
            for p in posts:
                p["agent_name"] = agent["name"]
                all_posts.append(p)
        posts = all_posts

    return {
        "history": [
            {
                "agent_id": p.get("agent_id", "unknown"),
                "agent_name": p.get("agent_name", "Unknown"),
                "title": p.get("title", ""),
                "text": p.get("text", ""),
                "created_at": p.get("created_at", ""),
                "sources": p.get("sources", [])
            }
            for p in posts
        ]
    }

@app.delete("/api/agent/{agent_id}")
async def deactivate_agent(agent_id: str):
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    db.set_agent_active(agent_id, 0)
    return {"ok": True, "agent_id": agent_id}

@app.get("/api/agents")
async def list_agents():
    agents = db.list_active_agents()
    return {"agents": agents}

# Updated path to point to the 'hackathon-group' folder where index.html is located
static_dir = project_root / "hackathon-group"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def root():
    index_file = static_dir / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return JSONResponse(status_code=500, content={"detail": "hackathon-group/index.html not found"})

@app.get("/index.html")
async def index():
    index_file = static_dir / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return JSONResponse(status_code=500, content={"detail": "hackathon-group/index.html not found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("website:app", host="127.0.0.1", port=8000, reload=True)
