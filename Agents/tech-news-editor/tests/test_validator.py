"""
Unit tests for validator.py
"""

import pytest
from src.validator import validate_decision


def test_valid_publish_decision():
    """Test a valid PUBLISH decision passes validation."""
    decision = {
        "decision": "PUBLISH",
        "reasoning": "Good technical story.",
        "selectedCandidateId": "cand1",
        "post": {
            "text": "Critical vuln found in TLS 1.3.",
            "rationale": "Important security fix.",
            "sources": ["https://example.com/article"]
        }
    }
    candidates = [
        {"id": "cand1", "sources": ["https://example.com/article"]}
    ]
    assert validate_decision(decision, candidates) is True


def test_valid_reject_decision():
    """Test a valid REJECT decision passes validation."""
    decision = {
        "decision": "REJECT",
        "reasoning": "All candidates are promotional."
    }
    candidates = [{"id": "cand1", "sources": []}]
    assert validate_decision(decision, candidates) is True


def test_invalid_source_url():
    """Test that invalid source URLs cause failure."""
    decision = {
        "decision": "PUBLISH",
        "reasoning": "Good story.",
        "selectedCandidateId": "cand1",
        "post": {
            "text": "News.",
            "rationale": "Rationale.",
            "sources": ["https://fake.com/not-in-candidate"]
        }
    }
    candidates = [
        {"id": "cand1", "sources": ["https://real.com/article"]}
    ]
    assert validate_decision(decision, candidates) is False


def test_post_too_long():
    """Test that posts over 280 chars fail validation."""
    decision = {
        "decision": "PUBLISH",
        "reasoning": "Good story.",
        "selectedCandidateId": "cand1",
        "post": {
            "text": "a" * 281,
            "rationale": "Rationale.",
            "sources": ["https://example.com"]
        }
    }
    candidates = [
        {"id": "cand1", "sources": ["https://example.com"]}
    ]
    assert validate_decision(decision, candidates) is False


def test_missing_required_keys():
    """Test that missing keys fail validation."""
    decision = {
        "decision": "PUBLISH",
        "reasoning": "Good story."
        # missing selectedCandidateId and post
    }
    candidates = [{"id": "cand1", "sources": []}]
    assert validate_decision(decision, candidates) is False


def test_invalid_candidate_id():
    """Test that non-existent candidate ID fails validation."""
    decision = {
        "decision": "PUBLISH",
        "reasoning": "Good story.",
        "selectedCandidateId": "fake-id",
        "post": {
            "text": "News.",
            "rationale": "Rationale.",
            "sources": []
        }
    }
    candidates = [{"id": "cand1", "sources": []}]
    assert validate_decision(decision, candidates) is False


def test_reject_with_post_fails():
    """Test that REJECT with a post field fails validation."""
    decision = {
        "decision": "REJECT",
        "reasoning": "All bad.",
        "post": {"text": "Should not be here"}
    }
    candidates = []
    assert validate_decision(decision, candidates) is False


def test_reject_with_candidate_id_fails():
    """Test that REJECT with selectedCandidateId fails validation."""
    decision = {
        "decision": "REJECT",
        "reasoning": "All bad.",
        "selectedCandidateId": "cand1"
    }
    candidates = []
    assert validate_decision(decision, candidates) is False


def test_invalid_decision_value():
    """Test that invalid decision values fail validation."""
    decision = {"decision": "MAYBE"}
    candidates = []
    assert validate_decision(decision, candidates) is False