import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHologramTurnGuard, HologramDeadlineError, sanitizeHologramTrace } from '../src/worlds/hologram/hologram-lifecycle-v523.js';
import { sendHologramTurn, HologramTurnError } from '../src/worlds/hologram/hologram-turn-v523.js';

const enc = new TextEncoder();
const sse = (type, payload) => `event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`;
const mockClient = () => ({apiBase:'',sessionId:'',persistSession:false,_emit(){},_handle(){}});
const makeStream = (messages,{hang=false}={}) => new ReadableStream({
  start(controller){
    for(const m of messages) controller.enqueue(enc.encode(m));
    if(!hang) controller.close();
  },
});
const fetchStream = (stream) => async () => ({ok:true, status:200, body:stream});

test('resultado SSE real aparece sin esperar al cierre del stream', async () => {
  const trace=[];
  const result=await sendHologramTurn({client:mockClient(),message:'personal ahora',
    fetchImpl:fetchStream(makeStream([
      sse('progress',{message:'pensando'}),
      sse('result',{result:{answer:'Consulta resuelta',presentations:[]}}),
    ],{hang:true})),onTrace:(state)=>trace.push(state),timeoutMs:5000,inactivityMs:5000});
  assert.equal(result.answer,'Consulta resuelta');
  assert.ok(trace.some(x=>x.event==='result'));
});

test('evento SSE error es TERMINAL inmediato, sin bucle de animación', async () => {
  let events=0;
  const start=Date.now();
  await assert.rejects(
    sendHologramTurn({client:mockClient(),message:'trabajando ahora',
      fetchImpl:fetchStream(makeStream([sse('progress',{message:'consultando'}),
        sse('error',{message:'Error al consultar fuente de empleados'})],{hang:true})),
      onTrace:()=>events++,timeoutMs:5000,inactivityMs:5000}),
    error => error instanceof HologramTurnError && error.code==='backend-error'
  );
  assert.ok(Date.now()-start<1000);
  assert.ok(events>=2);
});

test('done sin result no sigue esperando', async () => {
  await assert.rejects(sendHologramTurn({client:mockClient(),message:'x',
    fetchImpl:fetchStream(makeStream([sse('done',{ok:true})],{hang:true})),
    timeoutMs:5000,inactivityMs:5000}),
  e=>e.code==='missing-result');
});

test('guardia de UI libera aunque el trabajo ignore completamente AbortSignal', async () => {
  const start=Date.now();
  const controller=new AbortController();
  const statuses=[];
  const guard=createHologramTurnGuard({
    work:()=>new Promise(()=>{}), signal:controller.signal,deadlineMs:220,
    onDeadline:(code)=>{statuses.push(code);controller.abort();}
  });
  await assert.rejects(guard.result,e=>e instanceof HologramDeadlineError && e.code==='deadline');
  assert.deepEqual(statuses,['deadline']);
  assert.ok(Date.now()-start<1500);
});

test('cancelación de usuario termina sin mostrar indefinidamente pensando', async () => {
  const controller=new AbortController();
  const guard=createHologramTurnGuard({work:()=>new Promise(()=>{}),signal:controller.signal,deadlineMs:5000});
  controller.abort();
  await assert.rejects(guard.result,e=>e.code==='cancelled');
});

test('consulta correcta gana al límite y no llama a onDeadline', async () => {
  const statuses=[];
  const guard=createHologramTurnGuard({work:()=>Promise.resolve({answer:'24 trabajadores'}),deadlineMs:500,
    onDeadline:(code)=>statuses.push(code)});
  const result=await guard.result;
  assert.equal(result.answer,'24 trabajadores');
  assert.deepEqual(statuses,[]);
});

test('diagnóstico nunca muestra sesión, usuario, mensaje ni datos', () => {
  const result=sanitizeHologramTrace({phase:'stream',event:'progress',events:4,http:200,
    elapsedMs:15670, sessionId:'secreto',message:'Ana está de servicio',employees:['Ana','Luis']});
  const txt=JSON.stringify(result);
  assert.equal(result.version,'5.2.3');
  assert.equal(result.elapsedSeconds,16);
  assert.ok(!txt.includes('Ana'));
  assert.ok(!txt.includes('secreto'));
});

test('main siempre ofrece salida visual, versión visible en ?diag=1 y cancelación', async () => {
  const main=await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  const html=await readFile(new URL('../src/worlds/hologram/index.html',import.meta.url),'utf8');
  assert.ok(main.includes('createHologramTurnGuard'));
  assert.ok(main.includes('startStatusClock()'));
  assert.ok(main.includes("queryPhase !== 'querying'"));
  assert.ok(main.includes("queryPhase = 'presenting'"));
  assert.ok(main.includes("queryPhase = 'terminal'"));
  assert.ok(main.includes('clearStatusClock()'));
  assert.ok(main.includes('const cancelled = code === \'cancelled\''));
  assert.ok(!main.includes('if (requestController.signal.aborted) return;'));
  for(const name of ['hgQueryMonitor','hgCancelQuery','hgDiagPanel','hgDiagCopy','hgDiagView']){
    assert.ok(html.includes(`id="${name}"`),name);
  }
  assert.ok(html.includes('v=5.2.3'));
});
