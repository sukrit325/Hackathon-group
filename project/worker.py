"""Per-agent worker pipeline.

Each tick:
  verify agent -> acquire lock -> discover -> normalize -> dedup ->
  retrieve memory -> LLM editorial decision -> validate -> source integrity ->
  content normalization -> hash -> atomic insert -> release lock.

Failure of any stage is logged; the lock is always released; APScheduler and
FastAPI are never crashed by a worker exception.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import db
import discovery
import llm
from config import get_settings
from schemas import EditorialDecision

logger = logging.getLogger("worker")

# Per-agent in-process locks. Created lazily under a guard lock to prevent
# two coroutines from creating two locks for the same agent.
_agent_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _get_agent_lock(agent_id: str) -> asyncio.Lock:
    async with _locks_guard:
        lk = _agent_locks.get(agent_id)
        if lk is None:
            lk = asyncio.Lock()
            _agent_locks[agent_id] = lk
        return lk


_WS_RE = re.compile(r"\s+")


def normalize_text(t: str) -> str:
    return _WS_RE.sub(" ", (t or "")).strip().lower()


def content_hash(title: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(normalize_text(title).encode("utf-8"))
    h.update(b"|")
    h.update(normalize_text(text).encode("utf-8"))
    return h.hexdigest()


def _validate_decision(raw: dict, candidate_urls: set[str]) -> EditorialDecision:
    """Validate LLM output strictly. Raises ValueError on any violation."""
    if not isinstance(raw, dict):
        raise ValueError("LLM output is not a JSON object")
    try:
        d = EditorialDecision.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"LLM output schema invalid: {exc}") from exc

    if d.decision == "PUBLISH":
        s = get_settings()
        if not d.title or len(d.title) < s.min_title_length:
            raise ValueError("title too short")
        if len(d.title) > s.max_title_length:
            raise ValueError("title too long")
        if not d.text or len(d.text) < s.min_post_length:
            raise ValueError("text too short")
        if len(d.text) > s.max_post_length:
            raise ValueError("text too long")
        if not isinstance(d.sources, list):
            raise ValueError("sources must be a list")
        if len(d.sources) < s.min_sources or len(d.sources) > s.max_sources:
            raise ValueError("source count out of bounds")
        # Source integrity: every source URL must come from the discovered set.
        for u in d.sources:
            nu = discovery.normalize_url(u)
            if not nu or nu not in candidate_urls:
                raise ValueError(f"unknown source URL: {u}")
    return d


async def run_worker_tick(
    agent_id: str,
    db_path: Optional[str] = None,
    provider: Optional[llm.LLMProvider] = None,
) -> None:
    """Execute one worker tick for an agent. Never raises."""
    start = time.monotonic()
    log_ctx = {"agent_id": agent_id}
    try:
        agent = db.get_agent(agent_id, db_path=db_path)
        if not agent:
            logger.warning("worker tick for unknown agent %s", agent_id, extra=log_ctx)
            return
        if not agent["active"]:
            logger.info("worker tick for inactive agent %s; skipping", agent_id, extra=log_ctx)
            return

        lock = await _get_agent_lock(agent_id)
        # APScheduler max_instances=1 already prevents overlap for scheduled
        # runs, but the immediate first-run task bypasses the scheduler. The
        # asyncio.Lock closes that gap.
        async with lock:
            log_ctx["agent_name"] = agent["name"]
            logger.info("worker tick start", extra=log_ctx)
            settings = get_settings()

            # Discovery
            try:
                candidates = await discovery.discover()
            except Exception as exc:
                logger.error("discovery failed: %s", exc, extra=log_ctx)
                return
            if not candidates:
                logger.info("no candidates; ending tick", extra=log_ctx)
                return

            # Dedup + top-N selection
            top_n = candidates[: settings.top_n_candidates]
            cand_dicts = [c.to_dict() for c in top_n]
            candidate_urls = {c.source_url for c in top_n}

            # Memory retrieval (capped at 10)
            memory = db.recent_posts_for_memory(agent_id, limit=10, db_path=db_path)

            # LLM call (bounded retries inside provider)
            prov = provider or llm.get_provider()
            try:
                raw = await prov.generate_editorial_decision(
                    candidates=cand_dicts,
                    memory=memory,
                    persona_name=agent["name"],
                    persona_domain=agent["domain"],
                )
            except llm.LLMError as exc:
                logger.error("LLM failed: %s", exc, extra=log_ctx)
                return
            except Exception as exc:
                # Defensive: provider contract violations must not escape.
                logger.exception("LLM provider raised unexpected error: %s", exc)
                return

            # Strict validation
            try:
                decision = _validate_decision(raw, candidate_urls)
            except ValueError as exc:
                logger.warning("LLM output rejected: %s | raw=%s", exc, raw, extra=log_ctx)
                return

            if decision.decision == "REJECT":
                logger.info(
                    "REJECT | rationale=%s", decision.rationale, extra=log_ctx
                )
                return

            # Content normalization + hash
            title = decision.title.strip()
            text = decision.text.strip()
            sources = [discovery.normalize_url(u) for u in decision.sources]
            sources = [u for u in sources if u]  # defensive
            chash = content_hash(title, text)
            post_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Atomic persistence; UNIQUE(agent_id, content_hash) is the durable
            # deduplication boundary.
            inserted = db.insert_post(
                post_id=post_id,
                agent_id=agent_id,
                created_at=created_at,
                title=title,
                text=text,
                rationale=decision.rationale.strip(),
                sources=sources,
                content_hash=chash,
                db_path=db_path,
            )
            if inserted:
                logger.info(
                    "PUBLISHED | post_id=%s | hash=%s | sources=%d",
                    post_id, chash[:12], len(sources), extra=log_ctx,
                )
            else:
                logger.info(
                    "DUPLICATE prevented by UNIQUE constraint | hash=%s",
                    chash[:12], extra=log_ctx,
                )
    except Exception:
        # Last-resort guard: a worker tick must never crash the scheduler.
        logger.exception("worker tick unhandled exception for agent %s", agent_id)
    finally:
        dur = time.monotonic() - start
        logger.info("worker tick end | duration=%.2fs", dur, extra=log_ctx)