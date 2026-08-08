"""Pydantic models for request/response validation and LLM output."""
from __future__ import annotations

import re
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})+$", re.I)
_MAX_NAME = 120
_MAX_DOMAIN = 253


class Persona(BaseModel):
    name: str = Field(..., min_length=1, max_length=_MAX_NAME)
    domain: str = Field(..., min_length=3, max_length=_MAX_DOMAIN)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        value = value.strip().lower()
        if not _DOMAIN_RE.match(value):
            raise ValueError("domain must look like a hostname")
        return value


class AgentInitRequest(BaseModel):
    persona: Persona


class AgentInitResponse(BaseModel):
    agentId: str


class PostOut(BaseModel):
    id: str
    agent_id: str
    title: str
    body: str
    source_url: str
    source_urls: List[str]
    created_at: str


class FeedResponse(BaseModel):
    posts: List[PostOut]


class EditorialDecision(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=6000)
    source_url: str = Field(..., min_length=1)
    source_urls: List[str] = Field(default_factory=list)
    reason: str = Field(default="")

    @field_validator("source_urls")
    @classmethod
    def _ensure_sources(cls, value: List[str]) -> List[str]:
        return [item.strip() for item in value if item and item.strip()]
