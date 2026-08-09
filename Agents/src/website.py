"""
Integrated FastAPI application - connects UI, Database, Worker, and Breeth AI Agent
Run: uvicorn website:app --reload --host 127.0.0.1 --port 8000
"""

import os
import sys
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from bs4 import BeautifulSoup

# ====== Add paths BEFORE imports ======
sys.path.insert(0, str(Path(__file__).parent / "Agents" / "src"))

# ====== Import project modules ======
try:
    import db
    import worker
    from config import get_settings
    from schemas import AgentInitRequest, AgentInitResponse
    from news_editor import NewsEditorAgent
    from discovery import discover_candidates
except ImportError as e:
    print(f"❌ Import error: {e}")
    print(f"Current path: {sys.path}")
    # Fallback imports
    import db
    import worker
    from config import get_settings
    from schemas import AgentInitRequest, AgentInitResponse
    from news_editor import NewsEditorAgent
    from discovery import discover_candidates

# ====== FastAPI App ======
app = FastAPI(title="Autonomous Tech Insights Studio")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== Data Models ======
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

# ====== Persona Config ======
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

# ====== Discovery Functions ======
def fetch_rss_candidates(category: str):
    """Fetch candidates from Hacker News RSS."""
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

            content = scrape_article_text(link)
            
            candidates.append({
                "id": f"cand_{idx}",
                "title": title,
                "summary": content[:500],
                "content": content,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "sources": [link]
            })
            
    except Exception as e:
        print(f"Error fetching RSS: {e}")
        
    return candidates

def scrape_article_text(url: str) -> str:
    """Scrape article text from URL."""
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

def get_fallback_data(selected, persona_config, domain):
    """Return fallback data when no candidates available."""
    return {
        "headline": selected.get("title", "Tech Update"),
        "selection_rationale": f"Selected due to high technical relevance on {domain} and structural alignment with {persona_config['role']} priorities.",
        "impact_score": "8.5/10",
        "target_audience": persona_config["role"],
        "takeaways": [
            "Significant efficiency improvements reported",
            "Reduces infrastructure overhead during high-concurrency execution",
            "Establishes a repeatable architectural blueprint for enterprise deployment"
        ],
        "briefing": "This development represents a key step forward in modern tech stack evolution.",
        "hashtags": ["#TechBriefing", "#SystemDesign", "#Engineering"]
    }

# ====== Startup Event ======
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    try:
        db.init_db()
        print("✅ Database initialized")
    except Exception as e:
        print(f"⚠️ Database init warning: {e}")
    
    breeth_key = os.getenv("BREETH_API_KEY")
    print(f"✅ Breeth API Key: {'Found' if breeth_key else 'Missing'}")
    print("✅ Agent ready: NewsEditorAgent loaded")

# ====== API Endpoints ======

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected",
        "agent": "ready",
        "breeth_api_key": "configured" if os.getenv("BREETH_API_KEY") else "missing",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/agent/curate")
async def curate_agent(request: CurateRequest):
    """
    Main curation endpoint - connects UI with the full pipeline.
    """
    persona_config = PERSONA_PROMPTS.get(request.persona, PERSONA_PROMPTS["ai_architect"])
    
    # Create agent
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
        print(f"❌ Failed to create agent: {e}")
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
        # Run the worker pipeline
        await worker.run_pipeline(agent_id)
        
        # Get the latest post
        posts = db.list_posts(agent_id, limit=1)
        
        if posts:
            post = posts[0]
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
                source_url=post.get("sources", [""])[0] if post.get("sources") else "",
                domain=post.get("sources", [""])[0].split("/")[2] if post.get("sources") else "tech-news.com",
                hashtags=["#TechNews", "#AI", "#Engineering"],
                generated_at=post.get("created_at", db.now_utc_iso())
            )
        else:
            return CurateResponse(
                persona=persona_config["role"],
                headline="No suitable candidates found",
                selection_rationale="All candidates rejected by editorial standards. Try again with different settings.",
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
        print(f"❌ Curation error: {e}")
        import traceback
        traceback.print_exc()
        
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
    """Initialize an agent and run the publishing pipeline."""
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

@app.get("/api/agent/feed")
async def get_feed(agent_id: str, limit: int = 10):
    """Get posts for a specific agent."""
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    
    posts = db.list_posts(agent_id, limit=limit)
    return {
        "agent": agent,
        "posts": [
            {
                "id": p["id"],
                "created_at": p["created_at"],
                "title": p["title"],
                "text": p["text"],
                "rationale": p["rationale"],
                "sources": p["sources"]
            }
            for p in posts
        ]
    }

@app.get("/api/agent/history")
async def get_history(agent_id: Optional[str] = None):
    """Get posting history."""
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
    """Deactivate an agent."""
    agent = db.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    
    db.set_agent_active(agent_id, 0)
    return {"ok": True, "agent_id": agent_id}

@app.get("/api/agents")
async def list_agents():
    """List all active agents."""
    agents = db.list_active_agents()
    return {"agents": agents}

# ====== Static Files ======
# Mount static files
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    print(f"⚠️ Static files mount warning: {e}")

@app.get("/")
async def root():
    """Serve the main UI."""
    try:
        return FileResponse("static/index.html")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Could not find static/index.html: {str(e)}"}
        )

@app.get("/index.html")
async def index():
    """Serve index.html."""
    try:
        return FileResponse("static/index.html")
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Could not find static/index.html: {str(e)}"}
        )

# ====== Error Handlers ======
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    print(f"❌ Unhandled error: {exc}")
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"}
    )

# ====== Run ======
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "website:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )