import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHologramTurnGuard, sanitizeHologramTrace } from '../src/worlds/hologram/hologram-lifecycle-v523.js';
import { sendHologramTurn, HologramTurnError } from '../src/worlds/hologram/hologram-turn-v523.js';

const enc = new TextEncoder();
const sse = (type, payload) => `event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`;
const mockClient = () => ({ apiBase:'', sessionId:null, persistSession:false, _emit(){}, _handle(){} });
const makeStream = (messages,{hang=false}={}) => new ReadableStream({
  start(controller){ for(const m of messages) controller.enqueue(enc.encode(m)); if(!hang) controller.close(); }
});
const fetchStream = (body) => async () => ({ ok:true, status:200, body });

test('result SSE termina sin esperar al final de una conexión abierta', async () => {
  const trace = [];
  const output = await sendHologramTurn({
    client:mockClient(), message:'trabajadores trabajando ahora',
    fetchImpl:fetchStream(makeStream([
      sse('progress',{ message:'Consulta iniciada' }),
      sse('result',{ result:{answer:'Hay 24 personas',presentations:[]} }),
    ],{hang:true})),
    timeoutMs:2000,inactivityMs:2000,onTrace:event => trace.push(event),
  });
  assert.equal(output.answer,'Hay 24 personas');
  assert.ok(trace.some(x => x.event==='fetch-start' && x.requestStarted===true));
  assert.ok(trace.some(x => x.event==='result'));
});

test('error SSE termina sin seguir en thinking', async () => {
  await assert.rejects(sendHologramTurn({
    client:mockClient(),message:'trabajando ahora',
    fetchImpl:fetchStream(makeStream([sse('error',{message:'Fallo en personal'})],{hang:true})),
    timeoutMs:1200,inactivityMs:1200,
  }), error=>error instanceof HologramTurnError && error.code==='backend-error');
});

test('petición pendiente sin respuesta HTTP no supera el deadline visual', async () => {
  const ctrl = new AbortController();
  const start = Date.now();
  const guard = createHologramTurnGuard({
    work: () => sendHologramTurn({
      client:mockClient(),message:'personal ahora',
      fetchImpl:()=>new Promise(()=>{}),signal:ctrl.signal,timeoutMs:5000,inactivityMs:5000,
    }),
    signal:ctrl.signal, deadlineMs:210,
    onDeadline:()=>ctrl.abort(),
  });
  await assert.rejects(guard.result, error=>['deadline','cancelled'].includes(error.code));
  assert.ok(Date.now()-start<1000);
});

test('diagnóstico incluye inicio real de petición y fallo visual sin datos personales', () => {
  const diag = sanitizeHologramTrace({
    phase:'sending',event:'fetch-start',requestStarted:true,uiWarning:'thinking-animation',
    elapsedMs:99100,message:'empleados Ana Luis',sessionId:'secreto',http:null,
  });
  assert.equal(diag.version,'5.2.4');
  assert.equal(diag.requestStarted,true);
  assert.equal(diag.uiWarning,'thinking-animation');
  assert.equal(diag.elapsedSeconds,99);
  assert.equal(diag.events,0);
  assert.equal(diag.http,null);
  assert.ok(!JSON.stringify(diag).includes('Ana'));
  assert.ok(!JSON.stringify(diag).includes('secreto'));
});

test('informe distingue fallo de UI de fallo de transporte', () => {
  const ui = sanitizeHologramTrace({phase:'result',event:'result',result:true,uiWarning:'thinking-animation',requestStarted:true,http:200,events:1});
  const server = sanitizeHologramTrace({phase:'error',event:'terminal',lastError:'deadline',requestStarted:true,http:null,events:0});
  assert.equal(ui.result,true);
  assert.equal(ui.uiWarning,'thinking-animation');
  assert.equal(server.result,false);
  assert.equal(server.lastError,'deadline');
  assert.equal(server.requestStarted,true);
});

test('orden de ejecución: guardia ANTES de animación, todo dentro de try', async () => {
  const src = await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  const start = src.indexOf('async function submit(');
  const guarded = src.indexOf('const guarded = createHologramTurnGuard',start);
  const animation = src.indexOf("safely('thinking-animation'",start);
  const tryAt = src.indexOf('  try {',start);
  const firstUi = src.indexOf("safely('clock-start'",start);
  assert.ok(start>=0 && tryAt>start && guarded>tryAt && firstUi>guarded && animation>firstUi);
  assert.ok(src.includes("safely('welcome-cancel'"));
  assert.ok(src.includes("safely('audio-stop'"));
  assert.ok(src.includes("safely('waiting-start'"));
  assert.ok(src.includes("safely('input-focus'"));
});

test('finally libera busy antes de iniciar limpiezas potencialmente fallidas', async () => {
  const src=await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  const start=src.indexOf('async function submit(');
  const fin=src.indexOf('  } finally {',start);
  const released=src.indexOf('busy = false;',fin);
  const reset=src.indexOf('queryPhase = \'ready\';',fin);
  const clock=src.indexOf("safely('clock-final'",fin);
  assert.ok(fin>=0 && released>fin && reset>released && clock>reset);
  assert.ok(src.includes("if (activeTurnController === requestController) activeTurnController = null"));
});

test('sigue limitado al holograma, conserva micrófono y respuesta ejecutiva', async () => {
  const src=await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  const html=await readFile(new URL('../src/worlds/hologram/index.html',import.meta.url),'utf8');
  for(const term of ['voice?.cycle()','adaptHologramResult','hologramExecutiveCopy','renderHologramBrief','hologramVoice.speak','director?.enter','new MiaClient()']) {
    assert.ok(src.includes(term),term);
  }
  assert.ok(html.includes('HG v5.2.4'));
  assert.ok(html.includes('main.js?v=5.2.4'));
  assert.ok(html.includes('id="hgDiagView"'));
});
