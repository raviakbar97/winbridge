"""In-memory agent session/event store for Winbridge WebSocket goals."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def create(self, goal: str = "") -> Dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = utc_now()
        session = {
            "id": session_id,
            "goal": goal or "",
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "events": [],
        }
        with self._lock:
            self._sessions[session_id] = session
        return self.get(session_id)

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return {
                **{k: v for k, v in session.items() if k != "events"},
                "events": [dict(event) for event in session["events"]],
            }

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            sessions = []
            for session in self._sessions.values():
                sessions.append({
                    "id": session["id"],
                    "goal": session["goal"],
                    "status": session["status"],
                    "created_at": session["created_at"],
                    "updated_at": session["updated_at"],
                    "event_count": len(session["events"]),
                })
            return sorted(sessions, key=lambda s: s["created_at"], reverse=True)

    def record(self, session_id: str, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex,
            "timestamp": utc_now(),
            "type": event_type,
            "data": data,
        }
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"session not found: {session_id}")
            session["events"].append(event)
            session["updated_at"] = event["timestamp"]
        return dict(event)

    def finish(self, session_id: str, status: str = "done") -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"session not found: {session_id}")
            session["status"] = status
            session["updated_at"] = utc_now()
        return self.get(session_id)
