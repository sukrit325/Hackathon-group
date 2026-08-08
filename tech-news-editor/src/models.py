from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Candidate(BaseModel):
    id: str
    title: str
    summary: Optional[str] = None
    publicationTimestamp: Optional[str] = None
    sources: List[str] = Field(default_factory=list)


class EditorRequest(BaseModel):
    postingHistory: List[Dict[str, Any]] = Field(default_factory=list)
    candidates: List[Candidate] = Field(default_factory=list)


class Post(BaseModel):
    text: str
    rationale: str
    sources: List[str] = Field(default_factory=list)


class EditorResponse(BaseModel):
    decision: str
    reasoning: str
    selectedCandidateId: Optional[str] = None
    post: Optional[Post] = None
