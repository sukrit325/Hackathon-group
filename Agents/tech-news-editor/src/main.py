#!/usr/bin/env python3
"""
Entry point for the Autonomous Technology News Editor.
"""

import json
import sys
import argparse
import os
from dotenv import load_dotenv

load_dotenv()

# Import from the local module
from src.news_editor import (
    parse_input_data,
    build_system_prompt,
    call_llm,
    validate_decision
)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Technology News Editor")
    parser.add_argument("--input", type=str, help="Input JSON file path; if not provided, read from stdin.")
    args = parser.parse_args()

    # Read input
    if args.input:
        with open(args.input, "r") as f:
            input_str = f.read()
    else:
        input_str = sys.stdin.read()

    if not input_str.strip():
        print(json.dumps({"error": "No input provided."}), file=sys.stderr)
        sys.exit(1)

    try:
        data = parse_input_data(input_str)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    # Build system prompt
    system_prompt = build_system_prompt(
        agent_name=data["agent_name"],
        agent_domain=data["agent_domain"],
        current_utc_time=data["current_utc_time"],
        posting_history=data["posting_history"],
        candidates=data["candidates"]
    )

    # Call LLM
    try:
        response_text = call_llm(system_prompt)
        decision = json.loads(response_text)
    except Exception as e:
        print(json.dumps({"error": f"LLM processing failed: {e}"}), file=sys.stderr)
        sys.exit(1)

    # Validate decision
    if not validate_decision(decision, data["candidates"]):
        decision = {
            "decision": "REJECT",
            "reasoning": "The LLM's initial decision did not satisfy validation constraints. Rejecting all candidates.",
            "selectedCandidateId": None,
            "post": None
        }

    # Output final decision
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()