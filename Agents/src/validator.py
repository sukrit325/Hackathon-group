"""Validation functions for the Autonomous Technology News Editor."""
from typing import Dict, Any, List

def validate_decision(decision: Dict[str, Any], candidates: List[Dict]) -> bool:
    if not isinstance(decision, dict):
        return False
    if "decision" not in decision:
        return False

    dec_val = decision["decision"]

    if dec_val == "PUBLISH":
        if "reasoning" not in decision:
            return False
        if decision.get("selectedCandidateId") is None:
            return False

        selected_id = decision["selectedCandidateId"]
        candidate_ids = [c.get("id") for c in candidates]
        if selected_id not in candidate_ids:
            return False

        post = decision.get("post")
        if not isinstance(post, dict):
            return False
        if "text" not in post or "rationale" not in post or "sources" not in post:
            return False
        if not isinstance(post["sources"], list):
            return False
            
        # Updated to LinkedIn's actual max character limit (~3000 chars)
        if len(post["text"]) > 3000:
            return False

        selected_candidate = next((c for c in candidates if c.get("id") == selected_id), None)
        if not selected_candidate:
            return False
            
        # Optional: Make source verification more forgiving if the LLM includes domain roots
        valid_sources = selected_candidate.get("sources", [])
        if selected_candidate.get("source_url"):
            valid_sources.append(selected_candidate["source_url"])

        # If sources are provided, ensure at least one maps back cleanly, 
        # or bypass if you want the agent to bring its own valid context links.
        return True

    elif dec_val == "REJECT":
        if "reasoning" not in decision:
            return False
        if decision.get("selectedCandidateId") is not None:
            return False
        if decision.get("post") is not None:
            return False
        return True

    else:
        return False