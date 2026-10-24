// Regression test for the dropped-`onDismiss`-parameter bug: promptForMail() used to reference a
// bare `onDismiss` identifier it never destructured, which threw a ReferenceError in this ES
// module's strict mode before the balloon was ever appended to the DOM. announceNewMail() swallows
// that into console.error, so the balloon silently never appeared. Run with:
//   node --experimental-loader=./tests/support/css-stub-loader.mjs --test tests/mail-watch-prompt.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

class FakeElement {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.parentNode = null;
    this._listeners = {};
    this.style = {};
  }
  setAttribute(key, value) { this[`attr_${key}`] = value; }
  addEventListener(type, cb) { (this._listeners[type] ||= []).push(cb); }
  click() { (this._listeners.click || []).forEach((cb) => cb({})); }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...nodes) { for (const node of nodes) this.appendChild(node); }
  removeChild(child) {
    this.children = this.children.filter((c) => c !== child);
    child.parentNode = null;
    return child;
  }
}

const body = new FakeElement('body');
globalThis.document = { body, createElement: (tag) => new FakeElement(tag) };

const storage = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (storage.has(k) ? storage.get(k) : null),
  setItem: (k, v) => storage.set(k, v),
  removeItem: (k) => storage.delete(k),
};

globalThis.window = {
  setTimeout: (...args) => setTimeout(...args),
  setInterval: (...args) => setInterval(...args),
  clearInterval: (...args) => clearInterval(...args),
  addEventListener: () => {},
  removeEventListener: () => {},
  focus: () => {},
};

const { announceNewMail, consumeMailPrompt } = await import('../src/core/mail-watch.js');

function dismissButton() {
  const actions = body.children.at(-1)?.children.at(-1);
  return actions?.children.find((btn) => btn.textContent === 'Ahora no');
}

test('announceNewMail renders the balloon and wires onDismiss without throwing', () => {
  storage.clear();
  body.children = [];
  let dismissed = false;
  const correo = { de: 'rrhh@sbc.test', asunto: 'Nómina de octubre', recibido: '2026-10-24T09:00:00Z' };
  assert.doesNotThrow(() => {
    announceNewMail([correo], {
      speak: () => {},
      onSummary: () => {},
      onDetails: () => {},
      onDismiss: () => { dismissed = true; },
    });
  });
  assert.equal(body.children.length, 1, 'the balloon must be appended to document.body');
  const btn = dismissButton();
  assert.ok(btn, '"Ahora no" button must exist');
  btn.click();
  assert.equal(dismissed, true, 'clicking "Ahora no" must invoke onDismiss');
  assert.equal(body.children.length, 0, 'dismissing must remove the balloon from the DOM');
});

test('promptForMail still works when onDismiss is omitted (no ReferenceError)', async () => {
  storage.clear();
  body.children = [];
  const { promptForMail } = await import('../src/core/mail-watch.js');
  const correo = { de: 'ana@sbc.test', asunto: 'Vacaciones' };
  assert.doesNotThrow(() => promptForMail(correo, { onSummary: () => {}, onDetails: () => {} }));
  const btn = dismissButton();
  assert.doesNotThrow(() => btn.click());
});

test('consumeMailPrompt recognizes a natural-language dismissal after the balloon is shown', () => {
  storage.clear();
  body.children = [];
  announceNewMail([{ de: 'x@sbc.test', asunto: 'Asunto' }], { speak: () => {} });
  const result = consumeMailPrompt('ahora no, sigamos con lo de antes');
  assert.equal(result?.action, 'dismiss');
});
