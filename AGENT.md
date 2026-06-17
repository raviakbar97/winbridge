# Winbridge v1 — Agent Integration Guide

Winbridge is a lightweight Windows automation bridge for AI agents running on a different device in the same local network.

Typical topology:

```txt
AI Agent machine / gateway / server
  e.g. Linux box running Hermes, OpenCode, Claude Code, custom agent
        |
        | LAN HTTP + WebSocket
        v
Windows PC running Winbridge
        |
        | Windows UI APIs + Chrome extension
        v
Desktop apps, Explorer, Chrome tabs, web pages
```

This guide is written for AI agents. If you are an agent, read this entire file before controlling a user's PC.

---

## 0. Current scope and assumptions

Winbridge v1 assumes:

- The AI agent and Windows PC are on the same trusted LAN.
- Winbridge runs on the Windows PC and listens on port `5100`.
- The agent connects from another machine using the PC LAN IP.
- Chrome DOM features require the included unpacked Chrome extension to be installed.
- The server is intended for trusted local use, not public internet exposure.

Default base URL:

```txt
http://WINDOWS_PC_IP:5100
```

Example used by Ravi's setup:

```txt
http://192.168.1.100:5100
```

WebSocket endpoint:

```txt
ws://WINDOWS_PC_IP:5100/agent/ws
```

---

## 1. Quick health check

Always start by checking connectivity.

```http
GET /health
```

Expected response:

```json
{
  "status": "ok",
  "service": "winbridge",
  "uia": true
}
```

If this fails:

- Winbridge may not be running.
- Windows Firewall may block port `5100`.
- The server may be bound only to localhost.
- The PC IP may be wrong.
- The PC and agent may not be on the same network.

---

## 2. Core control model for agents

Use this model:

```txt
observe state
→ decide next action
→ execute one action
→ observe again
→ verify result
→ repeat until goal is done
```

Do not blindly chain many UI actions without observing between them.

Preferred control layers, from safest to most fragile:

1. Filesystem/task-specific actions, e.g. `mkdir`, `path_exists`, `list_dir`.
2. Chrome DOM actions through the extension, e.g. `chrome_state`, `chrome_click`, `chrome_type`.
3. Window/app actions, e.g. `open`, `focus`.
4. Generic typing into the focused window.
5. Coordinate clicks or screenshot-based control, if added in the future.

---

## 3. Screen and window state

```http
GET /screen/state
```

Returns the focused window and visible windows.

Example:

```json
{
  "focused_window": {
    "pid": 13764,
    "name": "chrome.exe",
    "title": "YouTube - Google Chrome",
    "state": "maximized",
    "ready_for_typing": false
  },
  "visible_windows": [
    {
      "pid": 13764,
      "name": "chrome.exe",
      "title": "YouTube - Google Chrome",
      "state": "maximized"
    }
  ],
  "count": 1
}
```

Important fields:

- `focused_window`: Current foreground window.
- `pid`: Process ID.
- `name`: Executable name, e.g. `chrome.exe`, `explorer.exe`.
- `title`: Window title.
- `state`: `normal`, `minimized`, or `maximized`.
- `ready_for_typing`: Whether the focused UI control appears text-ready.
- `visible_windows`: Other visible top-level windows.

---

## 4. REST app/window actions

These REST endpoints are useful for simple tooling or manual debugging. For multi-step goals, prefer the WebSocket session API in section 7.

### 4.1 Open app/path

```http
POST /action/open
Content-Type: application/json
```

Launch an executable:

```json
{"target": "notepad.exe"}
```

Open Explorer at a path:

```json
{"target": "explorer.exe", "args": ["E:\\"]}
```

Launch with working directory and args:

```json
{
  "target": "cmd.exe",
  "working_dir": "E:\\Projects",
  "args": ["/k", "dir"]
}
```

### 4.2 Focus a window

```http
POST /action/focus
Content-Type: application/json
```

By PID, preferred:

```json
{"pid": 1234}
```

By partial title:

```json
{"title": "Notepad"}
```

Winbridge uses multiple Windows focus strategies internally, including `AttachThreadInput`, `SwitchToThisWindow`, `SetForegroundWindow`, and a topmost toggle.

### 4.3 Type into focused window

```http
POST /action/type
Content-Type: application/json
```

```json
{"text": "Hello from AI agent", "enter": true}
```

Important:

- REST `/action/type` currently defaults `enter` to `true`.
- WebSocket `type` action defaults `enter` to `false`, which is safer.
- Before typing, observe/focus the correct target window.

Typing backends:

1. Clipboard paste with `Ctrl+V`.
2. UI Automation `SendKeys` fallback.
3. `WScript.Shell` COM fallback.

---

## 5. Admin and self-update

