import asyncio

import db
import worker


def _candidate():
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


def test_concurrent_ticks_produce_single_post(tmp_db_path, monkeypatch):
    db.init_db(tmp_db_path)
    db.insert_agent("a1", "AI", "example.com", "t", tmp_db_path)

    async def fake_discover():
        return _candidate()

    monkeypatch.setattr("worker.discovery.discover", fake_discover)

    async def run_twice():
        first = await worker.run_worker_tick("a1")
        second = await worker.run_worker_tick("a1")
        return first, second

    first, second = asyncio.run(run_twice())
    assert first is True
    assert second is False
