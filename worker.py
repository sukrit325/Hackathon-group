"""Worker: publishing pipeline for agent."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import db
import discovery
import llm

# Import our agent (now using Breeth)
from Agents.src.news_editor import NewsEditorAgent

logger = logging.getLogger(__name__)


async def run_pipeline(agent_id: str) -> None:
    """
    Run the complete publishing pipeline for an agent:
    Discovery → Memory → Editorial filtering → Breeth AI → Validation → Persistence
    """
    try:
        # 1. Get agent
        agent = db.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        
        agent_name = agent["name"]
        agent_domain = agent["domain"]
        
        # 2. Discovery: fetch candidates
        raw_candidates = await discovery.discover()
        # Normalize candidates to dicts (support objects with to_dict for tests)
        candidates = [c.to_dict() if hasattr(c, "to_dict") else c for c in raw_candidates]
        
        if not candidates:
            logger.warning(f"No candidates found for agent {agent_id}")
            return
        
        # 3. Get recent memory from SQLite
        posting_history = db.list_posts(agent_id, limit=50)
        memory_context = [
            {"title": p["title"], "text": p["text"], "sources": p.get("sources", [])}
            for p in posting_history
        ]
        
        # 4. Breeth semantic retrieval (optional)
        try:
            from breeth_client import get_semantic_memories
            semantic_memories = await get_semantic_memories(agent_id)
            memory_context.extend(semantic_memories)
        except Exception as e:
            logger.warning(f"Breeth retrieval failed, falling back to SQLite: {e}")
        
        # 5. Prepare agent config
        agent_config = {
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "current_utc_time": db.now_utc_iso()
        }
        
        # 6. Initialize and run the news editor agent
        editor = NewsEditorAgent(agent_config)
        
        # Convert candidates to the format expected by the agent
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
        
        # Convert memory to the format expected by the agent
        formatted_history = []
        for m in memory_context:
            formatted_history.append({
                "title": m.get("title", ""),
                "text": m.get("text", ""),
                "sources": m.get("sources", []),
                "created_at": m.get("created_at", db.now_utc_iso())
            })
        
        # 7. Run editorial evaluation
        decision = editor.evaluate_and_select(formatted_candidates, formatted_history)
        
        # 8. Process the decision
        if decision.get("decision") == "PUBLISH":
            # Find the selected candidate
            selected_id = decision.get("candidate_id")
            selected = None
            for c in formatted_candidates:
                if c["id"] == selected_id:
                    selected = c
                    break
            
            if selected:
                # Insert post to SQLite
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
                    logger.info(f"✅ Published post for agent {agent_id}")
                    
                    # 9. Write to Breeth memory (optional)
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


async def run_worker_tick(agent_id: str) -> bool:
    """Compatibility helper used by tests: a single tick that attempts to publish the
    first discovered candidate. Returns True when a new post was inserted, False when
    no insertion (duplicate or no candidates).
    """
    try:
        agent = db.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        raw_candidates = await discovery.discover()
        candidates = [c.to_dict() if hasattr(c, "to_dict") else c for c in raw_candidates]

        # Use same database path discovered by db.get_agent when possible (test DB)
        db_path_for_ops = getattr(db, '_last_db_path', None)

        for data in candidates:
            source = (
                data.get("source_url")
                or (data.get("sources") and data.get("sources")[0])
                or data.get("source")
                or data.get("link")
                or ""
            )
            title = data.get("title", "Untitled")
            text = data.get("summary") or data.get("content") or ""

            content_hash = f"{agent_id}_{source}"
            post_id = db.new_uuid()

            print(f"DEBUG: Attempting insert: agent={agent_id} content_hash={content_hash} db_path={db_path_for_ops}")
            logger.debug(f"Attempting insert: agent={agent_id} content_hash={content_hash} db_path={db_path_for_ops}")
            inserted = db.insert_post(
                post_id=post_id,
                agent_id=agent_id,
                created_at=db.now_utc_iso(),
                title=title,
                text=text,
                rationale="",
                sources=[source] if source else [],
                content_hash=content_hash,
                db_path=db_path_for_ops,
            )

            if inserted:
                logger.info(f"Inserted post for agent {agent_id} (source={source})")
                return True

        # No new insertion
        return False
    except Exception as e:
        logger.exception(f"run_worker_tick failed for {agent_id}: {e}")
        raise