Winbridge can update its own source code from a ZIP uploaded by an agent.

### 5.1 Version/status

```http
GET /admin/version
GET /admin/update/status
```

Example:

```json
{
  "service": "winbridge",
  "started_at": "2026-06-17T14:49:33Z",
  "pid": 23728,
  "app_dir": "F:\\claudecode\\exp\\10\\window_bridge",
  "admin_token_required": false,
  "update_status": {
    "status": "success",
    "files": ["server.py", "AGENT.md"]
  }
}
```

### 5.2 Restart

```http
POST /admin/restart
```

### 5.3 Upload update ZIP

```http
POST /admin/update
Content-Type: multipart/form-data
file=@winbridge-update.zip
```

Allowed bundle paths:

```txt
server.py
updater.py
agent_ws.py
agent_session.py
chrome_bridge.py
AGENT.md
README.md
requirements.txt
chrome_extension/*
tests/*
```

Update behavior:

1. Server extracts ZIP to `.winbridge-update-staging/<id>/`.
2. Path traversal and unknown top-level files are rejected.
3. Server spawns `updater.py` and exits.
4. Updater backs up replaced files to `backups/<timestamp>/`.
5. Updater copies staged files into the app directory.
6. If `requirements.txt` is included, updater runs `python -m pip install -r requirements.txt`.
7. Updater starts a fresh `python server.py`.
8. Status is written to `.winbridge-update-status.json`.

Agent recommendation:

- After `/admin/update`, poll `/health` until it returns `ok`.
- Then check `/admin/update/status`.
- If adding a new top-level file, first update `updater.py` allowlist, then send the full update in a second bundle.

---

## 6. Realtime WebSocket agent session

Use this for actual agent work.

```txt
WS /agent/ws
```

Full URL example:

```txt
ws://192.168.1.100:5100/agent/ws
```

The WebSocket accepts one JSON message at a time and replies with one JSON message. Keep the connection open for a goal.

### 6.1 Ping

Send:

```json
{"id":"1","type":"ping"}
```

Receive:

```json
{"id":"1","type":"pong","ok":true}
```

### 6.2 Start a session/goal

Send:

```json
{
  "id": "s1",
  "type": "start_session",
  "goal": "Open Explorer and create a folder on E named AliceTest"
}
```

Receive:

```json
{
  "id": "s1",
  "type": "session",
  "ok": true,
  "session": {
    "id": "abc123...",
    "goal": "Open Explorer and create a folder on E named AliceTest",
    "status": "running",
    "events": []
  }
}
```

After `start_session`, messages on the same WebSocket are recorded automatically. You can also pass `session_id` explicitly in any message.

### 6.3 Observe

Send:

```json
{"id":"2","type":"observe"}
```

Receive:

```json
{
  "id": "2",
  "type": "state",
  "ok": true,
  "data": {
    "focused_window": {...},
    "visible_windows": [...],
    "count": 12
  }
}
```

### 6.4 Run an action

Send:

```json
{
  "id": "3",
  "type": "action",
  "action": "mkdir",
  "args": {"path": "E:\\AliceTest"}
}
```

Receive:

```json
{
  "id": "3",
  "type": "result",
  "ok": true,
  "action": "mkdir",
  "data": {
    "status": "created",
    "path": "E:\\AliceTest",
    "exists": true
  }
}
```

### 6.5 Finish a session

Send:

```json
{"id":"s2","type":"finish_session","status":"done"}
```

Receive updated session.

### 6.6 Inspect sessions over HTTP

```http
GET /agent/sessions
GET /agent/session/<session_id>
```

Sessions are in-memory for v1. They reset when Winbridge restarts.

---

## 7. WebSocket action reference

All actions use this envelope:

```json
{
  "id": "unique-message-id",
  "type": "action",
  "action": "action_name",
  "args": {}
}
```

### 7.1 `screen_state`

Same as `observe` or `GET /screen/state`.

```json
{"id":"1","type":"action","action":"screen_state","args":{}}
```

### 7.2 `open`

Open an app or path.

```json
{
  "id": "2",
  "type": "action",
  "action": "open",
  "args": {
    "target": "explorer.exe",
    "args": ["E:\\"]
  }
}
```

### 7.3 `focus`

Focus by PID or partial title.

```json
{"id":"3","type":"action","action":"focus","args":{"title":"Chrome"}}
```

### 7.4 `type`

Type text into the focused window. Safer default: `enter=false`.

```json
{
  "id": "4",
  "type": "action",
  "action": "type",
  "args": {
    "text": "hello",
    "enter": false
  }
}
```

### 7.5 `mkdir`

Create a folder.

```json
{
  "id": "5",
  "type": "action",
  "action": "mkdir",
  "args": {
    "path": "E:\\AliceTest",
    "parents": true,
    "exist_ok": true
  }
}
```

