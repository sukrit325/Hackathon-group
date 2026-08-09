"""Worker: publishing pipeline for agent using Breeth AI."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import db
from discovery import discover_candidates

# Import our agent (now using Breeth)
from Agents.src.news_editor import NewsEditorAgent

logger = logging.getLogger(__name__)

async def run_pipeline(agent_id: str) -> None:
    """
    Run the complete publishing pipeline for an agent using Breeth AI.
    """
    try:
        agent = db.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        
        agent_name = agent["name"]
        agent_domain = agent["domain"]
        
        candidates = await discover_candidates()
        
        if not candidates:
            logger.warning(f"No candidates found for agent {agent_id}")
            return
        
        posting_history = db.list_posts(agent_id, limit=50)
        memory_context = [
            {"title": p["title"], "text": p["text"], "sources": p.get("sources", [])}
            for p in posting_history
        ]
        
        # Breeth semantic retrieval (optional)
        try:
            from breeth_client import get_semantic_memories
            semantic_memories = await get_semantic_memories(agent_id)
            memory_context.extend(semantic_memories)
        except Exception as e:
            logger.warning(f"Breeth retrieval failed, falling back to SQLite: {e}")
        
        agent_config = {
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "current_utc_time": db.now_utc_iso()
        }
        
        editor = NewsEditorAgent(agent_config)
        
        formatted_candidates = []
        for c in candidates:
            formatted_candidates.append({
                "id": c.get("id", f"cand_{len(formatted_candidates)}"),
                "title": c.get("title", ""),
                "summary": c.get("summary", ""),
                "content": c.get("content", ""),
                "timestamp": c.get("timestamp", db.now_utc_iso()),
                "sources": c.get("sources", [])
            })
        
        formatted_history = []
        for m in memory_context:
            formatted_history.append({
                "title": m.get("title", ""),
                "text": m.get("text", ""),
                "sources": m.get("sources", []),
                "created_at": m.get("created_at", db.now_utc_iso())
            })
        
        decision = editor.evaluate_and_select(formatted_candidates, formatted_history)
        
        if decision.get("decision") == "PUBLISH":
            selected_id = decision.get("candidate_id")
            selected = None
            for c in formatted_candidates:
                if c["id"] == selected_id:
                    selected = c
                    break
            
            if selected:
                post_id = db.new_uuid()
                content_hash = f"{agent_id}_{post_id}"
                
                success = db.insert_post(
                    post_id=post_id,
                    agent_id=agent_id,
                    created_at=db.now_utc_iso(),
                    title=selected.get("title", "Untitled"),
                    text=decision.get("post", ""),
                    rationale=decision.get("rationale", ""),
                    sources=decision.get("sources", []),
                    content_hash=content_hash
                )
                
                if success:
                    logger.info(f"Published post for agent {agent_id}")
                    
                    try:
                        from breeth_client import write_memory
                        await write_memory(
                            agent_id=agent_id,
                            text=decision.get("post", ""),
                            metadata={
                                "title": selected.get("title", ""),
                                "rationale": decision.get("rationale", ""),
                                "sources": decision.get("sources", [])
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Breeth memory write failed: {e}")
                else:
                    logger.warning(f"Duplicate post prevented for agent {agent_id}")
            else:
                logger.warning(f"Selected candidate not found: {selected_id}")
        else:
            logger.info(f"Agent {agent_id} rejected all candidates: {decision.get('rationale', 'No rationale')}")
            
    except Exception as e:
        logger.exception(f"Pipeline failed for agent {agent_id}: {e}")
        raise