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
        return [u.strip() for u in raw.split(",") if u.strip()]
    return [
        "https://hnrss.org/frontpage",
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
    ]

@dataclass(frozen=True)
class Settings:
    database_path: str = os.environ.get("DATABASE_PATH", "/tmp/publisher.db")
    api_key: str = os.environ.get("API_KEY", "")
    llm_provider: str = os.environ.get("LLM_PROVIDER", "openai")
    llm_api_key: str = os.environ.get("LLM_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_timeout: float = _env_float("LLM_TIMEOUT", 45.0)
    llm_max_retries: int = _env_int("LLM_MAX_RETRIES", 3)
    worker_interval_minutes: int = _env_int("WORKER_INTERVAL_MINUTES", 30)
    max_active_agents: int = _env_int("MAX_ACTIVE_AGENTS", 50)
    max_candidates: int = _env_int("MAX_CANDIDATES", 50)
    top_n_candidates: int = _env_int("TOP_N_CANDIDATES", 10)
    min_title_length: int = _env_int("MIN_TITLE_LENGTH", 8)
    max_title_length: int = _env_int("MAX_TITLE_LENGTH", 200)
    min_post_length: int = _env_int("MIN_POST_LENGTH", 200)
    max_post_length: int = _env_int("MAX_POST_LENGTH", 4000)
    min_sources: int = _env_int("MIN_SOURCES", 1)
    max_sources: int = _env_int("MAX_SOURCES", 5)
    rss_connect_timeout: float = _env_float("RSS_CONNECT_TIMEOUT", 8.0)
    rss_read_timeout: float = _env_float("RSS_READ_TIMEOUT", 15.0)
    rss_total_timeout: float = _env_float("RSS_TOTAL_TIMEOUT", 25.0)
    rss_max_bytes: int = _env_int("RSS_MAX_BYTES", 2 * 1024 * 1024)
    rss_max_age_hours: int = _env_int("RSS_MAX_AGE_HOURS", 72)
    agent_create_per_minute: int = _env_int("AGENT_CREATE_PER_MINUTE", 5)
    rss_sources: List[str] = field(default_factory=_default_rss_sources)

_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

def reset_settings() -> None:
    global _settings
    _settings = None
