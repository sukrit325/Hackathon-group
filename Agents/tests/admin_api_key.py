"""
Test using Breeth AI instead of Google Gemini.
"""

import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the Agents/src directory to path
project_root = Path(__file__).parent.parent.parent
agents_src = project_root / "Agents" / "src"
sys.path.insert(0, str(agents_src))

# Import from news_editor
from news_editor import NewsEditorAgent, build_system_prompt, call_llm

print("=== Testing with Breeth AI ===\n")

# Check if Breeth API key is set
breeth_key = os.getenv("BREETH_API_KEY")
if not breeth_key:
    print("❌ BREETH_API_KEY not set in .env file")
    print("Please add BREETH_API_KEY=your_key to your .env file")
    sys.exit(1)

print(f"✅ Breeth API key found: {breeth_key[:10]}...{breeth_key[-5:]}")

# Test the agent
print("\n1. Testing NewsEditorAgent with Breeth...")

agent = NewsEditorAgent({
    "agent_name": "TestBot",
    "agent_domain": "technology",
    "current_utc_time": "2026-08-08T12:00:00Z"
})

candidates = [
    {
        "id": "cand_1",
        "title": "AI Breakthrough in Natural Language Processing",
        "summary": "Researchers achieve 99.9% accuracy in NLP tasks",
        "content": "Full article content here...",
        "timestamp": "2026-08-08T10:00:00Z",
        "sources": ["https://example.com/article1"]
    },
    {
        "id": "cand_2",
        "title": "New Cybersecurity Framework Released",
        "summary": "Major update to enterprise security standards",
        "content": "Full article content here...",
        "timestamp": "2026-08-08T09:00:00Z",
        "sources": ["https://example.com/article2"]
    }
]

print("\n2. Running agent evaluation...")
try:
    decision = agent.evaluate_and_select(candidates, [])
    print(f"✅ Decision: {decision.get('decision')}")
    print(f"   Rationale: {decision.get('rationale', 'N/A')[:100]}...")
    
    if decision.get('decision') == 'PUBLISH':
        print(f"   Post: {decision.get('post', '')[:100]}...")
        print(f"   Candidate ID: {decision.get('candidate_id')}")
        print(f"   Sources: {decision.get('sources', [])}")
except Exception as e:
    print(f"❌ Agent evaluation failed: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ Test complete!")