const WINBRIDGE = 'http://127.0.0.1:5100';

async function postJson(path, payload) {
  const response = await fetch(`${WINBRIDGE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  return response.json();
}

async function getJson(path) {
  const response = await fetch(`${WINBRIDGE}${path}`);
  return response.json();
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0];
}

async function sendToActiveTab(message) {
  const tab = await activeTab();
  if (!tab || !tab.id) throw new Error('no active tab');
  return chrome.tabs.sendMessage(tab.id, message);
}

async function captureState() {
  const tab = await activeTab();
  if (!tab || !tab.id) return;
  try {
    const response = await sendToActiveTab({ type: 'GET_DOM_STATE' });
    if (response && response.ok) {
      await postJson('/chrome/update', {
        extension: { version: chrome.runtime.getManifest().version },
        tab: { id: tab.id, url: tab.url, title: tab.title, active: tab.active },
        ...response.state
      });
    } else {
      await postJson('/chrome/update', {
        extension: { version: chrome.runtime.getManifest().version },
        tab: { id: tab.id, url: tab.url, title: tab.title, active: tab.active },
        error: response && response.error ? response.error : 'content script did not return state',
        elements: []
      });
    }
  } catch (error) {
    await postJson('/chrome/update', {
      extension: { version: chrome.runtime.getManifest().version },
      tab: tab ? { id: tab.id, url: tab.url, title: tab.title, active: tab.active } : null,
      error: String(error && error.message ? error.message : error),
      elements: []
    }).catch(() => {});
  }
}

async function runCommand(command) {
  try {
    let response;
    if (command.action === 'navigate') {
      const tab = await activeTab();
      if (!tab || !tab.id) throw new Error('no active tab');
      await chrome.tabs.update(tab.id, { url: command.args.url });
      response = { ok: true, result: { ok: true, action: 'navigate', url: command.args.url } };
    } else {
      response = await sendToActiveTab({ type: 'RUN_COMMAND', command });
    }
    await postJson('/chrome/command/result', {
      id: command.id,
      ok: !!(response && response.ok),
      result: response && response.result ? response.result : response
    });
  } catch (error) {
    await postJson('/chrome/command/result', {
      id: command.id,
      ok: false,
      error: String(error && error.message ? error.message : error)
    });
  }
  setTimeout(captureState, 300);
}

async function pollCommands() {
  try {
    await captureState();
    const data = await getJson('/chrome/commands?limit=10');
    const commands = data.commands || [];
    for (const command of commands) {
      await runCommand(command);
    }
  } catch (error) {
    // Winbridge may not be running yet. Retry quietly.
  } finally {
    setTimeout(pollCommands, 1000);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  pollCommands();
});

chrome.runtime.onStartup.addListener(() => {
  pollCommands();
});

pollCommands();
