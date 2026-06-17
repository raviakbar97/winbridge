# Windows Automation Bridge — Agent Guide

Base URL: `http://HOST_IP:5100`

---

## 1. Check connectivity

```
GET /health
```

Returns `{"status":"ok","service":"winbridge","uia":true}`

---

## 2. Read screen state

```
GET /screen/state
```

### Response
```json
{
  "focused_window": {
    "pid": 1234,
    "name": "chrome.exe",
    "title": "Google Chrome",
    "state": "maximized",
    "ready_for_typing": true
  },
  "visible_windows": [
    {"pid": 1234, "name": "chrome.exe", "title": "...", "state": "maximized"},
    ...
  ],
  "count": 12
}
```

### Fields
| Field | Description |
|-------|-------------|
| `focused_window` | The window currently in the foreground |
| `pid` | Process ID of the window's process |
| `name` | Executable name (e.g. `chrome.exe`, `notepad.exe`) |
| `title` | Window title text |
| `state` | `"normal"`, `"minimized"`, or `"maximized"` |
| `ready_for_typing` | `true` if the focused control is a text input |
| `visible_windows` | All visible GUI windows (excluding background services) |
| `count` | Total number of visible windows |

---

## 3. Open an app

```
POST /action/open
Content-Type: application/json
```

### Simple launch
```json
{"target": "notepad.exe"}
```

### With working directory and args
```json
{"target": "cmd.exe", "working_dir": "C:\\Projects", "args": ["/k", "dir"]}
```

### Launch any path
```json
{"target": "C:\\Program Files\\SomeApp\\app.exe"}
```

---

## 4. Focus a window

```
POST /action/focus
Content-Type: application/json
```

### By PID (most reliable)
```json
{"pid": 1234}
```

### By title (partial match)
```json
{"title": "Notepad"}
```

### Notes
- Combines `AttachThreadInput`, `SwitchToThisWindow`, `SetForegroundWindow`, and topmost toggle to bypass Windows focus-stealing protection.
- Works even from background / non-interactive sessions.

---

## 5. Type text

```
POST /action/type
Content-Type: application/json
```

```json
{"text": "Hello from AI agent", "enter": true}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string | required | Text to type into the focused window |
| `enter` | bool | `true` | Press Enter after typing |

### How it works
1. **Primary**: Clipboard paste (`Ctrl+V`) — fast, handles Unicode
2. **Fallback**: Direct `SendKeys` with proper escaping
3. **Last resort**: `WScript.Shell` COM object

---

## 6. Typical agent workflow

```python
import requests

BRIDGE = "http://192.168.1.100:5100"

# 1. See what's on screen
state = requests.get(f"{BRIDGE}/screen/state").json()
print(state["focused_window"]["title"])

# 2. Open Notepad
requests.post(f"{BRIDGE}/action/open", json={"target": "notepad.exe"})

# 3. Wait, find Notepad, focus it
# (notepad PID comes from screen/state or you look it up)
requests.post(f"{BRIDGE}/action/focus", json={"title": "Notepad"})

# 4. Type into it
requests.post(f"{BRIDGE}/action/type", json={
    "text": "Hello from the remote agent!",
    "enter": True
})
```

---

## Error handling

- All endpoints return `{"error": "..."}` with HTTP 4xx/5xx on failure.
- `/screen/state` and `/action/type` include full tracebacks in logs.
- `/action/focus` returns 404 if the window is not found.
- `/action/open` returns 400 if `target` is missing.

---

## Security note

The server binds to `0.0.0.0` (all interfaces). Restrict by:
- Windows Firewall to allow only the Hermes agent's IP
- Running behind SSH tunnel (recommended for WAN)
