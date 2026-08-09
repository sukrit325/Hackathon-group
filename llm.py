"""Lightweight LLM provider compatibility shim used by tests.
This module provides a MockProvider class so tests that reference `llm.MockProvider`
can import it. The real project may use a different LLM provider; this file is a
minimal placeholder to satisfy tests.
"""

class MockProvider:
    """A no-op mock provider used only for test-time monkeypatching."""
    def __init__(self, *args, **kwargs):
        pass

    def generate(self, *args, **kwargs):
        return {}

    async def generate_async(self, *args, **kwargs):
        return {}
