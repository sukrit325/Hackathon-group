from fastapi.testclient import TestClient

import db
from main import app


def _init_db(tmp_db_path, monkeypatch):
    db.init_db(tmp_db_path)
    monkeypatch.setattr(db.get_settings(), "database_path", tmp_db_path)


def test_init_agent_valid(tmp_db_path, monkeypatch):
    _init_db(tmp_db_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/agent/init",
            json={"persona": {"name": "AI", "domain": "example.com"}},
        )
        assert response.status_code == 200, response.text
        assert "agentId" in response.json()


def test_feed_missing_agent_404(tmp_db_path, monkeypatch):
    _init_db(tmp_db_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/agent/feed?agentId=missing")
        assert response.status_code == 404
