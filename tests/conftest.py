import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Make the lightweight llm module available as a global name in tests that
# reference `llm` without importing it (some tests monkeypatch llm.MockProvider).
import builtins
try:
    import llm as _llm_module
    builtins.llm = _llm_module
except Exception:
    # If llm cannot be imported, tests that depend on it will fail later with a clear error.
    pass


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
