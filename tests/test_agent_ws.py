from pathlib import Path

import pytest

from agent_ws import dispatch_ws_message, make_error, validate_path


def test_ping_returns_pong():
    response = dispatch_ws_message({"id": "1", "type": "ping"}, actions={})
    assert response == {"id": "1", "type": "pong", "ok": True}


def test_unknown_message_type_returns_error():
    response = dispatch_ws_message({"id": "2", "type": "weird"}, actions={})
    assert response["id"] == "2"
    assert response["type"] == "error"
    assert response["ok"] is False
    assert "unsupported message type" in response["error"]


def test_observe_calls_observe_action():
    response = dispatch_ws_message(
        {"id": "3", "type": "observe"},
        actions={"observe": lambda args: {"focused_window": {"title": "Demo"}}},
    )
    assert response == {
        "id": "3",
        "type": "state",
        "ok": True,
        "data": {"focused_window": {"title": "Demo"}},
    }


def test_action_dispatches_named_action():
    response = dispatch_ws_message(
        {"id": "4", "type": "action", "action": "path_exists", "args": {"path": "E:/Demo"}},
        actions={"path_exists": lambda args: {"exists": True, "path": args["path"]}},
    )
    assert response == {
        "id": "4",
        "type": "result",
        "ok": True,
        "action": "path_exists",
        "data": {"exists": True, "path": "E:/Demo"},
    }


def test_missing_action_name_returns_error():
    response = dispatch_ws_message({"id": "5", "type": "action", "args": {}}, actions={})
    assert response["type"] == "error"
    assert "action is required" in response["error"]


def test_unknown_action_returns_error():
    response = dispatch_ws_message({"id": "6", "type": "action", "action": "format_drive"}, actions={})
    assert response["type"] == "error"
    assert "unsupported action" in response["error"]


def test_validate_path_rejects_empty_path():
    with pytest.raises(ValueError, match="path is required"):
        validate_path("")


def test_make_error_preserves_id():
    assert make_error("abc", "boom") == {"id": "abc", "type": "error", "ok": False, "error": "boom"}
