"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _default_rss_sources() -> List[str]:
    raw = os.environ.get("RSS_SOURCES", "")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "https://hnrss.org/frontpage",
        "https://feeds.feedburner.com/oreilly/radar",
        "https://feeds.arstechnica.com/arstechnica/index",
    ]


@dataclass
class Settings:
    database_path: str = os.environ.get("DATABASE_PATH", "data/publisher.db")
    api_key: str | None = os.environ.get("API_KEY") or None
    llm_provider: str = os.environ.get("LLM_PROVIDER", "openai")
    llm_api_key: str | None = os.environ.get("LLM_API_KEY") or None
    llm_model: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_timeout: int = _env_int("LLM_TIMEOUT", 45)
    llm_max_retries: int = _env_int("LLM_MAX_RETRIES", 3)
    worker_interval_minutes: int = _env_int("WORKER_INTERVAL_MINUTES", 30)
    max_active_agents: int = _env_int("MAX_ACTIVE_AGENTS", 50)
    max_candidates: int = _env_int("MAX_CANDIDATES", 50)
    top_n_candidates: int = _env_int("TOP_N_CANDIDATES", 10)
    min_title_length: int = _env_int("MIN_TITLE_LENGTH", 8)
    max_title_length: int = _env_int("MAX_TITLE_LENGTH", 120)
    min_post_length: int = _env_int("MIN_POST_LENGTH", 40)
    max_post_length: int = _env_int("MAX_POST_LENGTH", 4000)
    min_sources: int = _env_int("MIN_SOURCES", 1)
    max_sources: int = _env_int("MAX_SOURCES", 5)
    rss_sources: List[str] = field(default_factory=_default_rss_sources)
    rss_max_age_hours: int = _env_int("RSS_MAX_AGE_HOURS", 72)
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")


_settings = Settings()


def get_settings() -> Settings:
    return _settings
