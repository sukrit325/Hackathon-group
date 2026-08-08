import asyncio

import db
import llm
import worker


def _setup_agent(tmp_db_path):
    db.init_db(tmp_db_path)
    db.insert_agent("a1", "AI", "example.com", "2024-01-01T00:00:00Z", tmp_db_path)
    return "a1"


def test_successful_publish(tmp_db_path, monkeypatch):
    agent_id = _setup_agent(tmp_db_path)

    async def fake_discover():
        return [
            type(
                "C",
                (),
                {
                    "to_dict": lambda self: {
                        "title": "T",
                        "summary": "S",
                        "source_url": "https://x/y",
                        "published_at": "2024-01-01T00:00:00Z",
                        "source_name": "x",
                    }
                },
            )()
        ]

    monkeypatch.setattr("worker.discovery.discover", fake_discover)
    monkeypatch.setattr("worker.llm.MockProvider", llm.MockProvider)

    inserted = asyncio.run(worker.run_worker_tick(agent_id))
    assert inserted is True
