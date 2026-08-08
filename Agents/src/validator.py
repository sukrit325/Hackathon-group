"""
Validation functions for the Autonomous Technology News Editor.
"""

from typing import Dict, Any, List


def validate_decision(decision: Dict[str, Any], candidates: List[Dict]) -> bool:
    """
    Validate the decision object against the output contract and editorial rules.
    Returns True if valid, False otherwise.
    """
    if "decision" not in decision:
        return False

    if decision["decision"] == "PUBLISH":
        required_keys = ["decision", "reasoning", "selectedCandidateId", "post"]
        if not all(k in decision for k in required_keys):
            return False

        if decision["selectedCandidateId"] is None:
            return False

        candidate_ids = [c.get("id") for c in candidates]
        if decision["selectedCandidateId"] not in candidate_ids:
            return False

        post = decision["post"]
        if not isinstance(post, dict):
            return False
        if "text" not in post or "rationale" not in post or "sources" not in post:
            return False
        if not isinstance(post["sources"], list):
            return False
        if len(post["text"]) > 280:
            return False

        # Verify every source URL comes from the selected candidate's source list
        selected_candidate = next(c for c in candidates if c["id"] == decision["selectedCandidateId"])
        valid_sources = selected_candidate.get("sources", [])
        for url in post["sources"]:
            if url not in valid_sources:
                return False

        return True

    elif decision["decision"] == "REJECT":
        if "reasoning" not in decision:
            return False
        if decision.get("selectedCandidateId") is not None:
            return False
        if decision.get("post") is not None:
            return False
        return True

    else:
        return False