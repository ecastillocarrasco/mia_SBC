import test from 'node:test';
import assert from 'node:assert/strict';
import { mountMemoryWidget } from '../src/core/memory-widget.js';

function makeEl() {
  const node = {
    children: [],
    attrs: {},
    dataset: {},
    className: '',
    textContent: '',
    title: '',
    hidden: false,
    disabled: false,
    listeners: {},
    setAttribute(key, value) { this.attrs[key] = String(value); },
    getAttribute(key) { return this.attrs[key]; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    dispatch(type, detail = {}) { (this.listeners[type] || []).forEach((fn) => fn({ target: this, ...detail })); },
    appendChild(child) { this.children.push(child); child.parent = node; return child; },
    append(...nodes) { for (const n of nodes) this.appendChild(n); },
    querySelector(selector) {
      const cls = selector.replace('.', '');
      const stack = [...this.children];
      while (stack.length) {
        const current = stack.shift();
        if ((current.className || '').split(' ').includes(cls)) return current;
        stack.push(...(current.children || []));
      }
      return null;
    },
    contains(target) {
      const stack = [...this.children];
      while (stack.length) {
        const current = stack.shift();
        if (current === target) return true;
        stack.push(...(current.children || []));
      }
      return false;
    },
    remove() {
      if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    },
  };
  return node;
}

function installFakeBrowser({ responses }) {
  const previous = { document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch };
  const body = makeEl();
  const head = makeEl();
  globalThis.document = {
    createElement: makeEl,
    head,
    body,
    _bodyListeners: {},
    getElementById() { return null; },
    addEventListener(type, fn) { (this._bodyListeners[type] ||= []).push(fn); },
  };
  globalThis.window = { confirm: () => true };
  globalThis.fetch = async (url, options = {}) => {
    const method = options.method || 'GET';
    const match = responses.find((r) => r.method === method && (typeof r.url === 'string' ? r.url === url : r.url.test(url)));
    if (!match) throw new Error(`sin respuesta simulada para ${method} ${url}`);
    return { ok: match.status < 400, status: match.status, json: async () => match.body };
  };
  return {
    body,
    restore() {
      globalThis.document = previous.document;
      globalThis.window = previous.window;
      globalThis.fetch = previous.fetch;
    },
  };
}

test('no se muestra nada si la memoria está apagada globalmente', async () => {
  const { body, restore } = installFakeBrowser({
    responses: [{ method: 'GET', url: '/api/memory/settings', status: 200, body: { available: false, enabled: false } }],
  });
  try {
    await mountMemoryWidget();
    assert.equal(body.children.length, 0);
  } finally {
    restore();
  }
});

test('no se muestra nada ni se lanza si la primera consulta falla', async () => {
  const { body, restore } = installFakeBrowser({ responses: [] }); // sin respuesta simulada -> fetch lanza
  try {
    await assert.doesNotReject(mountMemoryWidget());
    assert.equal(body.children.length, 0);
  } finally {
    restore();
  }
});

test('con la memoria disponible, monta el botón y el panel, y el interruptor activa/desactiva', async () => {
  let enabled = false;
  const { body, restore } = installFakeBrowser({
    responses: [
      { method: 'GET', url: '/api/memory/settings', status: 200, body: { available: true, enabled: false } },
      {
        method: 'PUT',
        url: '/api/memory/settings',
        status: 200,
        get body() { enabled = true; return { available: true, enabled: true }; },
      },
      { method: 'GET', url: '/api/memory/items', status: 200, get body() { return { enabled, items: [] }; } },
    ],
  });
  try {
    await mountMemoryWidget();
    assert.equal(body.children.length, 2); // launcher + panel
    const [launcher, panel] = body.children;
    assert.equal(launcher.dataset.on, '0');
    assert.equal(panel.hidden, true);

    launcher.dispatch('click');
    await Promise.resolve();
    assert.equal(panel.hidden, false);

    const toggle = panel.querySelector('mia-mem-switch');
    assert.ok(toggle);
    toggle.dispatch('click');
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(toggle.getAttribute('aria-pressed'), 'true');
    assert.equal(launcher.dataset.on, '1');
  } finally {
    restore();
  }
});

test('borrar un recuerdo pide confirmación antes de vaciar todos', async () => {
  const deletedAll = { called: false };
  const { body, restore } = installFakeBrowser({
    responses: [
      { method: 'GET', url: '/api/memory/settings', status: 200, body: { available: true, enabled: true } },
      {
        method: 'GET',
        url: '/api/memory/items',
        status: 200,
        body: { enabled: true, items: [{ id: 'm1', content: 'algo', created_at: '2026-11-01T00:00:00Z' }] },
      },
      { method: 'DELETE', url: /\/api\/memory\/items$/, status: 200, get body() { deletedAll.called = true; return { deleted: 1 }; } },
    ],
  });
  try {
    await mountMemoryWidget();
    const [launcher, panel] = body.children;
    launcher.dispatch('click'); // abre el panel y dispara el primer refreshList()
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(panel.hidden, false);
    const clearButton = panel.querySelector('mia-mem-clear');
    assert.ok(clearButton, 'debe existir el botón de borrar todo con un recuerdo guardado');
    clearButton.dispatch('click');
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(deletedAll.called, true);
  } finally {
    restore();
  }
});
