"""Pydantic models for API request/response validation and LLM output parsing."""
from __future__ import annotations
import re
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

try:
    from pydantic import field_validator
    def _field_val(field_name):
        return field_validator(field_name)
except ImportError:
    from pydantic import validator
    def _field_val(field_name):
        return validator(field_name, allow_reuse=True)

_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})+$", re.I)
_MAX_NAME = 120
_MAX_DOMAIN = 253

class Persona(BaseModel):
    name: str = Field(..., min_length=1, max_length=_MAX_NAME)
    domain: str = Field(..., min_length=3, max_length=_MAX_DOMAIN)

    @_field_val("name")
    def _normalize_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @_field_val("domain")
    def _normalize_domain(cls, v: str) -> str:
        v = v.strip().lower()
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

class GenerateRequest(BaseModel):
    agentId: str = Field(..., min_length=1)

class GenerateResponse(BaseModel):
    generationId: str
    status: Literal["QUEUED"] = "QUEUED"

class GenerationStatusResponse(BaseModel):
    generationId: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "REJECTED", "FAILED"]
    postId: Optional[str] = None
    error: Optional[str] = None

class FeedPost(BaseModel):
    id: str
    createdAt: str
    text: str
    rationale: str
    sources: List[str]

class FeedResponse(BaseModel):
    posts: List[FeedPost]

class PostContent(BaseModel):
    text: str
    rationale: str
    sources: List[str] = Field(default_factory=list)

class EditorialDecision(BaseModel):
    """Strict schema for the LLM's editorial decision."""
    decision: Literal["PUBLISH", "REJECT"]
    reasoning: str
    selectedCandidateId: Optional[str] = None
    post: Optional[PostContent] = None

    @_field_val("reasoning")
    def _reasoning_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("reasoning must not be empty")
        return v.strip()
