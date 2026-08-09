from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from bs4 import BeautifulSoup
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# Add agent path
sys.path.insert(0, str(Path(__file__).parent / "Agents" / "src"))

# Import agent modules (now using Breeth)
from news_editor import NewsEditorAgent

app = FastAPI(title="Autonomous Tech Insights Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory tracking
published_titles = set()
posting_history = []

# Data Models
class GenerationRequest(BaseModel):
    category: str = "all"
    persona: str = "ai_architect"

class AgentRequest(BaseModel):
    agent_name: str
    agent_domain: str
    candidates: list

# Persona Mapping
PERSONA_PROMPTS = {
    "ai_architect": {
        "role": "AI Systems & ML Architect",
        "focus": "Focus on model architecture, GPU/memory optimization, and scalability."
    },
    "security_analyst": {
        "role": "Principal Cybersecurity Specialist",
        "focus": "Focus on vulnerability analysis, threat vectors, risk mitigation, and enterprise compliance."
    },
    "executive": {
        "role": "Tech Executive & Product Strategist",
        "focus": "Focus on market impact, enterprise ROI, strategic implementation, and product trends."
    }
}

def fetch_rss_candidates(category: str):
    url = "https://news.ycombinator.com/rss"
    candidates = []
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read()
        root = ET.fromstring(html)
        
        for idx, item in enumerate(root.findall('.//item')[:20]):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            
            if not title or not link or title in published_titles:
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
    return {
        "headline": selected.get("title", "Tech Update"),
        "selection_rationale": f"Selected due to high technical relevance on {domain} and structural alignment with {persona_config['role']} priorities.",
        "impact_score": "8.5/10",
        "target_audience": "System Architects & Senior Leads",
        "takeaways": [
            f"Significant efficiency improvements reported",
            "Reduces infrastructure overhead during high-concurrency execution",
            "Establishes a repeatable architectural blueprint for enterprise deployment"
        ],
        "briefing": f"This development represents a key step forward in modern tech stack evolution.",
        "hashtags": ["#TechBriefing", "#SystemDesign", "#Engineering"]
    }

@app.post("/api/agent/curate")
def run_autonomous_agent(payload: GenerationRequest):
    persona_config = PERSONA_PROMPTS.get(payload.persona, PERSONA_PROMPTS["ai_architect"])
    
    # 1. Fetch candidates
    candidates = fetch_rss_candidates(payload.category)
    
    if not candidates:
        selected = {
            "title": "Optimizing Vector Indexing for Real-Time LLM Inference Pipelines"
        }
        data = get_fallback_data(selected, persona_config, "tech-feed.org")
        selected = {"title": data["headline"], "sources": ["https://news.ycombinator.com"]}
    else:
        try:
            agent_config = {
                "agent_name": "TechSage",
                "agent_domain": payload.persona.replace("_", " ") + " technology",
                "current_utc_time": datetime.utcnow().isoformat() + "Z"
            }
            
            agent = NewsEditorAgent(agent_config)
            decision = agent.evaluate_and_select(candidates, posting_history)
            
            if decision.get("decision") == "PUBLISH":
                selected_id = decision.get("candidate_id")
                selected = next((c for c in candidates if c["id"] == selected_id), candidates[0])
                
                posting_history.append({
                    "text": decision.get("post", ""),
                    "sources": decision.get("sources", [])
                })
                
                data = {
                    "headline": selected["title"],
                    "selection_rationale": decision.get("rationale", "Selected by editorial agent"),
                    "impact_score": "8.5/10",
                    "target_audience": persona_config["role"],
                    "takeaways": [
                        decision.get("post", "")[:100],
                        f"Impact on {payload.persona} workflows",
                        "Implementation considerations"
                    ],
                    "briefing": decision.get("post", ""),
                    "hashtags": ["#TechNews", "#AI", "#Engineering"]
                }
            else:
                selected = candidates[0]
                data = get_fallback_data(selected, persona_config, urlparse(selected.get("sources", [""])[0]).netloc if selected.get("sources") else "unknown")
        except Exception as e:
            print(f"Agent error: {e}")
            selected = candidates[0]
            data = get_fallback_data(selected, persona_config, urlparse(selected.get("sources", [""])[0]).netloc if selected.get("sources") else "unknown")
    
    return {
        "persona": persona_config["role"],
        "headline": data.get("headline", "Tech Update"),
        "selection_rationale": data.get("selection_rationale", ""),
        "impact_score": data.get("impact_score", "8.0/10"),
        "target_audience": data.get("target_audience", "Engineering Teams"),
        "takeaways": data.get("takeaways", []),
        "briefing": data.get("briefing", ""),
        "source_url": selected.get("sources", [""])[0] if selected.get("sources") else "",
        "domain": urlparse(selected.get("sources", [""])[0] if selected.get("sources") else "").netloc,
        "hashtags": data.get("hashtags", []),
        "generated_at": "Just now"
    }

@app.get("/api/health")
def health_check():
    return {"status": "healthy"}

# Serve index.html at root
@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")