"""Per-agent worker pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import db
import discovery
import llm
from config import get_settings
from schemas import EditorialDecision

logger = logging.getLogger("worker")

_agent_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _get_agent_lock(agent_id: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _agent_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            _agent_locks[agent_id] = lock
        return lock


def _candidate_to_dict(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return candidate
    if hasattr(candidate, "to_dict"):
        return candidate.to_dict()
    return {"title": str(candidate), "summary": "", "source_url": "", "published_at": "", "source_name": ""}


def _normalize_content(value: str, max_length: int) -> str:
    value = " ".join(value.split()).strip()
    if len(value) > max_length:
        value = value[: max_length - 1].rstrip() + "…"
    return value


def _validate_decision(decision: EditorialDecision, candidates: list[dict[str, Any]]) -> bool:
    settings = get_settings()
    candidate_urls = {candidate.get("source_url", "") for candidate in candidates if candidate.get("source_url")}
    if not decision.source_url:
        return False
    if decision.source_url not in candidate_urls:
        return False
    if not decision.source_urls:
        return False
    if any(url not in candidate_urls for url in decision.source_urls):
        return False
    if not (settings.min_title_length <= len(decision.title) <= settings.max_title_length):
        return False
    if not (settings.min_post_length <= len(decision.body) <= settings.max_post_length):
        return False
    return True


async def run_worker_tick(agent_id: str) -> bool:
    settings = get_settings()
    agent = db.get_agent(agent_id)
    if not agent or not agent.get("is_active"):
        logger.warning("Agent %s not found or inactive", agent_id)
        return False

    lock = await _get_agent_lock(agent_id)
    async with lock:
        candidates = await discovery.discover()
        if not candidates:
            logger.info("No candidates discovered for %s", agent_id)
            return False

        normalized_candidates = []
        for candidate in candidates[: settings.top_n_candidates]:
            item = _candidate_to_dict(candidate)
            item["title"] = _normalize_content(item.get("title", ""), settings.max_title_length)
            item["summary"] = _normalize_content(item.get("summary", ""), 1200)
            normalized_candidates.append(item)

        memory = db.list_posts(agent_id, limit=5)
        provider = llm.MockProvider() if settings.llm_provider.lower() == "mock" or not settings.llm_api_key else llm.OpenAIProvider()
        try:
            raw_decision = await provider.generate_editorial_decision(
                normalized_candidates,
                memory,
                agent["name"],
                agent["domain"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM generation failed for %s: %s", agent_id, exc)
            return False

        try:
            decision = EditorialDecision.model_validate(raw_decision)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Editorial decision invalid for %s: %s", agent_id, exc)
            return False

        if not _validate_decision(decision, normalized_candidates):
            logger.warning("Editorial decision rejected for %s due to validation", agent_id)
            return False

        title = _normalize_content(decision.title, settings.max_title_length)
        body = _normalize_content(decision.body, settings.max_post_length)
        source_url = decision.source_url
        source_urls = [url for url in decision.source_urls if url] or [source_url]
        content_hash = hashlib.sha256(f"{title}\n{body}\n{','.join(source_urls)}".encode("utf-8")).hexdigest()
        post_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        inserted = db.insert_post(
            post_id,
            agent_id,
            created_at,
            title,
            body,
            source_url,
            source_urls,
            content_hash,
        )
        if inserted:
            logger.info("Inserted new post for %s", agent_id)
        else:
            logger.info("Duplicate post skipped for %s", agent_id)
        return inserted
