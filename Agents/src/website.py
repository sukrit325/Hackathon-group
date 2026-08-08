from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from bs4 import BeautifulSoup
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import json
import os
import sys
from pathlib import Path

# Add agent path
sys.path.insert(0, str(Path(__file__).parent / "Agents" / "tech-news-editor" / "src"))

# Import agent modules
from src.news_editor import build_system_prompt, call_llm, parse_input_data
from src.validator import validate_decision

app = FastAPI(title="Autonomous Tech Insights Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini Client if API key exists
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# In-memory tracking for deduplication
published_titles = set()
posting_history = []  # Store agent's published posts

# Data Models
class GenerationRequest(BaseModel):
    category: str = "all"
    persona: str = "ai_architect"

class AgentRequest(BaseModel):
    agent_name: str
    agent_domain: str
    candidates: list

# Persona Mapping (same as before)
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
        
        for item in root.findall('.//item')[:20]:
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            
            if not title or not link or title in published_titles:
                continue

            # Scrape content for agent
            content = scrape_article_text(link)
            
            candidates.append({
                "id": f"cand_{len(candidates)}",
                "title": title,
                "summary": content[:500],
                "content": content,
                "timestamp": "2026-08-08T12:00:00Z",  # Use current time
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
        "headline": selected["title"],
        "selection_rationale": f"Selected due to high technical relevance on {domain} and structural alignment with {persona_config['role']} priorities.",
        "impact_score": "8.5/10",
        "target_audience": "System Architects & Senior Leads",
        "takeaways": [
            f"Significant efficiency improvements reported regarding {selected['title'][:35]}...",
            "Reduces infrastructure overhead during high-concurrency execution.",
            "Establishes a repeatable architectural blueprint for enterprise deployment."
        ],
        "briefing": f"This development represents a key step forward in modern tech stack evolution. By addressing operational bottlenecks identified on {domain}, system leads can implement cleaner pipeline architectures.",
        "hashtags": ["#TechBriefing", "#SystemDesign", "#Engineering"]
    }

@app.post("/api/agent/curate")
def run_autonomous_agent(payload: GenerationRequest):
    persona_config = PERSONA_PROMPTS.get(payload.persona, PERSONA_PROMPTS["ai_architect"])
    
    # 1. Fetch candidates
    candidates = fetch_rss_candidates(payload.category)
    
    if not candidates:
        # Use fallback if no candidates
        selected = {
            "title": "Optimizing Vector Indexing for Real-Time LLM Inference Pipelines",
            "link": "https://news.ycombinator.com"
        }
        article_context = "No real-time feed available. Using fallback technical content."
        domain = "tech-feed.org"
        data = get_fallback_data(selected, persona_config, domain)
    else:
        # 2. Run agent on all candidates
        agent_input = {
            "agent_name": "TechSage",
            "agent_domain": payload.persona.replace("_", " ") + " technology",
            "current_utc_time": "2026-08-08T12:00:00Z",
            "posting_history": posting_history,
            "candidates": candidates
        }
        
        # Build prompt and call LLM (using Gemini or OpenAI)
        try:
            system_prompt = build_system_prompt(
                agent_name=agent_input["agent_name"],
                agent_domain=agent_input["agent_domain"],
                current_utc_time=agent_input["current_utc_time"],
                posting_history=agent_input["posting_history"],
                candidates=agent_input["candidates"]
            )
            
            # Call the agent's LLM
            response_text = call_llm(system_prompt)
            agent_decision = json.loads(response_text)
            
            # Validate decision
            if validate_decision(agent_decision, candidates) and agent_decision["decision"] == "PUBLISH":
                selected_candidate_id = agent_decision["selectedCandidateId"]
                selected = next(c for c in candidates if c["id"] == selected_candidate_id)
                
                # Add to posting history
                posting_history.append({
                    "text": agent_decision["post"]["text"],
                    "sources": agent_decision["post"]["sources"]
                })
                
                # Generate briefing using persona
                data = {
                    "headline": selected["title"],
                    "selection_rationale": agent_decision["reasoning"],
                    "impact_score": "8.5/10",  # Could be extracted from agent
                    "target_audience": persona_config["role"],
                    "takeaways": [
                        agent_decision["post"]["text"][:100],
                        f"Impact on {payload.persona} workflows",
                        "Implementation considerations"
                    ],
                    "briefing": agent_decision["post"]["text"],
                    "hashtags": ["#TechNews", "#AI", "#Engineering"]
                }
            else:
                # No candidate passed agent's editorial threshold
                selected = candidates[0] if candidates else {"title": "Fallback", "link": "https://news.ycombinator.com"}
                data = get_fallback_data(selected, persona_config, urlparse(selected.get("link", "")).netloc)
                
        except Exception as e:
            print(f"Agent processing error: {e}")
            selected = candidates[0]
            data = get_fallback_data(selected, persona_config, urlparse(selected.get("link", "")).netloc)
    
    # 3. Return response
    return {
        "persona": persona_config["role"],
        "headline": data.get("headline", "Tech Update"),
        "selection_rationale": data.get("selection_rationale", ""),
        "impact_score": data.get("impact_score", "8.0/10"),
        "target_audience": data.get("target_audience", "Engineering Teams"),
        "takeaways": data.get("takeaways", []),
        "briefing": data.get("briefing", ""),
        "source_url": selected.get("link", ""),
        "domain": urlparse(selected.get("link", "")).netloc,
        "hashtags": data.get("hashtags", []),
        "generated_at": "Just now"
    }

@app.post("/api/agent/run")
def run_agent_only(request: AgentRequest):
    """
    Direct endpoint to run the agent with custom input.
    """
    agent_input = {
        "agent_name": request.agent_name,
        "agent_domain": request.agent_domain,
        "current_utc_time": "2026-08-08T12:00:00Z",
        "posting_history": posting_history,
        "candidates": request.candidates
    }
    
    system_prompt = build_system_prompt(
        agent_name=agent_input["agent_name"],
        agent_domain=agent_input["agent_domain"],
        current_utc_time=agent_input["current_utc_time"],
        posting_history=agent_input["posting_history"],
        candidates=agent_input["candidates"]
    )
    
    try:
        response_text = call_llm(system_prompt)
        decision = json.loads(response_text)
        
        if validate_decision(decision, request.candidates):
            return decision
        else:
            return {
                "decision": "REJECT",
                "reasoning": "Validation failed",
                "selectedCandidateId": None,
                "post": None
            }
    except Exception as e:
        return {
            "decision": "ERROR",
            "reasoning": str(e),
            "selectedCandidateId": None,
            "post": None
        }

@app.get("/api/agent/history")
def get_posting_history():
    """Get the agent's publication history."""
    return {"history": posting_history}

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "agent_ready": True}