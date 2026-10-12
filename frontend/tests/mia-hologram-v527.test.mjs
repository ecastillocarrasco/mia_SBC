import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {
  sendHologramVia2D, createHologramApiContext, HologramApiError,
} from '../src/worlds/hologram/hologram-api-v525.js';
import {createHologramReplyIntegrity} from '../src/worlds/hologram/hologram-integrity-v526.js';
import {
  localHologramSocialReply, isLiveWorkforceQuestion,
  inspectLiveWorkforceProof, unverifiedWorkforceResponse,
} from '../src/worlds/hologram/hologram-truth-v527.js';

const encoder = new TextEncoder();
const json = (data, status=200) => ({ok:status>=200&&status<300,status,json:async()=>data});
const stream = (...events) => ({ok:true,status:200,body:new ReadableStream({start(controller){
  for(const ev of events) controller.enqueue(encoder.encode(JSON.stringify(ev)+'\n'));
  controller.close();
}})});
function proof(count, opts={}) {
  return {answer:'Texto generado por el backend', data: {provenance:{
    source:'turnos',scope:'working_now',coverage:'complete',
    as_of:new Date().toISOString(),working_count:count,...opts,
  }}};
}
function capture(factory) {
  const paths=[], bodies=[], traces=[];
  return {
    paths,bodies,traces,
    fetchImpl: async (url,init) => {
      paths.push(url);bodies.push(JSON.parse(init.body));
      assert.equal(init.cache,'no-store');
      return factory(url,init);
    },
    onTrace: (v)=>traces.push(v),
  };
}

 test('Cortesias se resuelven sin backend ni datos de personal', async()=>{
  const c = capture(() => {throw new Error('Network must not be called')});
  for(const message of ['gracias','Gracias,','muchas gracias','gracias mia','Te lo agradezco']) {
    const output = await sendHologramVia2D({message,fetchImpl:c.fetchImpl,onTrace:c.onTrace});
    assert.match(output.answer,/nada|placer|Cuando quieras/);
    assert.equal(output.presentations.length,0);
    assert.ok(!output.answer.includes('127'));
  }
  assert.equal(c.paths.length,0);
  assert.ok(c.traces.some(v=>v.route==='local-social'));
});

test('Hola mia no ejecuta herramientas ni reactiva respuestas anteriores',async()=>{
  const c=capture(()=>{throw new Error('No network')});
  const output=await sendHologramVia2D({message:'Hola MIA',fetchImpl:c.fetchImpl});
  assert.match(output.answer,/Hola/);
  assert.equal(c.paths.length,0);
});

test('Consulta de trabajadores ahora se distingue de ayer',()=>{
  for(const q of ['\u00bfQui\u00e9n est\u00e1 trabajando ahora mismo?', 'trabajadores trabajando ahora',
    '\u00bfCu\u00e1ntos empleados est\u00e1n de turno hoy?', '\u00bfQui\u00e9n est\u00e1 de turno ahora?']) {
    assert.equal(isLiveWorkforceQuestion(q),true,q);
  }
  for(const q of ['gracias','Hola mia','\u00bfQui\u00e9n trabaj\u00f3 ayer?', '\u00bfCu\u00e1ntos empleados hay en plantilla?',
      '\u00bfQui\u00e9n tiene turno ma\u00f1ana?']) {
    assert.equal(isLiveWorkforceQuestion(q),false,q);
  }
});

test('Nunca pregunta a la pasarela LLM un total de servicio actual',async()=>{
  const c=capture(url=>url.includes('stream')
    ? stream({type:'result',payload:{answer:'Trabajan 127 personas actualmente',kpis:[{label:'Trabajando ahora',value:127}]}})
    : json({answer:'Trabajan 127 personas actualmente'}));
  const output=await sendHologramVia2D({message:'trabajadores trabajando ahora',fetchImpl:c.fetchImpl,onTrace:c.onTrace});
  assert.deepEqual(c.paths,['/api/mia/chat/stream','/api/mia/chat']);
  assert.equal(output.source,'unverified-workforce');
  assert.equal(output.presentations.length,0);
  assert.ok(!JSON.stringify(output).includes('127'));
  assert.ok(c.traces.some(v=>v.validation==='workforce-unverified'));
});

test('127 con KPI pero sin procedencia NO pasa a voz ni gr\u00e1fica',async()=>{
  const c=capture(url=>url.includes('stream')
    ? stream({type:'result',payload:{speech:'Hay 127 trabajadores',data:{cards:[{label:'Trabajando ahora',value:127}]}}})
    : json({answer:'Hay 127 trabajadores',working_now:127}));
  const output=await sendHologramVia2D({message:'\u00bfCu\u00e1ntos trabajadores est\u00e1n trabajando ahora?',fetchImpl:c.fetchImpl});
  assert.ok(!JSON.stringify(output).includes('127'));
  assert.match(output.speech,/no incluye un recuento verificable/);
});

test('Prueba operativa fresca, completa y estructurada se presenta sin el texto libre',async()=>{
  const c=capture(url=>url.includes('stream')
    ? stream({type:'result',payload:proof(9)})
    : json({answer:'No deberia usarse'}));
  const output=await sendHologramVia2D({message:'\u00bfQui\u00e9n est\u00e1 trabajando ahora mismo?',fetchImpl:c.fetchImpl,onTrace:c.onTrace});
  assert.deepEqual(c.paths,['/api/mia/chat/stream']);
  assert.equal(output.working_now,9);
  assert.equal(output.verified_live_workforce,true);
  assert.equal(output.presentations[0].value,9);
  assert.ok(!output.answer.includes('Texto generado'));
  assert.ok(c.traces.some(v=>v.validation==='workforce-proof'));
});

