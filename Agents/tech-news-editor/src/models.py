"""
Data models for the Autonomous Technology News Editor.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class Post(BaseModel):
    """A published post."""
    text: str
    rationale: str
    sources: List[str]


class Decision(BaseModel):
    """Final decision output."""
    decision: str  # "PUBLISH" or "REJECT"
    reasoning: str
    selectedCandidateId: Optional[str] = None
    post: Optional[Post] = None


class Candidate(BaseModel):
    """A news candidate."""
    id: str
    title: str
    summary: str
    timestamp: str
    sources: List[str]


class InputData(BaseModel):
    """Input data structure."""
    agent_name: str
    agent_domain: str
    current_utc_time: str
    posting_history: List[Dict[str, Any]]
    candidates: List[Candidate]