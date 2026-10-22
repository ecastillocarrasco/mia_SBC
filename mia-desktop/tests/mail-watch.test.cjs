'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Cada test re-requiere el modulo desde cero: lastSeenAt vive a nivel de modulo y mezclarlo entre
// tests seria fragil (mismo motivo que tests/auth.test.cjs).
function fresh() {
  delete require.cache[require.resolve('../src/mail-watch.cjs')];
  delete require.cache[require.resolve('../src/auth.cjs')];
  const auth = require('../src/auth.cjs');
  auth.getAccessToken = async () => null; // sin login real en estos tests
  return require('../src/mail-watch.cjs');
}

function mockFetch(correos) {
  return async () => ({ ok: true, json: async () => ({ sin_leer_mostrados: correos.length, correos }) });
}

test('primera pasada: fija el punto de partida, nunca notifica de golpe toda la bandeja', async () => {
  const mailWatch = fresh();
  const original = global.fetch;
  const seen = [];
  try {
    global.fetch = mockFetch([
      { de: 'Ana', asunto: 'A', recibido: '2026-10-20T10:00:00Z' },
      { de: 'Bea', asunto: 'B', recibido: '2026-10-20T09:00:00Z' },
    ]);
    await mailWatch.checkOnce('http://x', correos => seen.push(correos));
  } finally { global.fetch = original; mailWatch.stop(); }
  assert.deepEqual(seen, []);
});

test('segunda pasada: solo notifica lo llegado despues de la anterior', async () => {
  const mailWatch = fresh();
  const original = global.fetch;
  try {
    global.fetch = mockFetch([{ de: 'Ana', asunto: 'A', recibido: '2026-10-20T10:00:00Z' }]);
    await mailWatch.checkOnce('http://x', () => assert.fail('no debe notificar en la primera pasada'));

    global.fetch = mockFetch([
      { de: 'Carla', asunto: 'C (nuevo)', recibido: '2026-10-20T10:05:00Z' },
      { de: 'Ana', asunto: 'A', recibido: '2026-10-20T10:00:00Z' },
    ]);
    const seen = [];
    await mailWatch.checkOnce('http://x', correos => seen.push(...correos));
    assert.equal(seen.length, 1);
    assert.equal(seen[0].asunto, 'C (nuevo)');
  } finally { global.fetch = original; mailWatch.stop(); }
});

test('sin correos nuevos desde la ultima comprobacion: no notifica', async () => {
  const mailWatch = fresh();
  const original = global.fetch;
  try {
    const correo = { de: 'Ana', asunto: 'A', recibido: '2026-10-20T10:00:00Z' };
    global.fetch = mockFetch([correo]);
    await mailWatch.checkOnce('http://x', () => {});
    await mailWatch.checkOnce('http://x', () => assert.fail('no debe notificar: nada nuevo'));
  } finally { global.fetch = original; mailWatch.stop(); }
});

test('backend inalcanzable: nunca lanza, nunca notifica', async () => {
  const mailWatch = fresh();
  const original = global.fetch;
  try {
    global.fetch = async () => { throw new Error('ECONNREFUSED'); };
    await mailWatch.checkOnce('http://x', () => assert.fail('no debe notificar'));
  } finally { global.fetch = original; mailWatch.stop(); }
});

test('respuesta HTTP no-ok: se trata igual que un fallo de red, sin lanzar', async () => {
  const mailWatch = fresh();
  const original = global.fetch;
  try {
    global.fetch = async () => ({ ok: false, status: 401 });
    await mailWatch.checkOnce('http://x', () => assert.fail('no debe notificar'));
  } finally { global.fetch = original; mailWatch.stop(); }
});

test('start() hace una primera comprobacion inmediata; stop() no lanza', async () => {
  const mailWatch = fresh();
  const original = global.fetch;
  let calls = 0;
  try {
    global.fetch = async () => { calls++; return { ok: true, json: async () => ({ correos: [] }) }; };
    await mailWatch.start('http://x', () => {});
    assert.equal(calls, 1);
  } finally { mailWatch.stop(); global.fetch = original; }
});
