from chrome_bridge import ChromeBridge


def test_update_and_get_state():
    bridge = ChromeBridge()
    state = bridge.update_state({"url": "https://example.com", "elements": []})
    assert state["connected"] is True
    assert state["url"] == "https://example.com"
    assert bridge.get_state()["url"] == "https://example.com"


def test_enqueue_and_poll_command():
    bridge = ChromeBridge()
    cmd = bridge.enqueue("click", {"element_id": "wb_1"})
    assert cmd["id"]
    assert cmd["action"] == "click"
    pending = bridge.poll_commands(limit=10)
    assert pending[0]["id"] == cmd["id"]
    assert pending[0]["status"] == "sent"
    assert pending[0]["sent_at"]
    assert bridge.poll_commands(limit=10) == []


def test_record_result_updates_command():
    bridge = ChromeBridge()
    cmd = bridge.enqueue("type", {"element_id": "wb_2", "text": "hello"})
    bridge.poll_commands()
    result = bridge.record_result(cmd["id"], {"ok": True})
    assert result["status"] == "done"
    assert result["result"] == {"ok": True}


def test_unknown_result_raises_key_error():
    bridge = ChromeBridge()
    try:
        bridge.record_result("missing", {"ok": False})
    except KeyError as exc:
        assert "command not found" in str(exc)
    else:
        raise AssertionError("expected KeyError")
