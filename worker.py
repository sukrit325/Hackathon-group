"""Worker: publishing pipeline for agent with per-agent concurrency locks and generation tracking."""
import asyncio
import logging
from typing import Optional, Dict
import db
import discovery
import llm
from Agents.src.news_editor import NewsEditorAgent
from Agents.src.validator import validate_decision

logger = logging.getLogger(__name__)

_AGENT_LOCKS: Dict[str, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()

async def get_agent_lock(agent_id: str) -> asyncio.Lock:
    async with _LOCKS_GUARD:
        if agent_id not in _AGENT_LOCKS:
            _AGENT_LOCKS[agent_id] = asyncio.Lock()
        return _AGENT_LOCKS[agent_id]

async def run_pipeline(
    agent_id: str,
    generation_id: Optional[str] = None,
    trigger: str = "SCHEDULED",
) -> None:
    """Run the complete publishing pipeline for an agent."""
    lock = await get_agent_lock(agent_id)
    if lock.locked():
        logger.warning(f"Worker execution already running for agent {agent_id}. Skipping.")
        if generation_id:
            db.update_generation(generation_id, "FAILED", error_message="Generation already in progress for this agent.")
        return

    async with lock:
        if generation_id:
            db.update_generation(generation_id, "RUNNING")

        try:
            agent = db.get_agent(agent_id)
            if agent is None:
                raise ValueError(f"Agent {agent_id} not found")
            if not agent.get("active", 1):
                raise ValueError(f"Agent {agent_id} is inactive")

            # Discovery
            raw_candidates = await discovery.discover()
            candidates = [c.to_dict() if hasattr(c, "to_dict") else c for c in raw_candidates]

            if not candidates:
                logger.warning(f"No candidates found for agent {agent_id}")
                if generation_id:
                    db.update_generation(generation_id, "REJECTED")
                return

            # Memory retrieval
            posting_history = db.list_posts(agent_id, limit=50)
            memory_context = [
                {
                    "title": p["title"],
                    "text": p["text"],
                    "sources": p.get("sources", []),
                    "created_at": p.get("created_at", db.now_utc_iso()),
                }
                for p in posting_history
            ]

            try:
                from breeth_client import get_semantic_memories
                semantic_memories = await get_semantic_memories(agent_id)
                memory_context.extend(semantic_memories)
            except Exception as e:
                logger.warning(f"Breeth retrieval failed: {e}")

            formatted_candidates = []
            for idx, c in enumerate(candidates):
                c_id = c.get("id") or f"cand_{idx}"
                sources = c.get("sources") or []
                if not sources and c.get("source_url"):
                    sources = [c["source_url"]]
                formatted_candidates.append({
                    "id": c_id,
                    "title": c.get("title", ""),
                    "summary": c.get("summary", ""),
                    "content": c.get("content", ""),
                    "timestamp": c.get("timestamp") or c.get("published_at") or db.now_utc_iso(),
                    "sources": sources,
                })

            # Use agent data retrieved directly via database
            agent_instance = NewsEditorAgent(agent)
            decision = await agent_instance.evaluate_and_select(formatted_candidates, memory_context)

            if decision.get("decision") == "PUBLISH":
                # Validate against AGENTS.md contract
                is_valid = validate_decision(decision, formatted_candidates)
                if not is_valid:
                    logger.warning(f"Decision failed validation for agent {agent_id}")
                    if generation_id:
                        db.update_generation(generation_id, "REJECTED")
                    return

                selected_id = decision.get("selectedCandidateId") or decision.get("candidate_id")
                selected_candidate = next((c for c in formatted_candidates if c["id"] == selected_id), None)

                post_data = decision.get("post")
                if isinstance(post_data, dict):
                    post_text = post_data.get("text", "")
                    post_rationale = post_data.get("rationale", "")
                    post_sources = post_data.get("sources", [])
                else:
                    post_text = str(post_data or "")
                    post_rationale = decision.get("rationale", "")
                    post_sources = decision.get("sources", [])

                title = selected_candidate.get("title", "Untitled") if selected_candidate else "Untitled"
                post_id = db.new_uuid()
                primary_source = post_sources[0] if post_sources else (selected_candidate["sources"][0] if selected_candidate and selected_candidate["sources"] else "")
                content_hash = f"{agent_id}_{primary_source}" if primary_source else f"{agent_id}_{post_id}"

                db_path_for_ops = getattr(db, '_last_db_path', None)
                inserted = db.insert_post(
                    post_id=post_id,
                    agent_id=agent_id,
                    created_at=db.now_utc_iso(),
                    title=title,
                    text=post_text,
                    rationale=post_rationale,
                    sources=post_sources,
                    content_hash=content_hash,
                    db_path=db_path_for_ops,
                )

                if inserted:
                    logger.info(f"Published post {post_id} for agent {agent_id} (trigger={trigger})")
                    if generation_id:
                        db.update_generation(generation_id, "COMPLETED", post_id=post_id)
                    try:
                        from breeth_client import write_memory
                        await write_memory(
                            agent_id=agent_id,
                            text=post_text,
                            metadata={
                                "title": title,
                                "rationale": post_rationale,
                                "sources": post_sources,
                            },
                        )
                    except Exception as e:
                        logger.warning(f"Breeth memory write failed: {e}")
                else:
                    logger.warning(f"Duplicate post prevented for agent {agent_id}")
                    if generation_id:
                        db.update_generation(generation_id, "REJECTED")
            else:
                logger.info(f"Agent {agent_id} rejected all candidates: {decision.get('reasoning') or decision.get('rationale')}")
                if generation_id:
                    db.update_generation(generation_id, "REJECTED")

        except Exception as e:
            logger.exception(f"Pipeline failed for agent {agent_id}: {e}")
            if generation_id:
                db.update_generation(generation_id, "FAILED", error_message="Internal processing error occurred.")

async def run_worker_tick(agent_id: str) -> bool:
    """Compatibility helper used by tests: a single tick that attempts to publish."""
    try:
        agent = db.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        raw_candidates = await discovery.discover()
        candidates = [c.to_dict() if hasattr(c, "to_dict") else c for c in raw_candidates]
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
        return False
    except Exception as e:
        logger.exception(f"run_worker_tick failed for {agent_id}: {e}")
        raise