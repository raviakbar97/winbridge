"""
Windows Automation Bridge
REST API server for remote AI agents to control Windows (focused window, open apps, typing).
"""

import os
import sys
import json
import time
import logging
import subprocess
import traceback
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import flask
from flask import Flask, request, jsonify
from flask_sock import Sock
import psutil
import ctypes
from ctypes import wintypes
import win32api
import win32con
import win32gui
import win32process

from updater import STATUS_FILE, safe_extract_zip
from agent_ws import dispatch_ws_message, validate_path
from agent_session import SessionStore
from chrome_bridge import ChromeBridge
from audio_control import volume_get, volume_set, volume_mute, volume_toggle_mute

try:
    import uiautomation as auto
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

try:
    import win32com.client
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False

try:
    from comtypes import CoInitialize, CoUninitialize
    HAS_COM = True
except ImportError:
    HAS_COM = False

_uia_lock = threading.Lock()

logger = logging.getLogger("winbridge")


class _UIAContext:
    """Context manager for thread-safe uiautomation usage with COM init."""
    def __enter__(self):
        if not HAS_UIA:
            raise RuntimeError("uiautomation not installed")
        if HAS_COM:
            CoInitialize()
        return auto

    def __exit__(self, *exc):
        if HAS_COM:
            CoUninitialize()
        return False

use_uia = _UIAContext()

HOST = "0.0.0.0"
PORT = 5100
APP_DIR = Path(__file__).resolve().parent
STARTED_AT = datetime.utcnow().isoformat(timespec="seconds") + "Z"
ADMIN_TOKEN = os.environ.get("WINBRIDGE_ADMIN_TOKEN", "")

# ---- ctypes wrappers for focus-stealing workaround ----
user32 = ctypes.windll.user32

SwitchToThisWindow = user32.SwitchToThisWindow
SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]

SetWindowPos = user32.SetWindowPos
SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                         ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_int,
                         ctypes.c_uint]

AttachThreadInput = user32.AttachThreadInput
AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

keybd_event = user32.keybd_event
keybd_event.argtypes = [ctypes.c_byte, ctypes.c_byte, ctypes.c_uint, ctypes.c_uint]


# ---- window helpers ----
def window_title(hwnd: int) -> str:
    try:
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


def window_class(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd) or ""
    except Exception:
        return ""


def window_state(hwnd: int) -> str:
    try:
        p = win32gui.GetWindowPlacement(hwnd)
        if p[1] == win32con.SW_SHOWMINIMIZED:
            return "minimized"
        if p[1] == win32con.SW_SHOWMAXIMIZED:
            return "maximized"
        return "normal"
    except Exception:
        return "unknown"


def process_of(hwnd: int):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name(), pid
    except Exception:
        return "unknown", 0


def is_gui_window(hwnd: int) -> bool:
    if not win32gui.IsWindowVisible(hwnd):
        return False
    cls = window_class(hwnd)
    if cls in (
        "Progman", "WorkerW", "SysListView32",
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
        "NotifyIconOverflowWindow",
    ):
        return False
    title = window_title(hwnd)
    if not title:
        return False
    return True


def can_type(hwnd: int) -> bool:
    if HAS_UIA:
        try:
            with use_uia as uia:
                ctrl = uia.ControlFromHandle(hwnd)
                if ctrl:
                    fc = ctrl.GetFriendlyControl()
                    if fc:
                        ct = fc.ControlTypeName
                        for prefix in ("Edit", "Document", "Combo", "RichEdit", "TextBox"):
                            if ct.startswith(prefix):
                                return True
        except Exception:
            pass
    cls = window_class(hwnd)
    for k in (
        "Edit", "RichEdit", "RICHEDIT", "RICHEDIT50W",
        "TextBox", "Windows.UI.Core.CoreWindow",
        "MSEditor", "Chrome_RenderWidgetHostHWND",
    ):
        if k in cls:
            return True
    return False


# ---- window enumeration ----
def enum_windows() -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    def cb(hwnd, _):
        try:
            if not is_gui_window(hwnd):
                return True
            name, pid = process_of(hwnd)
            result.append(dict(
                pid=pid, name=name,
                title=window_title(hwnd),
                state=window_state(hwnd),
            ))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return result


