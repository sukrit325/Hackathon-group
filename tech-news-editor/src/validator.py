from typing import Any, Dict, Optional


def validate_output(output: Dict[str, Any]) -> bool:
    if not isinstance(output, dict):
        return False

    if output.get("decision") not in {"PUBLISH", "REJECT"}:
        return False

    if output["decision"] == "REJECT":
        return output.get("selectedCandidateId") is None and output.get("post") is None

    if output["decision"] == "PUBLISH":
        if not output.get("selectedCandidateId"):
            return False
        post = output.get("post")
        if not isinstance(post, dict):
            return False
        if not isinstance(post.get("text"), str) or not post.get("text"):
            return False
        if not isinstance(post.get("rationale"), str) or not post.get("rationale"):
            return False
        if not isinstance(post.get("sources"), list):
            return False
        return True

    return False
