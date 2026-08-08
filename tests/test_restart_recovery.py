import db


def test_active_agents_restored_after_restart(tmp_db_path):
    db.init_db(tmp_db_path)
    db.insert_agent("a1", "AI", "example.com", "t1", tmp_db_path)
    db.insert_post("p1", "a1", "t2", "Title", "Body", "https://x/y", ["https://x/y"], "hash1", tmp_db_path)

    db.init_db(tmp_db_path)
    agents = db.list_active_agents(tmp_db_path)
    assert len(agents) == 1
    assert agents[0]["id"] == "a1"