# ---- actions ----
def action_open(target: str, cwd: Optional[str] = None,
                args: Optional[List[str]] = None) -> Dict[str, Any]:
    cmd = [target]
    if args:
        if isinstance(args, str):
            cmd.append(args)
        else:
            cmd.extend(args)
    subprocess.Popen(cmd, cwd=cwd, shell=False)
    logger.info("Launched %s", target)
    return {"status": "launched", "target": target}


def action_focus(pid: Optional[int] = None,
                 title: Optional[str] = None) -> Dict[str, Any]:
    hwnd = None

    if pid is not None:
        def by_pid(h, _):
            nonlocal hwnd
            if hwnd is not None:
                return False
            try:
                if is_gui_window(h):
                    _, p = win32process.GetWindowThreadProcessId(h)
                    if p == pid:
                        hwnd = h
                        return False
            except Exception:
                pass
            return True
        win32gui.EnumWindows(by_pid, None)

    if title and hwnd is None:
        t = title.lower()
        def by_title(h, _):
            nonlocal hwnd
            if hwnd is not None:
                return False
            try:
                if is_gui_window(h) and t in window_title(h).lower():
                    hwnd = h
                    return False
            except Exception:
                pass
            return True
        win32gui.EnumWindows(by_title, None)

    if hwnd is None:
        raise ValueError(f"Window not found (pid={pid}, title={title})")

    # ---- focus-stealing workaround ----
    if window_state(hwnd) == "minimized":
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    tid = win32api.GetCurrentThreadId()
    target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
    attached = False
    if tid != target_tid:
        AttachThreadInput(target_tid, tid, True)
        attached = True

    try:
        SwitchToThisWindow(hwnd, True)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        # Toggle topmost to force z-order to front
        SetWindowPos(hwnd, -1, 0, 0, 0, 0, 1 | 2)
        SetWindowPos(hwnd, -2, 0, 0, 0, 0, 1 | 2)
    finally:
        if attached:
            AttachThreadInput(target_tid, tid, False)

    time.sleep(0.15)
    logger.info("Focused hwnd=%s title=%s", hwnd, window_title(hwnd))
    return {"status": "focused"}


def action_type(text: str, enter: bool = True):
    if HAS_UIA:
        try:
            with use_uia as uia:
                uia.SetClipboardText(text)
                time.sleep(0.05)
                uia.SendKeys("{Ctrl}v", waitTime=0.1)
                time.sleep(0.05)
                if enter:
                    uia.SendKeys("{Enter}", waitTime=0.3)
                logger.info("Typed %d chars via paste", len(text))
                return
        except Exception:
            logger.warning("Paste method failed", exc_info=True)

        try:
            with use_uia as uia:
                safe = (text.replace("{", "{{}")
                            .replace("}", "{}}")
                            .replace("+", "{+}")
                            .replace("^", "{^}")
                            .replace("%", "{%}")
                            .replace("~", "{~}")
                            .replace("(", "{(}").replace(")", "{)}"))
                uia.SendKeys(safe, waitTime=0.05)
                if enter:
                    uia.SendKeys("{Enter}", waitTime=0.3)
                logger.info("Typed %d chars via SendKeys", len(text))
                return
        except Exception as e:
            raise RuntimeError("uiautomation SendKeys also failed") from e

    if HAS_WIN32COM:
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.AppActivate(win32gui.GetForegroundWindow())
            time.sleep(0.1)
            shell.SendKeys(text)
            if enter:
                shell.SendKeys("{ENTER}")
            logger.info("Typed %d chars via WScript.Shell", len(text))
            return
        except Exception as e:
            raise RuntimeError("All typing methods failed") from e

    raise RuntimeError("No typing backend available — install uiautomation")


# ---- admin / self-update helpers ----
def require_admin_token():
    """Protect code-update endpoints when WINBRIDGE_ADMIN_TOKEN is configured."""
    if not ADMIN_TOKEN:
        return None
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {ADMIN_TOKEN}"
    if auth != expected:
        return jsonify(error="unauthorized"), 401
    return None


