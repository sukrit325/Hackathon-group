"""Worker: publishing pipeline for agent."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import db
from discovery import discover_candidates
from llm import get_provider

logger = logging.getLogger(__name__)


async def run_pipeline(agent_id: str) -> None:
    """
    Run the complete publishing pipeline for an agent:
    Discovery → Memory → Editorial filtering → Gemini → Validation → Persistence
    """
    try:
        # 1. Get agent
        agent = db.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        
        agent_name = agent["name"]
        agent_domain = agent["domain"]
        
        # 2. Discovery: fetch candidates
        candidates = await discover_candidates()
        
        if not candidates:
            logger.warning(f"No candidates found for agent {agent_id}")
            return
        
        # 3. Get recent memory from SQLite
        posting_history = db.list_posts(agent_id, limit=50)
        memory_context = [
            {"text": p["text"], "sources": p.get("sources", [])}
            for p in posting_history
        ]
        
        # 4. Breeth semantic retrieval (optional, fallback to SQLite)
        try:
            from breeth_client import get_semantic_memories
            semantic_memories = await get_semantic_memories(agent_id)
            memory_context.extend(semantic_memories)
        except Exception as e:
            logger.warning(f"Breeth retrieval failed, falling back to SQLite: {e}")
        
        # 5. Run agent editorial pipeline
        from Agents.src.news_editor import build_system_prompt, call_llm, validate_decision
        
        agent_input = {
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "current_utc_time": db.now_utc_iso(),
            "posting_history": memory_context,
            "candidates": candidates
        }
        
        # Build prompt and call LLM
        system_prompt = build_system_prompt(**agent_input)
        response_text = call_llm(system_prompt)
        decision = json.loads(response_text)
        
        # Validate decision
        if not validate_decision(decision, candidates):
            logger.warning(f"Validation failed for agent {agent_id}")
            return
        
        # 6. If PUBLISH, persist to SQLite
        if decision["decision"] == "PUBLISH":
            selected = next(c for c in candidates if c["id"] == decision["selectedCandidateId"])
            
            db.insert_post(
                agent_id=agent_id,
                text=decision["post"]["text"],
                rationale=decision["post"]["rationale"],
                sources=decision["post"]["sources"],
                created_at=db.now_utc_iso(),
            )
            
            # 7. Write to Breeth memory (optional)
            try:
                from breeth_client import write_memory
                await write_memory(
                    agent_id=agent_id,
                    text=decision["post"]["text"],
                    metadata={
                        "rationale": decision["post"]["rationale"],
                        "sources": decision["post"]["sources"]
                    }
                )
            except Exception as e:
                logger.warning(f"Breeth memory write failed: {e}")
            
            logger.info(f"Published post for agent {agent_id}")
        else:
            logger.info(f"Agent {agent_id} rejected all candidates")
            
    except Exception as e:
        logger.exception(f"Pipeline failed for agent {agent_id}: {e}")
        raise