"""WebSocket message dispatch helpers for Winbridge agent sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Mapping

ActionMap = Mapping[str, Callable[[dict], Any]]


def make_error(message_id: Any, error: str) -> dict:
    return {"id": message_id, "type": "error", "ok": False, "error": error}


def validate_path(path: str) -> Path:
    if not path or not str(path).strip():
        raise ValueError("path is required")
    return Path(path)


def dispatch_ws_message(message: dict, actions: ActionMap) -> dict:
    """Dispatch one inbound WebSocket JSON message.

    Supported messages:
    - {id, type: "ping"}
    - {id, type: "observe"}
    - {id, type: "action", action: "...", args: {...}}
    """
    message_id = message.get("id")
    message_type = message.get("type")
    try:
        if message_type == "ping":
            return {"id": message_id, "type": "pong", "ok": True}

        if message_type == "observe":
            observe = actions.get("observe")
            if observe is None:
                return make_error(message_id, "observe action is not registered")
            return {"id": message_id, "type": "state", "ok": True, "data": observe({})}

        if message_type == "action":
            action_name = message.get("action")
            if not action_name:
                return make_error(message_id, "action is required")
            action = actions.get(action_name)
            if action is None:
                return make_error(message_id, f"unsupported action: {action_name}")
            args = message.get("args") or {}
            if not isinstance(args, dict):
                return make_error(message_id, "args must be an object")
            return {
                "id": message_id,
                "type": "result",
                "ok": True,
                "action": action_name,
                "data": action(args),
            }

        return make_error(message_id, f"unsupported message type: {message_type}")
    except Exception as exc:
        return make_error(message_id, str(exc))
