"""RSS/HTTP discovery for candidate articles."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlparse

import feedparser
import httpx

from config import get_settings

logger = logging.getLogger("discovery")


@dataclass
class Candidate:
    title: str
    summary: str
    source_url: str
    published_at: str
    source_name: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "source_name": self.source_name,
        }


async def discover(urls: Optional[List[str]] = None) -> List[Candidate]:
    settings = get_settings()
    sources = urls or settings.rss_sources
    candidates: List[Candidate] = []
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        for url in sources[: settings.max_candidates]:
            try:
                response = await client.get(url)
                response.raise_for_status()
                parsed = feedparser.parse(response.text)
                for entry in parsed.entries[: settings.top_n_candidates]:
                    published = entry.get("published") or entry.get("updated") or ""
                    if published:
                        try:
                            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                        except ValueError:
                            dt = datetime.now(timezone.utc)
                        age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
                        if age > timedelta(hours=settings.rss_max_age_hours):
                            continue
                    title = (entry.get("title") or "Untitled").strip()
                    summary = (entry.get("summary") or entry.get("description") or "").strip()
                    source_url = entry.get("link") or ""
                    source_name = parsed.feed.get("title") or urlparse(url).netloc or "feed"
                    if source_url:
                        candidates.append(
                            Candidate(
                                title=title,
                                summary=summary,
                                source_url=source_url,
                                published_at=published or datetime.now(timezone.utc).isoformat(),
                                source_name=source_name,
                            )
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Discovery failed for %s: %s", url, exc)
    return candidates[: settings.max_candidates]
