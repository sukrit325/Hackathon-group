"""SQLite access layer with schema versioning and migrations."""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from config import get_settings

CURRENT_SCHEMA_VERSION = 2


def _connect(db_path: str) -> sqlite3.Connection:
    path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@contextlib.contextmanager
def query(db_path: Optional[str] = None):
    path = db_path or get_settings().database_path
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    path = db_path or get_settings().database_path
    with query(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                domain TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_urls TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(agent_id, content_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(CURRENT_SCHEMA_VERSION),),
        )


def get_agent(agent_id: str, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    with query(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, domain, created_at, is_active FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else None


def insert_agent(
    agent_id: str,
    name: str,
    domain: str,
    created_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    init_db(db_path)
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    with query(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO agents (id, name, domain, created_at, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (agent_id, name, domain, created_at),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def insert_post(
    post_id: str,
    agent_id: str,
    created_at: str,
    title: str,
    body: str,
    source_url: str,
    source_urls: Iterable[str],
    content_hash: str,
    db_path: Optional[str] = None,
) -> bool:
    init_db(db_path)
    payload = json.dumps(list(source_urls))
    with query(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO posts (
                    id, agent_id, title, body, source_url, source_urls, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (post_id, agent_id, title, body, source_url, payload, content_hash, created_at),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def list_posts(agent_id: str, limit: int = 50, db_path: Optional[str] = None) -> list[dict[str, Any]]:
    with query(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, agent_id, title, body, source_url, source_urls, content_hash, created_at
            FROM posts
            WHERE agent_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (agent_id, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "title": row["title"],
                "body": row["body"],
                "source_url": row["source_url"],
                "source_urls": json.loads(row["source_urls"]),
                "content_hash": row["content_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def list_active_agents(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    with query(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, domain, created_at, is_active FROM agents WHERE is_active = 1"
        ).fetchall()
        return [dict(row) for row in rows]


def count_active_agents(db_path: Optional[str] = None) -> int:
    with query(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM agents WHERE is_active = 1").fetchone()
        return int(row["count"])


def delete_agent(agent_id: str, db_path: Optional[str] = None) -> None:
    with query(db_path) as conn:
        conn.execute("UPDATE agents SET is_active = 0 WHERE id = ?", (agent_id,))


def insert_idempotency_key(key: str, agent_id: str, db_path: Optional[str] = None) -> bool:
    init_db(db_path)
    with query(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO idempotency_keys(key, agent_id, created_at) VALUES (?, ?, ?)",
                (key, agent_id, datetime.now(timezone.utc).isoformat()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def has_idempotency_key(key: str, db_path: Optional[str] = None) -> bool:
    with query(db_path) as conn:
        row = conn.execute("SELECT 1 FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
        return row is not None


def get_idempotency_agent(key: str, db_path: Optional[str] = None) -> Optional[str]:
    with query(db_path) as conn:
        row = conn.execute("SELECT agent_id FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
        return row["agent_id"] if row else None
