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

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

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

  function textOf(el, limit = 200) {
    const value = el.value || el.innerText || el.textContent || '';
    return String(value).replace(/\s+/g, ' ').trim().slice(0, limit);
  }

  function describeElement(el, index) {
    const rect = el.getBoundingClientRect();
    return {
      id: `wb_${index}`,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      name: el.getAttribute('name') || '',
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
      .slice(0, 500)
      .map((el, index) => ({ el, item: describeElement(el, index) }))
      .filter(({ item }) => item.visible)
      .slice(0, 160)
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

  function cleanText(value) {
    return String(value || '')
      .replace(/\[[^\]]{1,20}\]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function getParagraphs() {
    const selectors = [
      '#mw-content-text .mw-parser-output > p',
      'article p',
      'main p',
      '[role="main"] p',
      '.mw-parser-output > p',
      'p'
    ];
    let nodes = [];
    for (const selector of selectors) {
      nodes = Array.from(document.querySelectorAll(selector));
      const good = nodes.map(n => cleanText(n.innerText || n.textContent)).filter(t => t.length > 80);
      if (good.length >= 2) {
        return {
          url: location.href,
          title: document.title,
          selector,
          paragraphs: good.slice(0, 50),
          headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(h => cleanText(h.innerText || h.textContent)).filter(Boolean).slice(0, 40),
          captured_at: new Date().toISOString()
        };
      }
    }
    return {
      url: location.href,
      title: document.title,
      selector: 'p',
      paragraphs: nodes.map(n => cleanText(n.innerText || n.textContent)).filter(t => t.length > 40).slice(0, 50),
      headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(h => cleanText(h.innerText || h.textContent)).filter(Boolean).slice(0, 40),
      captured_at: new Date().toISOString()
    };
  }

  function findById(elementId) {
    if (!window.__WINBRIDGE_ELEMENTS) getState();
    const index = Number(String(elementId || '').replace('wb_', ''));
    return window.__WINBRIDGE_ELEMENTS && Number.isFinite(index) ? window.__WINBRIDGE_ELEMENTS[index] : null;
  }

  function eventPoint(el) {
    const rect = el.getBoundingClientRect();
    return {
      x: Math.round(rect.left + rect.width / 2),
      y: Math.round(rect.top + rect.height / 2)
    };
  }

  function dispatchMouse(el, type, button = 0) {
    const p = eventPoint(el);
    const event = new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      view: window,
      button,
      buttons: type === 'mouseup' ? 0 : (button === 2 ? 2 : 1),
      clientX: p.x,
      clientY: p.y
    });
    el.dispatchEvent(event);
  }

  function clickElement(args) {
    const el = findById(args.element_id);
    if (!el) throw new Error(`element not found: ${args.element_id}`);
    const button = args.button === 'right' || args.button === 2 ? 2 : 0;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.focus({ preventScroll: true });
    if (button === 2) {
      dispatchMouse(el, 'pointerdown', 2);
      dispatchMouse(el, 'mousedown', 2);
      dispatchMouse(el, 'contextmenu', 2);
      dispatchMouse(el, 'mouseup', 2);
      return { ok: true, action: 'right_click', element_id: args.element_id };
    }
    dispatchMouse(el, 'pointerdown', 0);
    dispatchMouse(el, 'mousedown', 0);
    dispatchMouse(el, 'mouseup', 0);
    dispatchMouse(el, 'click', 0);
    if (typeof el.click === 'function') el.click();
    return { ok: true, action: 'click', element_id: args.element_id };
  }

  function setTextValue(el, value, char) {
    if ('value' in el) {
      el.value = value;
    } else {
      el.textContent = value;
    }
    el.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      cancelable: true,
      inputType: 'insertText',
      data: char
    }));
  }

  async function typeElement(args) {
    const el = findById(args.element_id);
    if (!el) throw new Error(`element not found: ${args.element_id}`);
    const text = String(args.text || '');
    const minDelay = Number(args.min_delay_ms ?? 35);
    const maxDelay = Number(args.max_delay_ms ?? 120);
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.focus({ preventScroll: true });

    let current = 'value' in el ? String(el.value || '') : String(el.textContent || '');
    if (args.clear !== false) {
      current = '';
      if ('value' in el) el.value = '';
      else el.textContent = '';
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
    }

    for (const ch of text) {
      el.dispatchEvent(new KeyboardEvent('keydown', { key: ch, bubbles: true, cancelable: true }));
      current += ch;
      setTextValue(el, current, ch);
      el.dispatchEvent(new KeyboardEvent('keyup', { key: ch, bubbles: true, cancelable: true }));
      const jitter = minDelay + Math.random() * Math.max(0, maxDelay - minDelay);
      await sleep(jitter);
    }
    el.dispatchEvent(new Event('change', { bubbles: true }));
    if (args.enter) {
      el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
      const form = el.form || el.closest('form');
      if (form && typeof form.requestSubmit === 'function') {
        form.requestSubmit();
      } else if (form && typeof form.submit === 'function') {
        form.submit();
      }
      el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
    }
    return { ok: true, action: 'type', mode: 'human_like', element_id: args.element_id, chars: text.length, enter: !!args.enter };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    (async () => {
      try {
        if (message.type === 'GET_DOM_STATE') {
          sendResponse({ ok: true, state: getState() });
        } else if (message.type === 'GET_PARAGRAPHS') {
          sendResponse({ ok: true, article: getParagraphs() });
        } else if (message.type === 'RUN_COMMAND') {
          const cmd = message.command;
          let result;
          if (cmd.action === 'click' || cmd.action === 'right_click') result = clickElement({ ...(cmd.args || {}), button: cmd.action === 'right_click' ? 'right' : (cmd.args || {}).button });
          else if (cmd.action === 'type') result = await typeElement(cmd.args || {});
          else if (cmd.action === 'navigate') {
            location.href = cmd.args.url;
            result = { ok: true, action: 'navigate', url: cmd.args.url };
          } else if (cmd.action === 'paragraphs' || cmd.action === 'article_text') {
            result = getParagraphs();
          } else {
            throw new Error(`unsupported command: ${cmd.action}`);
          }
          sendResponse({ ok: true, result });
        }
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message ? error.message : error) });
      }
    })();
    return true;
  });
})();
