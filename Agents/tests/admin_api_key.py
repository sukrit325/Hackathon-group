"""
API tests for Google Gemini integration.
"""

import os
import json
import sys
from pathlib import Path
from src.news_editor import build_system_prompt, call_llm

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import google.generativeai as genai

def test_gemini_api_connection():
    """Test Gemini API connection and response."""
    print("\n=== TEST: Gemini API Connection ===")
    
    # Check API key
    api_key = os.getenv("GOOGLE_API_KEY")
    print(f"1. Checking API key: {'✅ Found' if api_key else '❌ Missing'}")
    
    if not api_key:
        print("❌ GOOGLE_API_KEY not set. Skipping test.")
        pytest.skip("GOOGLE_API_KEY not set")
    
    print("2. Configuring Gemini...")
    genai.configure(api_key=api_key)
    
    print("3. Creating model...")
    model = genai.GenerativeModel("gemini-1.5-pro")
    
    print("4. Sending test request...")
    try:
        response = model.generate_content(
            "Return a JSON object with key 'test' and value 'success'",
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
        )
        
        print(f"5. ✅ Response received: {len(response.text)} characters")
        print(f"6. Response: {response.text}")
        
        # Parse JSON
        print("7. Parsing JSON response...")
        data = json.loads(response.text)
        print(f"8. ✅ Valid JSON: {data}")
        assert data.get("test") == "success"
        
        return True
    except Exception as e:
        print(f"❌ API call failed: {e}")
        raise


def test_gemini_model_list():
    """Test listing available Gemini models."""
    print("\n=== TEST: Gemini Model List ===")
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY not set. Skipping test.")
        pytest.skip("GOOGLE_API_KEY not set")
    
    genai.configure(api_key=api_key)
    
    print("1. Listing available models...")
    try:
        models = genai.list_models()
        model_names = [m.name for m in models]
        print(f"2. Found {len(model_names)} models")
        
        # Check for Gemini models
        gemini_models = [m for m in model_names if "gemini" in m.lower()]
        print(f"3. Gemini models: {gemini_models}")
        
        if gemini_models:
            print("4. ✅ Gemini models available")
        else:
            print("4. ⚠️ No Gemini models found")
            
    except Exception as e:
        print(f"❌ Failed to list models: {e}")
        raise


def test_gemini_with_system_prompt():
    """Test Gemini with the full system prompt."""
    print("\n=== TEST: Gemini with System Prompt ===")
    
    from src.news_editor import build_system_prompt
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY not set. Skipping test.")
        pytest.skip("GOOGLE_API_KEY not set")
    
    print("1. Building system prompt...")
    system_prompt = build_system_prompt(
        agent_name="TestBot",
        agent_domain="AI testing",
        current_utc_time="2026-08-08T12:00:00Z",
        posting_history=[],
        candidates=[
            {
                "id": "test1",
                "title": "Test article",
                "summary": "This is a test.",
                "timestamp": "2026-08-08T10:00:00Z",
                "sources": ["https://test.com"]
            }
        ]
    )
    print(f"2. Prompt built: {len(system_prompt)} characters")
    
    print("3. Configuring Gemini...")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")
    
    print("4. Sending request to Gemini...")
    try:
        response = model.generate_content(
            system_prompt + "\n\nEvaluate the candidates and return a JSON decision.",
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
        )
        
        print(f"5. ✅ Response received: {len(response.text)} characters")
        print(f"6. Response preview: {response.text[:200]}...")
        
        # Parse JSON
        print("7. Parsing JSON response...")
        data = json.loads(response.text)
        print(f"8. ✅ Valid JSON: {list(data.keys())}")
        
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")
        raise


if __name__ == "__main__":
    print("Running Gemini API tests...")
    test_gemini_api_connection()
    test_gemini_model_list()
    test_gemini_with_system_prompt()
    print("\n✅ All tests passed!")