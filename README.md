# Winbridge v1

Winbridge is a lightweight Windows automation bridge for AI agents running on another device in the same local network.

```txt
AI agent machine / gateway
  ↕ HTTP + WebSocket over LAN
Windows PC running Winbridge
  ↕ Windows UI APIs + Chrome extension
Desktop apps, Explorer, Chrome tabs, web pages
```

## What it does

- Exposes Windows app/window state over HTTP.
- Opens apps and focuses windows.
- Types into focused controls.
- Runs realtime goal sessions over WebSocket.
- Provides safe filesystem primitives such as `mkdir`, `path_exists`, and `list_dir`.
- Self-updates from uploaded ZIP bundles and restarts automatically.
- Includes a Chrome MV3 extension bridge for DOM state, tab management, element coordinates, and article paragraph extraction.
- Supports hybrid browser control: Chrome extension as eyes/helper, Winbridge native Windows input as mouse/keyboard hands.
- Supports native mouse clicks, hotkeys, key presses, human-like typing, volume control, and minimize-all.

## Main endpoints

```txt
GET  /health
GET  /screen/state
POST /action/open
POST /action/focus
POST /action/type

WS   /agent/ws
GET  /agent/sessions
GET  /agent/session/<session_id>

GET  /admin/version
GET  /admin/update/status
POST /admin/restart
POST /admin/update

GET  /chrome/state
POST /chrome/update
POST /chrome/command
GET  /chrome/commands
POST /chrome/command/result
```

## Chrome extension

Install the unpacked extension from:

```txt
chrome_extension/
```

In Chrome:

```txt
chrome://extensions
→ Developer mode ON
→ Load unpacked
→ select chrome_extension folder
```

The extension polls `http://127.0.0.1:5100`, pushes active-tab DOM state to Winbridge, and executes queued commands.

## Agent guide

Read [`AGENT.md`](./AGENT.md) for the full AI-agent integration guide, message formats, examples, workflows, and troubleshooting.

## Network assumption

v1 assumes a trusted LAN:

```txt
agent device and Windows PC are different machines but on the same network
```

Do not expose Winbridge directly to the public internet.
