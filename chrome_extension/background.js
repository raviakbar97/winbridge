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

function canInjectInto(tab) {
  const url = tab && tab.url ? tab.url : '';
  return /^https?:\/\//i.test(url) || /^file:\/\//i.test(url);
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0];
}

async function ensureContentScript(tab) {
  if (!tab || !tab.id) throw new Error('no active tab');
  if (!canInjectInto(tab)) throw new Error(`content scripts cannot run on ${tab.url || 'this page'}`);
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
}

async function sendToTabWithRetry(tab, message) {
  if (!tab || !tab.id) throw new Error('no active tab');
  try {
    return await chrome.tabs.sendMessage(tab.id, message);
  } catch (firstError) {
    const msg = String(firstError && firstError.message ? firstError.message : firstError);
    if (!msg.includes('Receiving end does not exist') && !msg.includes('Could not establish connection')) {
      throw firstError;
    }
    await ensureContentScript(tab);
    await new Promise(resolve => setTimeout(resolve, 150));
    return await chrome.tabs.sendMessage(tab.id, message);
  }
}

async function sendToActiveTab(message) {
  const tab = await activeTab();
  return sendToTabWithRetry(tab, message);
}

async function captureState() {
  const tab = await activeTab();
  if (!tab || !tab.id) return;
  try {
    const response = await sendToTabWithRetry(tab, { type: 'GET_DOM_STATE' });
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

async function waitForTabLoad(tabId, timeoutMs = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete') return tab;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return chrome.tabs.get(tabId);
}

async function runCommand(command) {
  try {
    let response;
    if (command.action === 'navigate') {
      const tab = await activeTab();
      if (!tab || !tab.id) throw new Error('no active tab');
      await chrome.tabs.update(tab.id, { url: command.args.url });
      const loadedTab = await waitForTabLoad(tab.id, 12000);
      if (canInjectInto(loadedTab)) {
        await ensureContentScript(loadedTab).catch(() => {});
      }
      response = { ok: true, result: { ok: true, action: 'navigate', url: command.args.url } };
    } else {
      const tab = await activeTab();
      response = await sendToTabWithRetry(tab, { type: 'RUN_COMMAND', command });
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
  setTimeout(captureState, 500);
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
