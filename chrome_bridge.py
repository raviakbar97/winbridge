"""In-memory Chrome extension bridge state and command queue."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


class ChromeBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {"connected": False, "updated_at": None, "elements": []}
        self._commands: Dict[str, Dict[str, Any]] = {}
        self._pending: List[str] = []

    def update_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = utc_now()
        state = dict(payload or {})
        state["connected"] = True
        state["updated_at"] = now
        state.setdefault("elements", [])
        with self._lock:
            self._state = state
        return self.get_state()

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def enqueue(self, action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not action:
            raise ValueError("action is required")
        command_id = uuid.uuid4().hex
        command = {
            "id": command_id,
            "action": action,
            "args": args or {},
            "status": "pending",
            "created_at": utc_now(),
            "sent_at": None,
            "completed_at": None,
            "result": None,
        }
        with self._lock:
            self._commands[command_id] = command
            self._pending.append(command_id)
        return dict(command)

    def poll_commands(self, limit: int = 20) -> List[Dict[str, Any]]:
        now = utc_now()
        with self._lock:
            ids = self._pending[:limit]
            self._pending = self._pending[limit:]
            commands = []
            for command_id in ids:
                cmd = self._commands[command_id]
                cmd["status"] = "sent"
                cmd["sent_at"] = now
                commands.append(dict(cmd))
            return commands

    def record_result(self, command_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            cmd = self._commands.get(command_id)
            if cmd is None:
                raise KeyError(f"command not found: {command_id}")
            cmd["status"] = "done" if result.get("ok", True) else "failed"
            cmd["completed_at"] = utc_now()
            cmd["result"] = dict(result)
            return dict(cmd)

    def get_command(self, command_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cmd = self._commands.get(command_id)
            return dict(cmd) if cmd else None
