from agent_session import SessionStore


def test_create_session_has_goal_and_empty_events():
    store = SessionStore()
    session = store.create(goal="buat folder di E")
    assert session["id"]
    assert session["goal"] == "buat folder di E"
    assert session["status"] == "running"
    assert session["events"] == []


def test_record_event_appends_to_session():
    store = SessionStore()
    session = store.create(goal="test")
    event = store.record(session["id"], "action", {"name": "mkdir"})
    loaded = store.get(session["id"])
    assert event["type"] == "action"
    assert loaded["events"] == [event]


def test_list_sessions_omits_event_details():
    store = SessionStore()
    session = store.create(goal="test")
    store.record(session["id"], "result", {"ok": True})
    sessions = store.list()
    assert sessions[0]["id"] == session["id"]
    assert sessions[0]["event_count"] == 1
    assert "events" not in sessions[0]


def test_finish_session_sets_status():
    store = SessionStore()
    session = store.create(goal="test")
    store.finish(session["id"], status="done")
    assert store.get(session["id"])["status"] == "done"
