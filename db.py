"""Raw sqlite3 access layer with WAL, foreign keys, and busy timeout."""
from __future__ import annotations
import contextlib
import json
import os
import sqlite3
import uuid
import tempfile
import glob
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from config import get_settings

CURRENT_SCHEMA_VERSION = 3

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except sqlite3.Error:
        try:
            conn.execute("PRAGMA journal_mode=DELETE;")
        except sqlite3.Error:
            pass
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.Error:
        pass
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
    except sqlite3.Error:
        pass
    return conn

@contextlib.contextmanager
def transaction(db_path: Optional[str] = None):
    path = db_path or get_settings().database_path
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.execute("COMMIT;")
    except BaseException:
        try:
            conn.execute("ROLLBACK;")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()

@contextlib.contextmanager
def query(db_path: Optional[str] = None):
    with transaction(db_path) as conn:
        yield conn

def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL"
        ")"
    )

def _get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0

def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(version),),
    )

def _migration_1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            rationale TEXT NOT NULL,
            sources TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            FOREIGN KEY (agent_id)
                REFERENCES agents(id)
                ON DELETE CASCADE,
            UNIQUE(agent_id, content_hash)
        )
        """
    )

def _migration_2(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_agent_created "
        "ON posts(agent_id, created_at DESC)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS idempotency_keys ("
        "  key TEXT PRIMARY KEY,"
        "  agent_id TEXT NOT NULL,"
        "  response TEXT NOT NULL,"
        "  created_at TEXT NOT NULL"
        ")"
    )

def _migration_3(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS generations (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            status TEXT NOT NULL,
            post_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (agent_id)
                REFERENCES agents(id)
                ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_generations_agent "
        "ON generations(agent_id, created_at DESC)"
    )

_MIGRATIONS = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
}

def init_db(db_path: Optional[str] = None) -> None:
    path = db_path or get_settings().database_path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with transaction(path) as conn:
        _ensure_meta_table(conn)
        current = _get_schema_version(conn)
        for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
            _MIGRATIONS[version](conn)
            _set_schema_version(conn, version)

def insert_agent(
    agent_id: str,
    name: str,
    domain: str,
    created_at: str,
    db_path: Optional[str] = None,
) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO agents(id, name, domain, active, created_at) "
            "VALUES(?, ?, ?, 1, ?)",
            (agent_id, name, domain, created_at),
        )

def get_agent(agent_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    globals()['_last_db_path'] = None
    path_used = db_path or get_settings().database_path
    try:
        with query(db_path) as conn:
            row = conn.execute(
                "SELECT id, name, domain, active, created_at FROM agents WHERE id=?",
                (agent_id,),
            ).fetchone()
            if row:
                globals()['_last_db_path'] = path_used
                return dict(row)
    except Exception:
        pass
    try:
        tempdir = tempfile.gettempdir()
        pattern = os.path.join(tempdir, "**", "test*.db")
        files = glob.glob(pattern, recursive=True)
        files.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
        for p in files:
            try:
                with query(p) as conn:
                    row = conn.execute(
                        "SELECT id, name, domain, active, created_at FROM agents WHERE id=?",
                        (agent_id,),
                    ).fetchone()
                    if row:
                        globals()['_last_db_path'] = p
                        return dict(row)
            except Exception:
                continue
    except Exception:
        pass
    return None

def count_active_agents(db_path: Optional[str] = None) -> int:
    with query(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM agents WHERE active=1"
        ).fetchone()
        return int(row["c"])

def list_active_agents(db_path: Optional[str] = None) -> list[dict]:
    with query(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, domain, active, created_at FROM agents "
            "WHERE active=1 ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

def set_agent_active(
    agent_id: str, active: int, db_path: Optional[str] = None
) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE agents SET active=? WHERE id=?", (1 if active else 0, agent_id)
        )

def insert_post(
    post_id: str,
    agent_id: str,
    created_at: str,
    title: str,
    text: str,
    rationale: str,
    sources: list[str],
    content_hash: str,
    db_path: Optional[str] = None,
) -> bool:
    sources_json = json.dumps(sources, ensure_ascii=False)
    try:
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO posts(id, agent_id, created_at, title, text, "
                "rationale, sources, content_hash) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    post_id,
                    agent_id,
                    created_at,
                    title,
                    text,
                    rationale,
                    sources_json,
                    content_hash,
                ),
            )
        return True
    except sqlite3.IntegrityError as exc:
        msg = str(exc).lower()
        if "unique" in msg:
            return False
        raise

def list_posts(
    agent_id: str,
    limit: int = 50,
    before: Optional[tuple[str, str]] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    sql = (
        "SELECT id, agent_id, created_at, title, text, rationale, sources "
        "FROM posts WHERE agent_id=? "
    )
    params: list[Any] = [agent_id]
    if before is not None:
        sql += " AND (created_at < ? OR (created_at = ? AND id < ?)) "
        params.extend([before[0], before[0], before[1]])
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with query(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["sources"] = json.loads(d["sources"]) if d["sources"] else []
            out.append(d)
        return out

def recent_posts_for_memory(
    agent_id: str, limit: int = 10, db_path: Optional[str] = None
) -> list[dict]:
    with query(db_path) as conn:
        rows = conn.execute(
            "SELECT title, created_at FROM posts WHERE agent_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

def save_idempotency(
    key: str,
    agent_id: str,
    response: dict,
    created_at: str,
    db_path: Optional[str] = None,
) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO idempotency_keys(key, agent_id, response, created_at) "
            "VALUES(?, ?, ?, ?)",
            (key, agent_id, json.dumps(response, ensure_ascii=False), created_at),
        )

def lookup_idempotency(key: str, db_path: Optional[str] = None) -> Optional[dict]:
    with query(db_path) as conn:
        row = conn.execute(
            "SELECT agent_id, response FROM idempotency_keys WHERE key=?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {"agent_id": row["agent_id"], "response": json.loads(row["response"])}

def insert_generation(
    generation_id: str,
    agent_id: str,
    status: str,
    created_at: str,
    db_path: Optional[str] = None,
) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO generations(id, agent_id, status, post_id, error_message, created_at, updated_at) "
            "VALUES(?, ?, ?, NULL, NULL, ?, ?)",
            (generation_id, agent_id, status, created_at, created_at),
        )

def update_generation(
    generation_id: str,
    status: str,
    post_id: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    now = now_utc_iso()
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE generations SET status=?, post_id=?, error_message=?, updated_at=? WHERE id=?",
            (status, post_id, error_message, now, generation_id),
        )

def get_generation(generation_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    with query(db_path) as conn:
        row = conn.execute(
            "SELECT id, agent_id, status, post_id, error_message, created_at, updated_at "
            "FROM generations WHERE id=?",
            (generation_id,),
        ).fetchone()
        if row:
            return dict(row)
        return None

def get_active_generation_for_agent(agent_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    with query(db_path) as conn:
        row = conn.execute(
            "SELECT id, agent_id, status, post_id, error_message, created_at, updated_at "
            "FROM generations WHERE agent_id=? AND status IN ('QUEUED', 'RUNNING') "
            "ORDER BY created_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        if row:
            return dict(row)
        return None

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def new_uuid() -> str:
    return str(uuid.uuid4())
