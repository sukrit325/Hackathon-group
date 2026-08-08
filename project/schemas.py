"""Pydantic models for API request/response validation and LLM output parsing."""
from __future__ import annotations

import re
from typing import List, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})+$", re.I)
_MAX_NAME = 120
_MAX_DOMAIN = 253


class Persona(BaseModel):
    name: str = Field(..., min_length=1, max_length=_MAX_NAME)
    domain: str = Field(..., min_length=3, max_length=_MAX_DOMAIN)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, v: str) -> str:
        v = v.strip().lower()
        # Strip a scheme if the client provided one.
        if "://" in v:
            v = v.split("://", 1)[1]
        v = v.split("/", 1)[0]
        if not _DOMAIN_RE.match(v):
            raise ValueError("domain must be a valid DNS domain")
        return v


class AgentInitRequest(BaseModel):
    persona: Persona


class AgentInitResponse(BaseModel):
    agentId: str


class FeedPost(BaseModel):
    id: str
    createdAt: str
    text: str
    rationale: str
    sources: List[str]


class FeedResponse(BaseModel):
    posts: List[FeedPost]


# ---- LLM structured output ----------------------------------------------

class EditorialDecision(BaseModel):
    """Strict schema for the LLM's editorial decision."""
    decision: Literal["PUBLISH", "REJECT"]
    title: str | None = None
    text: str | None = None
    rationale: str
    sources: List[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _rationale_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rationale must not be empty")
        return v.strip()