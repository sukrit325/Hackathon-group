import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.editor import run_editor


def build_payload():
    return {
        "agent_name": "TechBot",
        "agent_domain": "technology",
        "current_utc_time": "2026-08-08T00:00:00Z",
        "postingHistory": [],
        "candidates": [
            {
                "id": "candidate-1",
                "title": "A practical open-source model benchmark report",
                "summary": "A benchmark report compares local inference performance for several small language models.",
                "publicationTimestamp": "2026-08-08T00:00:00Z",
                "sources": ["https://example.com/report"],
            }
        ],
    }


def test_run_editor_returns_valid_publish_payload():
    result = run_editor(build_payload())
    assert result["decision"] == "PUBLISH"
    assert result["selectedCandidateId"] == "candidate-1"
    assert result["post"]["sources"] == ["https://example.com/report"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
