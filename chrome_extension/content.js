(() => {
  const SELECTOR = [
    'a[href]',
    'button',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[contenteditable="true"]',
    '[tabindex]'
  ].join(',');

  function visible(el, rect) {
    const style = window.getComputedStyle(el);
    return !!(
      rect.width > 0 &&
      rect.height > 0 &&
      style.visibility !== 'hidden' &&
      style.display !== 'none' &&
      rect.bottom >= 0 &&
      rect.right >= 0 &&
      rect.top <= window.innerHeight &&
      rect.left <= window.innerWidth
    );
  }

  function textOf(el) {
    const value = el.value || el.innerText || el.textContent || '';
    return String(value).replace(/\s+/g, ' ').trim().slice(0, 200);
  }

  function describeElement(el, index) {
    const rect = el.getBoundingClientRect();
    return {
      id: `wb_${index}`,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      text: textOf(el),
      aria_label: el.getAttribute('aria-label') || '',
      title: el.getAttribute('title') || '',
      placeholder: el.getAttribute('placeholder') || '',
      href: el.href || '',
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        w: Math.round(rect.width),
        h: Math.round(rect.height)
      },
      visible: visible(el, rect)
    };
  }

  function getElements() {
    window.__WINBRIDGE_ELEMENTS = [];
    return Array.from(document.querySelectorAll(SELECTOR))
      .slice(0, 300)
      .map((el, index) => ({ el, item: describeElement(el, index) }))
      .filter(({ item }) => item.visible)
      .slice(0, 120)
      .map(({ el, item }) => {
        window.__WINBRIDGE_ELEMENTS.push(el);
        item.id = `wb_${window.__WINBRIDGE_ELEMENTS.length - 1}`;
        return item;
      });
  }

  function getState() {
    const active = document.activeElement;
    return {
      url: location.href,
      title: document.title,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scroll: { x: window.scrollX, y: window.scrollY },
      focused: active ? describeElement(active, 'focused') : null,
      elements: getElements(),
      captured_at: new Date().toISOString()
    };
  }

  function findById(elementId) {
    if (!window.__WINBRIDGE_ELEMENTS) getState();
    const index = Number(String(elementId || '').replace('wb_', ''));
    return window.__WINBRIDGE_ELEMENTS && Number.isFinite(index) ? window.__WINBRIDGE_ELEMENTS[index] : null;
  }

  function clickElement(args) {
    const el = findById(args.element_id);
    if (!el) throw new Error(`element not found: ${args.element_id}`);
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.click();
    return { ok: true, action: 'click', element_id: args.element_id };
  }

  function typeElement(args) {
    const el = findById(args.element_id);
    if (!el) throw new Error(`element not found: ${args.element_id}`);
    const text = args.text || '';
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.focus();
    if ('value' in el) {
      if (args.clear !== false) el.value = '';
      el.value += text;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      if (args.clear !== false) el.textContent = '';
      el.textContent += text;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
    }
    if (args.enter) {
      el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
      el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
    }
    return { ok: true, action: 'type', element_id: args.element_id, chars: text.length, enter: !!args.enter };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    try {
      if (message.type === 'GET_DOM_STATE') {
        sendResponse({ ok: true, state: getState() });
      } else if (message.type === 'RUN_COMMAND') {
        const cmd = message.command;
        let result;
        if (cmd.action === 'click') result = clickElement(cmd.args || {});
        else if (cmd.action === 'type') result = typeElement(cmd.args || {});
        else if (cmd.action === 'navigate') {
          location.href = cmd.args.url;
          result = { ok: true, action: 'navigate', url: cmd.args.url };
        } else {
          throw new Error(`unsupported command: ${cmd.action}`);
        }
        sendResponse({ ok: true, result });
      }
    } catch (error) {
      sendResponse({ ok: false, error: String(error && error.message ? error.message : error) });
    }
    return true;
  });
})();
