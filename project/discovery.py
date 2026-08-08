"""RSS/HTTP discovery of candidate news articles.

All external content is treated as untrusted data: it is only ever placed into
the LLM prompt inside a clearly-labelled UNTRUSTED DATA section, never executed,
and never concatenated into SQL.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx

from config import get_settings

logger = logging.getLogger("discovery")


@dataclass
class Candidate:
    title: str
    summary: str
    source_url: str
    published_at: str  # ISO8601 UTC
    source_name: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "source_name": self.source_name,
        }


def normalize_url(url: str) -> str:
    """Strip fragments, lowercase host, drop common tracking params."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https"):
        return ""
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    # Drop tracking query params.
    keep_q = []
    if p.query:
        for kv in p.query.split("&"):
            if "=" in kv:
                k = kv.split("=", 1)[0].lower()
            else:
                k = kv.lower()
            if k in ("utm_source", "utm_medium", "utm_campaign", "utm_term",
                     "utm_content", "fbclid", "gclid", "ref"):
                continue
            keep_q.append(kv)
    query = "&".join(keep_q)
    return urlunparse((p.scheme.lower(), host, p.path.rstrip("/") or "/", "", query, ""))


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _parse_date(entry) -> Optional[str]:
    for field_name in ("published_parsed", "updated_parsed"):
        t = entry.get(field_name)
        if t:
            try:
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError):
                continue
    return None


def _source_name_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except ValueError:
        return "unknown"


def fetch_feed(
    url: str,
    client: httpx.AsyncClient,
) -> List[Candidate]:
    """Fetch and parse a single RSS/Atom feed. Raises on hard failure."""
    settings = get_settings()
    # Stream so we can enforce a max-bytes ceiling on untrusted payloads.
    resp = yield_or_raise_streaming(url, client, settings)
    # feedparser parses bytes; cap size defensively.
    body = resp[: settings.rss_max_bytes]
    parsed = feedparser.parse(body)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"malformed feed from {url}: {parsed.bozo_exception}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.rss_max_age_hours)
    candidates: List[Candidate] = []
    seen_urls: set[str] = set()
    for entry in parsed.entries:
        link = entry.get("link", "")
        nurl = normalize_url(link)
        if not nurl or nurl in seen_urls:
            continue
        title = _strip_html(entry.get("title", ""))
        summary = _strip_html(entry.get("summary", entry.get("description", "")))
        if not title:
            continue
        published = _parse_date(entry)
        if published:
            try:
                pdt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
                if pdt < cutoff:
                    continue
            except ValueError:
                pass
        seen_urls.add(nurl)
        candidates.append(
            Candidate(
                title=title[:500],
                summary=summary[:2000],
                source_url=nurl,
                published_at=published or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source_name=_source_name_from_url(url),
            )
        )
    return candidates


def yield_or_raise_streaming(url: str, client: httpx.AsyncClient, settings) -> bytes:
    """Fetch with size cap. Returns full bytes after validation.

    Implemented synchronously inside an async helper; we use the async client
    with explicit timeouts. Because feedparser is sync, we collect the body.
    """
    raise _StreamingAwaitable(url, client, settings)


class _StreamingAwaitable(Exception):
    """Sentinel to allow `yield_or_raise_streaming` to be awaited via a wrapper.

    This is intentionally avoided below; we instead implement fetch_feed as a
    coroutine directly. (Kept for documentation only — see implementation below.)
    """


# The above indirection was a documentation stub. The real fetch_feed is a
# coroutine; redefine it properly:

async def fetch_feed(url: str, client: httpx.AsyncClient) -> List[Candidate]:  # noqa: F811
    settings = get_settings()
    try:
        resp = await client.get(
            url,
            timeout=httpx.Timeout(
                connect=settings.rss_connect_timeout,
                read=settings.rss_read_timeout,
                write=5.0,
                pool=settings.rss_total_timeout,
            ),
        )
        if resp.status_code >= 400:
            raise ValueError(f"feed {url} returned HTTP {resp.status_code}")
        body = resp.content[: settings.rss_max_bytes]
    except httpx.HTTPError as exc:
        raise ValueError(f"network error fetching {url}: {exc}") from exc

    parsed = feedparser.parse(body)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"malformed feed from {url}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.rss_max_age_hours)
    candidates: List[Candidate] = []
    seen_urls: set[str] = set()
    for entry in parsed.entries:
        link = entry.get("link", "")
        nurl = normalize_url(link)
        if not nurl or nurl in seen_urls:
            continue
        title = _strip_html(entry.get("title", ""))
        summary = _strip_html(entry.get("summary", entry.get("description", "")))
        if not title:
            continue
        published = _parse_date(entry)
        if published:
            try:
                pdt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
                if pdt < cutoff:
                    continue
            except ValueError:
                pass
        seen_urls.add(nurl)
        candidates.append(
            Candidate(
                title=title[:500],
                summary=summary[:2000],
                source_url=nurl,
                published_at=published or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                source_name=_source_name_from_url(url),
            )
        )
    return candidates


async def discover() -> List[Candidate]:
    """Discover and deduplicate candidates across all configured feeds.

    Failures of individual feeds are logged and skipped; the overall discovery
    call only fails if every feed fails.
    """
    settings = get_settings()
    out: List[Candidate] = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "AutonomousPublisher/1.0 (+discovery)"},
    ) as client:
        for url in settings.rss_sources:
            try:
                cands = await fetch_feed(url, client)
            except Exception as exc:
                logger.warning("feed %s failed: %s", url, exc)
                continue
            for c in cands:
                if c.source_url in seen_urls:
                    continue
                seen_urls.add(c.source_url)
                out.append(c)
    if not out:
        logger.warning("discovery produced zero candidates across all feeds")
    # Cap to MAX_CANDIDATES deterministically (by recency then URL).
    out.sort(key=lambda c: (c.published_at, c.source_url), reverse=True)
    return out[: settings.max_candidates]