import json
from typing import Any, Dict, List

from src.validator import validate_output


def build_prompt(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def run_editor(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder editor logic that returns a deterministic structure.

    In a real implementation, this function would call an LLM or other model.
    """
    prompt = build_prompt(payload)
    result = {
        "decision": "REJECT",
        "reasoning": "No candidate passed the editorial threshold in the placeholder implementation.",
        "selectedCandidateId": None,
        "post": None,
    }

    if payload.get("candidates"):
        first_candidate = payload["candidates"][0]
        result = {
            "decision": "PUBLISH",
            "reasoning": f"The first candidate, {first_candidate.get('title', 'Untitled')}, was selected for demonstration purposes.",
            "selectedCandidateId": first_candidate.get("id"),
            "post": {
                "text": f"A concise placeholder post about {first_candidate.get('title', 'the selected story')}",
                "rationale": "This scaffold demonstrates the expected output shape for a tech-news editor.",
                "sources": first_candidate.get("sources", []),
            },
        }

    validated = validate_output(result)
    if not validated:
        raise ValueError("Generated output failed validation")

    return result
