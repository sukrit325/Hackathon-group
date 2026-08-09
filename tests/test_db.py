import db


def test_schema_initialized(tmp_db_path):
    db.init_db(tmp_db_path)
    with db.query(tmp_db_path) as conn:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        assert int(row["value"]) == db.CURRENT_SCHEMA_VERSION


def test_insert_and_retrieve_post(tmp_db_path):
    db.init_db(tmp_db_path)
    db.insert_agent("a1", "AI", "example.com", "2024-01-01T00:00:00Z", tmp_db_path)
    inserted = db.insert_post(
        "p1",
        "a1",
        "2024-01-01T00:00:01Z",
        "Title",
        "Body",
        "https://x/y",
        ["https://x/y"],
        "hash1",
        tmp_db_path,
    )
    assert inserted is True
    posts = db.list_posts("a1", db_path=tmp_db_path)
    assert len(posts) == 1
