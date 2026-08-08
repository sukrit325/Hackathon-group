from src.validator import validate_output


def test_validate_publish_output():
    output = {
        "decision": "PUBLISH",
        "reasoning": "Selected a high-signal candidate",
        "selectedCandidateId": "candidate-1",
        "post": {
            "text": "A concise post",
            "rationale": "This is a test.",
            "sources": ["https://example.com"],
        },
    }
    assert validate_output(output) is True


def test_validate_reject_output():
    output = {
        "decision": "REJECT",
        "reasoning": "No candidate passed",
        "selectedCandidateId": None,
        "post": None,
    }
    assert validate_output(output) is True
