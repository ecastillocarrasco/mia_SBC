'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Cada test re-requiere el modulo desde cero: auth.cjs guarda estado (pca/authConfig) a nivel de
// modulo, y mezclar ese estado entre tests (orden, fail-open vs login real) seria fragil.
function freshAuth() {
  delete require.cache[require.resolve('../src/auth.cjs')];
  return require('../src/auth.cjs');
}

test('backend inalcanzable: fail-open, nunca lanza, getAccessToken devuelve null', async () => {
  const auth = freshAuth();
  const original = global.fetch;
  global.fetch = async () => { throw new Error('ECONNREFUSED'); };
  try {
    const result = await auth.ensureAuthenticated('/tmp/mia-desktop-test', 'http://127.0.0.1:5001');
    assert.equal(result, null);
    assert.equal(await auth.getAccessToken(), null);
  } finally { global.fetch = original; }
});

test('modo dev (requires_login:false): no-op, nunca construye MSAL, getAccessToken null', async () => {
  const auth = freshAuth();
  const original = global.fetch;
  let calls = 0;
  global.fetch = async (url) => {
    calls++;
    assert.equal(url, 'http://127.0.0.1:5001/api/auth/config');
    return { ok: true, json: async () => ({ mode: 'dev', requires_login: false, entra: null }) };
  };
  try {
    const result = await auth.ensureAuthenticated('/tmp/mia-desktop-test', 'http://127.0.0.1:5001');
    assert.equal(result, null);
    assert.equal(calls, 1);
    assert.equal(await auth.getAccessToken(), null);
  } finally { global.fetch = original; }
});

test('getAccessToken antes de ensureAuthenticated: null, nunca lanza', async () => {
  const auth = freshAuth();
  assert.equal(await auth.getAccessToken(), null);
});

test('/api/auth/config con HTTP no-ok: fail-open igual que un fallo de red', async () => {
  const auth = freshAuth();
  const original = global.fetch;
  global.fetch = async () => ({ ok: false, status: 500 });
  try {
    const result = await auth.ensureAuthenticated('/tmp/mia-desktop-test', 'http://127.0.0.1:5001');
    assert.equal(result, null);
  } finally { global.fetch = original; }
});

test('ensureAuthorized en modo dev (sin ensureAuthenticated previo): ok:true, nunca llama a la red', async () => {
  const auth = freshAuth();
  const original = global.fetch;
  global.fetch = async () => { throw new Error('No debería llamarse a /api/auth/me sin login real'); };
  try {
    const result = await auth.ensureAuthorized('http://127.0.0.1:5001');
    assert.deepEqual(result, { ok: true });
  } finally { global.fetch = original; }
});

test('ensureAuthorized tras requires_login:false: ok:true, nunca llama a la red', async () => {
  const auth = freshAuth();
  const original = global.fetch;
  global.fetch = async (url) => {
    if (String(url).endsWith('/api/auth/me')) throw new Error('No debería llamarse a /api/auth/me en modo dev');
    return { ok: true, json: async () => ({ mode: 'dev', requires_login: false, entra: null }) };
  };
  try {
    await auth.ensureAuthenticated('/tmp/mia-desktop-test', 'http://127.0.0.1:5001');
    const result = await auth.ensureAuthorized('http://127.0.0.1:5001');
    assert.deepEqual(result, { ok: true });
  } finally { global.fetch = original; }
});

test('getAccessToken: llamadas concurrentes con refresco fallido comparten un único login interactivo', async () => {
  const originalFetch = global.fetch;
  const electronPath = require.resolve('electron');
  const msalPath = require.resolve('@azure/msal-node');
  const originalElectronEntry = require.cache[electronPath];
  const originalMsalEntry = require.cache[msalPath];
  let interactiveCalls = 0;
  class FakePCA {
    getTokenCache() { return { getAllAccounts: async () => [{ username: 'ana@sbc.test' }] }; }
    async acquireTokenSilent() { throw new Error('token expirado'); }
    async acquireTokenInteractive() {
      interactiveCalls++;
      await new Promise((resolve) => setTimeout(resolve, 20));
      return { accessToken: 'tok-interactivo', account: { username: 'ana@sbc.test' } };
    }
  }
  require.cache[electronPath] = {
    id: electronPath, filename: electronPath, loaded: true,
    exports: { shell: { openExternal: async () => {} }, safeStorage: { isEncryptionAvailable: () => false } },
  };
  require.cache[msalPath] = {
    id: msalPath, filename: msalPath, loaded: true,
    exports: { PublicClientApplication: FakePCA },
  };
  global.fetch = async () => ({
    ok: true,
    json: async () => ({
      mode: 'entra', requires_login: true,
      entra: { desktop_client_id: 'cid', scope: 'api://mia/.default', tenant_id: 'tid' },
    }),
  });
  try {
    const auth = freshAuth();
    await auth.ensureAuthenticated('/tmp/mia-desktop-test', 'http://127.0.0.1:5001');
    const [t1, t2] = await Promise.all([auth.getAccessToken(), auth.getAccessToken()]);
    assert.equal(t1, 'tok-interactivo');
    assert.equal(t2, 'tok-interactivo');
    assert.equal(interactiveCalls, 1, 'dos getAccessToken() en paralelo no deben abrir dos logins interactivos');
  } finally {
    global.fetch = originalFetch;
    if (originalElectronEntry) require.cache[electronPath] = originalElectronEntry; else delete require.cache[electronPath];
    if (originalMsalEntry) require.cache[msalPath] = originalMsalEntry; else delete require.cache[msalPath];
  }
});
