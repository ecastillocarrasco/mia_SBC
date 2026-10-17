'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeBackendUrl, normalizeConfig } = require('../src/config.cjs');
const { endpoint, sendPrompt, speak } = require('../src/backend.cjs');
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
    status:200,ok:true,json:async()=>({answer:'Datos recibidos',speech_text:'Resumen',status:'ok'})
  }; };
  try {
    const res = await sendPrompt('http://127.0.0.1:5001','Hola mIA');
    assert.equal(res.answer,'Datos recibidos');
    assert.equal(res.speechText,'Resumen');
    assert.equal(invoked.u,'http://127.0.0.1:5001/api/mia/v4/chat');
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
