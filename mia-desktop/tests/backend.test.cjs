'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeBackendUrl, normalizeConfig } = require('../src/config.cjs');
const { endpoint, sendPrompt, speak, welcomeText, getMemorySettings, setMemoryEnabled } = require('../src/backend.cjs');
test('solo HTTPS o loopback HTTP en backend, bloquea usuario y URL arbitraria', () => {
  assert.equal(normalizeBackendUrl('http://evil.example'), 'http://127.0.0.1:5001');
  assert.equal(normalizeBackendUrl('http://localhost:5002'), 'http://localhost:5002');
  assert.equal(normalizeBackendUrl('https://mia.sbc.example'), 'https://mia.sbc.example');
  assert.equal(normalizeBackendUrl('https://user:pass@mia.sbc.example'), 'http://127.0.0.1:5001');
  assert.throws(() => endpoint('http://evil.example', '/api/mia/chat'));
});
test('la frase personalizada se conserva y una malformada se descarta', () => {
  assert.equal(normalizeConfig({wakePhrase:'Buenos dias mIA', wakePhraseEnabled:true}).wakePhrase,'Buenos dias mIA');
  assert.equal(normalizeConfig({wakePhrase:'$(rm -rf /)',wakePhraseEnabled:true}).wakePhrase,'Hola mIA');
});
test('la consulta usa el endpoint V4 y responde con datos sin HTML inventado', async () => {
  const original = global.fetch;
  let invoked;
  global.fetch = async (u, init) => { invoked = {u,init}; return {
    // "speech" es el campo real que devuelve el backend (legacy_payload en compat.py);
    // "speech_text" nunca ha existido ahí -- regresión real que hacía que sendPrompt
    // ignorase siempre este campo y cayera a `answer` para la voz.
    status:200,ok:true,json:async()=>({answer:'Datos recibidos',speech:'Resumen',status:'ok'})
  }; };
  try {
    const res = await sendPrompt('http://127.0.0.1:5001','Hola mIA');
    assert.equal(res.answer,'Datos recibidos');
    assert.equal(res.speechText,'Resumen');
    assert.equal(invoked.u,'http://127.0.0.1:5001/api/mia/v4/chat');
  } finally { global.fetch = original; }
});
test('la URL cruda de un informe nunca llega visible ni locutable: se usa "speech" y se recorta el Markdown', async () => {
  const original = global.fetch;
  global.fetch = async () => ({
    status: 200, ok: true,
    json: async () => ({
      answer: 'Archivos generados y disponibles para descargar:\n- [Informe de nóminas (PDF)](/api/reports/250e9ca9de3e4210bfa83ea3c828eca2)',
      speech: 'Los archivos solicitados están generados y disponibles para descargar.',
      status: 'ok',
    }),
  });
  try {
    const res = await sendPrompt('http://127.0.0.1:5001', 'Genera el informe en PDF');
    assert.doesNotMatch(res.answer, /\/api\/reports\//, 'la URL cruda no debe quedar visible en el texto mostrado');
    assert.match(res.answer, /Informe de nóminas \(PDF\)/);
    assert.equal(res.speechText, 'Los archivos solicitados están generados y disponibles para descargar.');
    assert.doesNotMatch(res.speechText, /\/api\/reports\//);
  } finally { global.fetch = original; }
});
test('si no hay autorizacion no salta a otro endpoint', async () => {
  const original = global.fetch; let calls = 0;
  global.fetch = async () => { calls++; return { status:401, ok:false }; };
  try { const r = await sendPrompt('http://127.0.0.1:5001','Hola'); assert.match(r.error,/autorizado/i); assert.equal(calls,1); }
  finally { global.fetch = original; }
});
test('ElevenLabs recupera audio de backend, no almacena token en escritorio', async () => {
  const original = global.fetch;
  global.fetch = async (_u,_opts) => ({ok:true,status:200,headers:{get:()=> 'audio/mpeg'},arrayBuffer:async()=>Buffer.from([1,2,3])});
  try { const r = await speak('http://127.0.0.1:5001','Hola'); assert.equal(r.audioBase64,'AQID'); }
  finally { global.fetch = original; }
});
test('el backend conserva la tabla real para el renderer y no solo el texto', async () => {
 const original=global.fetch;
 global.fetch=async()=>({ok:true,status:200,json:async()=>({answer:'Listado disponible',data:{table:{rows:[{Persona:'A',Puesto:'Recepción'}]}}})});
 try { const res=await sendPrompt('http://127.0.0.1:5001','Personas y puestos');assert.equal(res.presentation.tables[0].rows[0].Puesto,'Recepción'); }
 finally { global.fetch=original; }
});
test('HTTP 503 de voz se informa como problema del servicio SBC', async () => {
 const original=global.fetch;
 global.fetch=async()=>({ok:false,status:503});
 try { const res=await speak('http://127.0.0.1:5001','Hola');assert.equal(res.code,503);assert.match(res.error,/backend.*503/i); }
 finally { global.fetch=original; }
});
test('el saludo pide la frase al backend (misma fuente que 2D/3D/holograma)', async () => {
  const original = global.fetch;
  let invoked;
  global.fetch = async (u) => { invoked = u; return { ok: true, status: 200, json: async () => ({ text: '¡Hola Enrique! Soy mIA.' }) }; };
  try {
    const res = await welcomeText('http://127.0.0.1:5001');
    assert.equal(res.text, '¡Hola Enrique! Soy mIA.');
    assert.equal(invoked, 'http://127.0.0.1:5001/api/voice/welcome');
  } finally { global.fetch = original; }
});
test('el nombre configurado en Ajustes se envía como override explícito', async () => {
  const original = global.fetch;
  let invoked;
  global.fetch = async (u) => { invoked = u; return { ok: true, status: 200, json: async () => ({ text: 'Hola Lucía' }) }; };
  try {
    await welcomeText('http://127.0.0.1:5001', 'Lucía');
    assert.equal(invoked, 'http://127.0.0.1:5001/api/voice/welcome?name=Luc%C3%ADa');
  } finally { global.fetch = original; }
});
test('si el backend de saludo falla, se informa el error sin lanzar excepción', async () => {
  const original = global.fetch;
  global.fetch = async () => ({ ok: false, status: 500 });
  try { const res = await welcomeText('http://127.0.0.1:5001'); assert.match(res.error, /saludo/i); }
  finally { global.fetch = original; }
});
test('la memoria se consulta al endpoint real de ajustes, nunca a configuración local', async () => {
  const original = global.fetch;
  let invoked;
  global.fetch = async (u, init) => { invoked = { u, init }; return { ok: true, status: 200, json: async () => ({ available: true, enabled: false }) }; };
  try {
    const res = await getMemorySettings('http://127.0.0.1:5001');
    assert.deepEqual(res, { ok: true, available: true, enabled: false });
    assert.equal(invoked.u, 'http://127.0.0.1:5001/api/memory/settings');
    assert.equal(invoked.init.headers.Accept, 'application/json');
  } finally { global.fetch = original; }
});
test('cambiar la memoria envía PUT con el valor booleano, nunca otro tipo', async () => {
  const original = global.fetch;
  let invoked;
  global.fetch = async (u, init) => { invoked = { u, init }; return { ok: true, status: 200, json: async () => ({ available: true, enabled: true }) }; };
  try {
    const res = await setMemoryEnabled('http://127.0.0.1:5001', true);
    assert.deepEqual(res, { ok: true, available: true, enabled: true });
    assert.equal(invoked.u, 'http://127.0.0.1:5001/api/memory/settings');
    assert.equal(invoked.init.method, 'PUT');
    assert.deepEqual(JSON.parse(invoked.init.body), { enabled: true });
  } finally { global.fetch = original; }
});
test('sesión caducada o sin permiso al consultar/cambiar la memoria se informa sin lanzar', async () => {
  const original = global.fetch;
  global.fetch = async () => ({ ok: false, status: 401 });
  try {
    const get = await getMemorySettings('http://127.0.0.1:5001');
    assert.equal(get.unauthorized, true);
    const set = await setMemoryEnabled('http://127.0.0.1:5001', true);
    assert.equal(set.unauthorized, true);
  } finally { global.fetch = original; }
});
test('con el interruptor global apagado, cambiar la memoria responde "no disponible" en vez de un error genérico', async () => {
  const original = global.fetch;
  global.fetch = async () => ({ ok: false, status: 404 });
  try {
    const res = await setMemoryEnabled('http://127.0.0.1:5001', true);
    assert.equal(res.available, false);
    assert.match(res.error, /no está activada/i);
  } finally { global.fetch = original; }
});
test('un fallo de red al consultar o cambiar la memoria no lanza excepción', async () => {
  const original = global.fetch;
  global.fetch = async () => { throw new Error('ECONNREFUSED'); };
  try {
    const get = await getMemorySettings('http://127.0.0.1:5001');
    assert.match(get.error, /no se puede conectar/i);
    const set = await setMemoryEnabled('http://127.0.0.1:5001', false);
    assert.match(set.error, /no se puede conectar/i);
  } finally { global.fetch = original; }
});