def update_status() -> Dict[str, Any]:
    path = APP_DIR / STATUS_FILE
    if not path.exists():
        return {"status": "never"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


def _exit_soon():
    def shutdown_soon():
        time.sleep(0.25)
        os._exit(0)

    threading.Thread(target=shutdown_soon, daemon=True).start()


def spawn_update_restart(staging_dir: Path):
    """Spawn updater.py to apply staged files, then stop this server process."""
    args = [
        sys.executable,
        str(APP_DIR / "updater.py"),
        "--app-dir", str(APP_DIR),
        "--staging-dir", str(staging_dir),
        "--old-pid", str(os.getpid()),
    ]
    subprocess.Popen(args, cwd=str(APP_DIR), close_fds=True)
    _exit_soon()


def spawn_plain_restart():
    """Start a fresh server.py process, then stop this server process."""
    subprocess.Popen([sys.executable, str(APP_DIR / "server.py")], cwd=str(APP_DIR), close_fds=True)
    _exit_soon()


def make_update_bundle_staging(upload) -> Path:
    payload = upload.read()
    if not payload:
        raise ValueError("empty update bundle")
    staging_dir = APP_DIR / ".winbridge-update-staging" / uuid.uuid4().hex
    safe_extract_zip(payload, staging_dir)
    return staging_dir


# ---- WebSocket action helpers ----
def get_screen_state_data() -> Dict[str, Any]:
    hwnd = win32gui.GetForegroundWindow()
    name, pid = process_of(hwnd)
    title = window_title(hwnd)
    state = window_state(hwnd)
    typing = can_type(hwnd)
    windows = enum_windows()
    return dict(
        focused_window=dict(
            pid=pid, name=name, title=title,
            state=state, ready_for_typing=typing,
        ),
        visible_windows=windows,
        count=len(windows),
    )


def ws_action_open(args: dict) -> Dict[str, Any]:
    target = args.get("target")
    if not target:
        raise ValueError("target is required")
    return action_open(target=target, cwd=args.get("working_dir"), args=args.get("args"))


def ws_action_focus(args: dict) -> Dict[str, Any]:
    return action_focus(pid=args.get("pid"), title=args.get("title"))


def ws_action_type(args: dict) -> Dict[str, Any]:
    text = args.get("text")
    if text is None:
        raise ValueError("text is required")
    action_type(text=str(text), enter=bool(args.get("enter", False)))
    return {"status": "ok", "chars": len(str(text)), "enter": bool(args.get("enter", False))}


def ws_action_mkdir(args: dict) -> Dict[str, Any]:
    path = validate_path(args.get("path", ""))
    path.mkdir(parents=bool(args.get("parents", True)), exist_ok=bool(args.get("exist_ok", True)))
    return {"status": "created", "path": str(path), "exists": path.exists()}


def ws_action_path_exists(args: dict) -> Dict[str, Any]:
    path = validate_path(args.get("path", ""))
    return {"path": str(path), "exists": path.exists(), "is_dir": path.is_dir(), "is_file": path.is_file()}


def ws_action_list_dir(args: dict) -> Dict[str, Any]:
    path = validate_path(args.get("path", ""))
    if not path.exists():
        raise ValueError(f"path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"path is not a directory: {path}")
    limit = int(args.get("limit", 100))
    entries = []
    for child in list(path.iterdir())[:limit]:
        entries.append({"name": child.name, "path": str(child), "is_dir": child.is_dir(), "is_file": child.is_file()})
    return {"path": str(path), "count": len(entries), "entries": entries}


def ws_action_minimize_all(args: dict) -> Dict[str, Any]:
    if not HAS_WIN32COM:
        raise RuntimeError("minimize_all requires win32com")
    if HAS_COM:
        CoInitialize()
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        shell.MinimizeAll()
        time.sleep(0.3)
        windows = enum_windows()
        minimized = [w for w in windows if w.get("state") == "minimized"]
        return {"status": "ok", "minimized_count": len(minimized), "window_count": len(windows)}
    finally:
        if HAS_COM:
            CoUninitialize()


def ws_action_volume_get(args: dict) -> Dict[str, Any]:
    return volume_get()


def ws_action_volume_set(args: dict) -> Dict[str, Any]:
    if "level" not in args:
        raise ValueError("level is required")
    return volume_set(args.get("level"))


def ws_action_volume_mute(args: dict) -> Dict[str, Any]:
    return volume_mute(True)


def ws_action_volume_unmute(args: dict) -> Dict[str, Any]:
    return volume_mute(False)


def ws_action_volume_toggle_mute(args: dict) -> Dict[str, Any]:
    return volume_toggle_mute()


def ws_action_chrome_state(args: dict) -> Dict[str, Any]:
    return CHROME.get_state()


def ws_action_chrome_command(action: str, args: dict) -> Dict[str, Any]:
    return CHROME.enqueue(action, args)


def ws_actions() -> Dict[str, Any]:
    return {
        "observe": lambda args: get_screen_state_data(),
        "screen_state": lambda args: get_screen_state_data(),
        "open": ws_action_open,
        "focus": ws_action_focus,
        "type": ws_action_type,
        "mkdir": ws_action_mkdir,
        "path_exists": ws_action_path_exists,
        "list_dir": ws_action_list_dir,
        "minimize_all": ws_action_minimize_all,
        "volume_get": ws_action_volume_get,
        "volume_set": ws_action_volume_set,
        "volume_mute": ws_action_volume_mute,
        "volume_unmute": ws_action_volume_unmute,
        "volume_toggle_mute": ws_action_volume_toggle_mute,
        "chrome_state": ws_action_chrome_state,
        "chrome_click": lambda args: ws_action_chrome_command("click", args),
        "chrome_right_click": lambda args: ws_action_chrome_command("right_click", args),
        "chrome_type": lambda args: ws_action_chrome_command("type", args),
        "chrome_navigate": lambda args: ws_action_chrome_command("navigate", args),
        "chrome_new_tab": lambda args: ws_action_chrome_command("new_tab", args),
        "chrome_tabs": lambda args: ws_action_chrome_command("tabs", args),
        "chrome_activate_tab": lambda args: ws_action_chrome_command("activate_tab", args),
        "chrome_paragraphs": lambda args: ws_action_chrome_command("paragraphs", args),
        "chrome_article_text": lambda args: ws_action_chrome_command("article_text", args),
    }


# ---- Flask routes ----
app = Flask(__name__)
sock = Sock(app)
SESSIONS = SessionStore()
CHROME = ChromeBridge()

DOCS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AGENT.md")
_DOCS_CACHE: Optional[str] = None


@app.route("/docs")
def docs():
    global _DOCS_CACHE
    try:
        if _DOCS_CACHE is None:
            _DOCS_CACHE = open(DOCS_PATH, "r", encoding="utf-8").read()
        return _DOCS_CACHE, 200, {"Content-Type": "text/markdown; charset=utf-8"}
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/health")
def health():
    return jsonify(status="ok", service="winbridge", uia=HAS_UIA)


@app.route("/admin/version")
def admin_version():
    return jsonify(
        service="winbridge",
        started_at=STARTED_AT,
        pid=os.getpid(),
        app_dir=str(APP_DIR),
        admin_token_required=bool(ADMIN_TOKEN),
        update_status=update_status(),
    )


@app.route("/admin/update/status")
def admin_update_status():
    return jsonify(update_status())


@app.route("/admin/restart", methods=["POST"])
def admin_restart():
    unauthorized = require_admin_token()
    if unauthorized:
        return unauthorized
    spawn_plain_restart()
    return jsonify(status="restarting", pid=os.getpid())


@app.route("/admin/update", methods=["POST"])
def admin_update():
    unauthorized = require_admin_token()
    if unauthorized:
        return unauthorized
    try:
        upload = request.files.get("file")
        if upload is None:
            return jsonify(error="multipart file field 'file' is required"), 400
        staging_dir = make_update_bundle_staging(upload)
        spawn_update_restart(staging_dir)
        return jsonify(status="updating", staging_dir=str(staging_dir), pid=os.getpid())
    except Exception as e:
        logger.exception("POST /admin/update")
        return jsonify(error=str(e)), 400


@app.route("/screen/state")
def screen_state():
    try:
        return jsonify(get_screen_state_data())
    except Exception:
        logger.exception("GET /screen/state")
        return jsonify(error=traceback.format_exc()), 500


@app.route("/agent/sessions")
def agent_sessions():
    return jsonify(sessions=SESSIONS.list())


@app.route("/agent/session/<session_id>")
def agent_session(session_id):
    session = SESSIONS.get(session_id)
    if session is None:
        return jsonify(error="session not found"), 404
    return jsonify(session)


@app.route("/chrome/update", methods=["POST"])
def chrome_update():
    data = request.get_json(silent=True) or {}
    return jsonify(CHROME.update_state(data))


@app.route("/chrome/state")
def chrome_state():
    return jsonify(CHROME.get_state())


@app.route("/chrome/command", methods=["POST"])
def chrome_command():
    data = request.get_json(silent=True) or {}
    try:
        action = data.get("action")
        args = data.get("args") or {}
        return jsonify(CHROME.enqueue(action, args))
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route("/chrome/commands")
def chrome_commands():
    limit = int(request.args.get("limit", 20))
    return jsonify(commands=CHROME.poll_commands(limit=limit))


@app.route("/chrome/command/result", methods=["POST"])
def chrome_command_result():
    data = request.get_json(silent=True) or {}
    command_id = data.get("id")
    try:
        return jsonify(CHROME.record_result(command_id, data))
    except KeyError as e:
        return jsonify(error=str(e)), 404
    except Exception as e:
        return jsonify(error=str(e)), 400


@sock.route("/agent/ws")
def agent_ws(ws):
    logger.info("WebSocket client connected: /agent/ws")
    actions = ws_actions()
    current_session_id = None
    while True:
        raw = ws.receive()
        if raw is None:
            logger.info("WebSocket client disconnected: /agent/ws")
            break
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                response = {"id": None, "type": "error", "ok": False, "error": "message must be a JSON object"}
            elif message.get("type") == "start_session":
                session = SESSIONS.create(goal=message.get("goal", ""))
                current_session_id = session["id"]
                response = {"id": message.get("id"), "type": "session", "ok": True, "session": session}
            elif message.get("type") == "finish_session":
                session_id = message.get("session_id") or current_session_id
                if not session_id:
                    response = {"id": message.get("id"), "type": "error", "ok": False, "error": "session_id is required"}
                else:
                    session = SESSIONS.finish(session_id, status=message.get("status", "done"))
                    response = {"id": message.get("id"), "type": "session", "ok": True, "session": session}
            else:
                session_id = message.get("session_id") or current_session_id
                if session_id:
                    SESSIONS.record(session_id, "message", {"message": message})
                response = dispatch_ws_message(message, actions)
                if session_id:
                    SESSIONS.record(session_id, "response", {"response": response})
        except Exception as e:
            response = {"id": None, "type": "error", "ok": False, "error": str(e)}
        ws.send(json.dumps(response, ensure_ascii=False))


@app.route("/action/open", methods=["POST"])
def open_():
    try:
        data = request.get_json(silent=True)
        if not data or "target" not in data:
            return jsonify(error='Required: {"target": "..."}'), 400
        return jsonify(action_open(
            target=data["target"],
            cwd=data.get("working_dir"),
            args=data.get("args"),
        ))
    except Exception as e:
        logger.exception("POST /action/open")
        return jsonify(error=str(e)), 500


@app.route("/action/focus", methods=["POST"])
def focus_():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify(error='Required: {"pid":N} or {"title":"..."}'), 400
        return jsonify(action_focus(pid=data.get("pid"), title=data.get("title")))
    except Exception as e:
        logger.exception("POST /action/focus")
        return jsonify(error=str(e)), 500


@app.route("/action/type", methods=["POST"])
def type_():
    try:
        data = request.get_json(silent=True)
        if not data or "text" not in data:
            return jsonify(error='Required: {"text": "..."}'), 400
        action_type(text=data["text"], enter=data.get("enter", True))
        return jsonify(status="ok", chars=len(data["text"]), enter=data.get("enter", True))
    except Exception as e:
        logger.exception("POST /action/type")
        return jsonify(error=str(e)), 500


# ---- main ----
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print("=" * 54)
    print("  Windows Automation Bridge")
    print("=" * 54)
    print(f"  uiautomation:  {'YES' if HAS_UIA else 'NO — pip install uiautomation'}")
    print(f"  win32com:      {'YES' if HAS_WIN32COM else 'NO'}")
    print()
    print("  Endpoints:")
    print("    GET  /docs           Agent documentation (this file)")
    print("    GET  /health         Server status")
    print("    GET  /screen/state          Focused + visible windows")
    print("    POST /action/open           Launch app or path")
    print("    POST /action/focus          Focus window by pid|title")
    print("    POST /action/type           Type text + Enter")
    print("    GET  /admin/version         Version + update status")
    print("    GET  /admin/update/status   Last update status")
    print("    POST /admin/update          Upload ZIP, apply, restart")
    print("    POST /admin/restart         Restart server")
    print()
    print(f"  Listening on http://{HOST}:{PORT}")
    print("=" * 54)

    if not HAS_UIA:
        print()
        print("  ⚠ Install uiautomation for reliable typing:")
        print("     pip install uiautomation")
        print()

    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