test('Ruta LLM no demuestra un recuento, incluso si imita la procedencia',()=>{
  assert.equal(inspectLiveWorkforceProof(proof(127),'llm').ok,false);
});

test('Registro antiguo no prueba los trabajadores de ahora',()=>{
  const p=proof(127,{as_of:new Date(Date.now()-60*60*1000).toISOString()});
  assert.equal(inspectLiveWorkforceProof(p,'backend-stream').reason,'stale-timestamp');
});

test('Desglose parcial no se acepta como total de personal',()=>{
  const p=proof(4,{coverage:'partial'});
  assert.equal(inspectLiveWorkforceProof(p,'backend-stream').reason,'partial-coverage');
});

test('Una prueba de origen pero sin scope de recuento actual se descarta',()=>{
  const p=proof(127,{scope:'all_employees'});
  assert.equal(inspectLiveWorkforceProof(p,'backend-stream').reason,'wrong-scope');
});

test('Total como texto inventado o decimal no se acepta como prueba',()=>{
  for (const count of ['127',127.4,-2,null]) {
    assert.equal(inspectLiveWorkforceProof(proof(count),'backend-json').ok,false);
  }
});

test('No se actualiza el contexto con respuestas no verificadas',async()=>{
  const state=createHologramApiContext({previous_intent:'mail'});
  const c=capture(url=>url.includes('stream') ? stream({type:'result',payload:{answer:'127',context:{poison:'from old answer'}}})
    : json({answer:'127',context:{poison:'from llm'}}));
  const output=await sendHologramVia2D({message:'trabajadores trabajando ahora',contextState:state,fetchImpl:c.fetchImpl});
  assert.equal(output.source,'unverified-workforce');
  assert.equal(state.value.poison,undefined);
  assert.equal(c.bodies[0].context.previous_intent,undefined);
  assert.equal(state.value.previous_intent,'mail');
});

test('Gracias despu\u00e9s de un error operacional nunca repite resultados previos',async()=>{
  const ctx=createHologramApiContext(), integrity=createHologramReplyIntegrity();
  const c=capture(url=>url.includes('stream')
    ? stream({type:'result',payload:{answer:'127 trabajadores en servicio'}})
    : json({answer:'127 trabajadores en servicio'}));
  const first=await sendHologramVia2D({message:'quienes estan trabajando ahora',contextState:ctx,replyIntegrity:integrity,fetchImpl:c.fetchImpl});
  const second=await sendHologramVia2D({message:'Gracias',contextState:ctx,replyIntegrity:integrity,fetchImpl:c.fetchImpl});
  assert.equal(first.verified_live_workforce,false);
  assert.equal(second.source,'local-social');
  assert.ok(!second.speech.includes('127'));
  assert.equal(c.paths.length,2);
});

test('Consulta no operativa conserva ruta general y contexto de conversacion',async()=>{
  const ctx=createHologramApiContext({preferencia:'breve'});
  const c=capture(url=>json({answer:'El informe est\u00e1 disponible.',context:{topic:'reports'}}));
  const result=await sendHologramVia2D({message:'Resume el informe econ\u00f3mico',fetchImpl:c.fetchImpl,contextState:ctx});
  assert.equal(c.paths[0],'/api/mia/v4/chat');
  assert.equal(c.bodies[0].context.preferencia,'breve');
  assert.equal(result.answer,'El informe est\u00e1 disponible.');
  assert.equal(ctx.value.topic,'reports');
});

test('Nueva consulta cancelada no habilita una respuesta atrasada',async()=>{
  const ac=new AbortController();
  const c=capture(()=>new Promise(resolve=>setTimeout(()=>resolve(json(proof(127))),80)));
  const work=sendHologramVia2D({message:'trabajadores trabajando ahora',signal:ac.signal,fetchImpl:c.fetchImpl});
  setTimeout(()=>ac.abort(),12);
  await assert.rejects(work,(e)=>e instanceof HologramApiError && e.code==='cancelled');
});

test('Holograma V527 no altera GLB ni mundos 2D/3D',async()=>{
  const main=await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  const html=await readFile(new URL('../src/worlds/hologram/index.html',import.meta.url),'utf8');
  assert.ok(main.includes('replyIntegrity: hgIntegrity'));
  assert.ok(main.includes('voice?.cycle()'));
  assert.ok(main.includes('new MiaHologramDirectorV52'));
  assert.match(html,/main\.js\?v=5\.2\.7/);
  assert.ok(!main.includes('sendHologramTurn('));
});

test('No extrapola un departamento a toda la plantilla',()=>{
  const p=proof(7,{department:'cocina'});
  const valid=inspectLiveWorkforceProof(p,'backend-stream',Date.now(),
    'Cuantos trabajadores estan trabajando en cocina ahora');
  assert.equal(valid.ok,true);
  assert.equal(valid.department,'cocina');
  const bad=inspectLiveWorkforceProof(p,'backend-stream',Date.now(),
    'Cuantos trabajadores estan trabajando en restaurante ahora');
  assert.equal(bad.reason,'department-mismatch');
});

test('Una fecha sin zona horaria no acredita el estado actual',()=>{
  const p=proof(12,{as_of:'2026-10-12T03:00:00'});
  assert.equal(inspectLiveWorkforceProof(p,'backend-stream').reason,'timestamp-without-timezone');
});

test('Saludo mas peticion de datos no se intercepta como cortesia',()=>{
  assert.equal(localHologramSocialReply('Hola, dime cuantos trabajan ahora'),null);
  assert.equal(localHologramSocialReply('Gracias, y cuantos empleados hay?'),null);
});