### 7.6 `path_exists`

Verify a file/folder exists.

```json
{"id":"6","type":"action","action":"path_exists","args":{"path":"E:\\AliceTest"}}
```

### 7.7 `list_dir`

List directory entries.

```json
{"id":"7","type":"action","action":"list_dir","args":{"path":"E:\\","limit":20}}
```

### 7.8 `minimize_all`

Minimize user-facing windows using Windows Shell automation.

```json
{"id":"8","type":"action","action":"minimize_all","args":{}}
```

### 7.9 Audio actions

Control Windows master volume. Requires `pycaw` on the Windows PC.

```json
{"id":"9","type":"action","action":"volume_get","args":{}}
{"id":"10","type":"action","action":"volume_set","args":{"level":25}}
{"id":"11","type":"action","action":"volume_mute","args":{}}
{"id":"12","type":"action","action":"volume_unmute","args":{}}
{"id":"13","type":"action","action":"volume_toggle_mute","args":{}}
```

### 7.10 `chrome_state`

Return the latest DOM state pushed by the Chrome extension.

```json
{"id":"8","type":"action","action":"chrome_state","args":{}}
```

### 7.9 `chrome_navigate`

Queue a Chrome tab navigation command for the extension.

```json
{
  "id": "9",
  "type": "action",
  "action": "chrome_navigate",
  "args": {"url": "https://www.youtube.com"}
}
```

The response confirms the command was queued, not necessarily completed. Observe `chrome_state` after a short delay.

### 7.10 `chrome_click`

Queue a click on an element ID from `chrome_state`.

```json
{
  "id": "10",
  "type": "action",
  "action": "chrome_click",
  "args": {"element_id": "wb_12"}
}
```

### 7.11 `chrome_type`

Queue typing into an element ID from `chrome_state`.

```json
{
  "id": "11",
  "type": "action",
  "action": "chrome_type",
  "args": {
    "element_id": "wb_3",
    "text": "Nadin Amizah",
    "clear": true,
    "enter": true
  }
}
```

---

## 8. Chrome extension bridge

The extension lives in:

```txt
chrome_extension/
```

Files:

```txt
manifest.json
background.js
content.js
```

Install once on the Windows PC:

1. Open Chrome.
2. Go to `chrome://extensions`.
3. Enable Developer mode.
4. Click Load unpacked.
5. Select the `chrome_extension` folder inside the Winbridge app directory.

Example path:

```txt
F:\claudecode\exp\10\window_bridge\chrome_extension
```

### 8.1 How the extension works

```txt
Extension background service worker
  → polls Winbridge /chrome/commands every ~1s
  → asks content script for active tab DOM state
  → POSTs latest state to /chrome/update
  → executes queued commands in active tab
  → POSTs command result to /chrome/command/result
```

### 8.2 Chrome bridge HTTP endpoints

Used mostly by the extension, but agents can inspect them.

```http
POST /chrome/update
GET  /chrome/state
POST /chrome/command
GET  /chrome/commands
POST /chrome/command/result
```

`GET /chrome/state` response example:

```json
{
  "connected": true,
  "url": "https://www.youtube.com/",
  "title": "YouTube",
  "viewport": {"width": 1920, "height": 919},
  "scroll": {"x": 0, "y": 0},
  "elements": [
    {
      "id": "wb_0",
      "tag": "input",
      "role": "searchbox",
      "text": "",
      "aria_label": "Search",
      "placeholder": "Search",
      "rect": {"x": 500, "y": 12, "w": 420, "h": 40},
      "visible": true
    }
  ],
  "updated_at": "2026-06-17T14:49:35.224Z"
}
```

### 8.3 Chrome element IDs are temporary

Element IDs like `wb_12` are generated from the latest DOM scan.

Agent rules:

- Call `chrome_state` before using `chrome_click` or `chrome_type`.
- Use the freshest element ID.
- If a command fails, call `chrome_state` again and reselect the element.
- Dynamic pages like YouTube can rerender and invalidate IDs quickly.

### 8.4 Pages where content scripts may not work

Chrome blocks or restricts content scripts on some pages:

```txt
chrome://*
chrome-extension://*
Chrome Web Store pages
some browser-internal pages
```

Normal sites such as YouTube, Google, docs, dashboards, and app pages should work.

---

## 9. Recommended agent workflows

### 9.1 Create a folder on E drive

Goal:

```txt
Create E:\AliceTest and verify it exists.
```

WebSocket flow:

```json
{"id":"s1","type":"start_session","goal":"Create E:\\AliceTest and verify it exists"}
{"id":"1","type":"action","action":"open","args":{"target":"explorer.exe","args":["E:\\"]}}
{"id":"2","type":"action","action":"mkdir","args":{"path":"E:\\AliceTest"}}
{"id":"3","type":"action","action":"path_exists","args":{"path":"E:\\AliceTest"}}
{"id":"s2","type":"finish_session","status":"done"}
```

