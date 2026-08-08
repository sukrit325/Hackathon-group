from typing import Any, Dict, List, Optional


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_valid_post(post: Any) -> bool:
    if post is None:
        return True
    if not isinstance(post, dict):
        return False
    text = post.get("text")
    rationale = post.get("rationale")
    sources = post.get("sources")
    if not _is_nonempty_str(text) or len(text) > 280:
        return False
    if not _is_nonempty_str(rationale):
        return False
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        return False
    return True


def validate_output(output: Any) -> bool:
    """Validate the editor output shape used by tests.

    Expected shape (simplified):
    - decision: "PUBLISH" or "REJECT"
    - reasoning: non-empty string
    - selectedCandidateId: str or None
    - post: dict or None (if dict, must contain text, rationale, sources)
    """
    if not isinstance(output, dict):
        return False

    decision = output.get("decision")
    if decision not in ("PUBLISH", "REJECT"):
        return False

    reasoning = output.get("reasoning")
    if not _is_nonempty_str(reasoning):
        return False

    selected = output.get("selectedCandidateId")
    if selected is not None and not isinstance(selected, str):
        return False

    post = output.get("post")
    if not _is_valid_post(post):
        return False

    # Additional minimal sanity: if decision is PUBLISH, post must be present
    if decision == "PUBLISH" and post is None:
        return False

    return True