Use `mkdir`/`path_exists` for correctness. Opening Explorer is only for user-visible feedback.

### 9.2 Navigate Chrome and interact with page DOM

Goal:

```txt
Open YouTube and search for Nadin Amizah.
```

Approximate flow:

```json
{"id":"s1","type":"start_session","goal":"Open YouTube and search Nadin Amizah"}
{"id":"1","type":"action","action":"chrome_navigate","args":{"url":"https://www.youtube.com"}}
{"id":"2","type":"action","action":"chrome_state","args":{}}
```

Then inspect `elements` for a search input. Choose by `tag`, `role`, `aria_label`, `placeholder`, text, and rect.

Then:

```json
{"id":"3","type":"action","action":"chrome_type","args":{"element_id":"wb_SEARCH_ID","text":"Nadin Amizah","clear":true,"enter":true}}
{"id":"4","type":"action","action":"chrome_state","args":{}}
{"id":"s2","type":"finish_session","status":"done"}
```

If the state is stale or command result is not visible yet, wait briefly and call `chrome_state` again.

---

## 10. Python client examples

### 10.1 REST health check

```python
import requests

BASE = "http://192.168.1.100:5100"
print(requests.get(f"{BASE}/health", timeout=5).json())
```

### 10.2 WebSocket goal loop

```python
import asyncio
import json
import websockets

WS = "ws://192.168.1.100:5100/agent/ws"

async def send(ws, msg):
    await ws.send(json.dumps(msg))
    return json.loads(await ws.recv())

async def main():
    async with websockets.connect(WS, open_timeout=10) as ws:
        print(await send(ws, {"id": "s1", "type": "start_session", "goal": "Create test folder"}))
        print(await send(ws, {"id": "1", "type": "action", "action": "mkdir", "args": {"path": "E:\\AgentTest"}}))
        print(await send(ws, {"id": "2", "type": "action", "action": "path_exists", "args": {"path": "E:\\AgentTest"}}))
        print(await send(ws, {"id": "s2", "type": "finish_session", "status": "done"}))

asyncio.run(main())
```

---

## 11. Troubleshooting

### `GET /health` timeout

Check:

- Winbridge server is running on the PC.
- PC IP is correct.
- Windows Firewall allows inbound TCP `5100` from the agent machine.
- Agent and PC are on the same LAN.

### `/chrome/state` shows `connected: false`

Check:

- Extension is installed as unpacked extension.
- Chrome is open.
- Active tab is a normal webpage, not `chrome://`.
- Extension has not errored in `chrome://extensions` → service worker logs.
- Winbridge is reachable at `http://127.0.0.1:5100` from the PC.

### `chrome_click` or `chrome_type` does nothing

Likely causes:

- Element ID is stale.
- Page rerendered.
- The target is inside a cross-origin iframe.
- The element is not actually clickable/typeable.

Fix:

1. Call `chrome_state` again.
2. Re-select the element.
3. Retry once.
4. If still failing, fall back to normal window actions or ask for screenshot/visual control.

### Update failed after adding a new top-level file

The running updater may not allow the new file yet.

Fix:

1. Upload a ZIP containing only the new `updater.py` allowlist.
2. Wait for `/health`.
3. Upload the full update ZIP.

---

## 12. Safety rules for AI agents

- Always observe before acting.
- Prefer deterministic file/DOM actions over typing into arbitrary focused windows.
- Never type secrets unless explicitly instructed by the user.
- Do not assume the focused window is the intended target.
- Use `path_exists` or `chrome_state` to verify completion.
- Keep each action small and reversible where possible.
- Report uncertainty when a UI state cannot be verified.
- For destructive file operations, ask the user first unless the goal explicitly authorizes them.

---

## 13. v1 feature summary

Core:

```txt
GET  /health
GET  /screen/state
POST /action/open
POST /action/focus
POST /action/type
```

Admin/self-update:

```txt
GET  /admin/version
GET  /admin/update/status
POST /admin/restart
POST /admin/update
```

Agent sessions:

```txt
WS   /agent/ws
GET  /agent/sessions
GET  /agent/session/<session_id>
```

Chrome bridge:

```txt
POST /chrome/update
GET  /chrome/state
POST /chrome/command
GET  /chrome/commands
POST /chrome/command/result
```

WebSocket actions:

```txt
screen_state
open
focus
type
mkdir
path_exists
list_dir
minimize_all
volume_get
volume_set
volume_mute
volume_unmute
volume_toggle_mute
chrome_state
chrome_click
chrome_type
chrome_navigate
```
