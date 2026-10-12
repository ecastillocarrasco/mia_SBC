import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  sendHologramVia2D, createHologramApiContext,
  normalizeHologramApiResult, HologramApiError,
  HOLOGRAM_COMPAT_ROUTES,
} from '../src/worlds/hologram/hologram-api-v525.js';

const enc = new TextEncoder();
const ndjson = (...events) => new ReadableStream({
  start(controller) {
    for (const event of events) controller.enqueue(enc.encode(`${JSON.stringify(event)}\n`));
    controller.close();
  },
});
const jsonResponse = (content, status=200) => ({ok:status<400,status,json:async()=>content});

function capture() {
  const routes = [], bodies = [], traces = [];
  return {
    routes, bodies, traces,
    wrap(responseFactory) {
      return async (url,options) => {
        routes.push(url);
        bodies.push(JSON.parse(options.body));
        return responseFactory(url,options);
      };
    },
    onTrace(t) { traces.push(t); },
  };
}

test('holograma utiliza la misma primera ruta y contexto del mundo 2D', async () => {
  const c=capture();
  const response={
    answer:'Actualmente hay 24 personas trabajando.',speech_text:'Hay 24 personas trabajando.',
    data:{cards:[{label:'Trabajando ahora',value:24}], table:{columns:['Departamento','Total'],rows:[['Cocina',10],['Restaurante',14]]}},
    context:{period:'2026-10-12'},
  };
  const state=createHologramApiContext();
  const output=await sendHologramVia2D({
    message:'quien esta trabajando ahora mismo',contextState:state,
    fetchImpl:c.wrap(()=>jsonResponse(response)), onTrace:c.onTrace.bind(c),
  });
  assert.deepEqual(c.routes,['/api/mia/v4/chat']);
  assert.equal(c.bodies[0].message,'quien esta trabajando ahora mismo');
  assert.equal(c.bodies[0].context.company,'Sunset Beach Club');
  assert.equal(c.bodies[0].context.locale,'es-ES');
  assert.ok(output.presentations.some(p=>p.cards?.[0]?.value===24));
  assert.ok(output.presentations.some(p=>p.rows?.length===2));
  assert.equal(output.speech,'Hay 24 personas trabajando.');
  assert.equal(state.value.period,'2026-10-12');
  assert.ok(c.traces.some(t=>t.phase==='received' && t.result===true));
});

test('fallback a NDJSON del backend 2D cuando el gateway LLM no responde',async()=>{
  const c=capture();
  const result={natural_answer:'He recibido tres registros',data:{table:{columns:['Area','Personas'],rows:[['Bar',2],['Recepcion',1]]}}};
  const progress=[];
  const output=await sendHologramVia2D({message:'trabajadores ahora',
    fetchImpl:c.wrap((url)=>url.endsWith('/v4/chat')
      ? jsonResponse({detail:'unavailable'},503)
      : {ok:true,status:200,body:ndjson({type:'progress',state:'concentrada',message:'Consultando turnos'}, {type:'result',payload:result})}),
    onProgress:(ev)=>progress.push(ev.type),
    onTrace:c.onTrace.bind(c),
  });
  assert.deepEqual(c.routes,['/api/mia/v4/chat','/api/mia/chat/stream']);
  assert.deepEqual(progress,['progress']);
  assert.equal(output.answer,result.natural_answer);
  assert.equal(output.presentations[0].rows.length,2);
});

test('fallback JSON si gateway y stream NDJSON fallan',async()=>{
  const c=capture();
  const output=await sendHologramVia2D({message:'hola',
    fetchImpl:c.wrap((url)=>url === '/api/mia/chat' ? jsonResponse({response:'¡Hola!'}) : jsonResponse({},404)),
  });
  assert.deepEqual(c.routes,['/api/mia/v4/chat','/api/mia/chat/stream','/api/mia/chat']);
  assert.equal(output.answer,'¡Hola!');
});

test('JSON 200 vacio no se considera resultado y activa el respaldo',async()=>{
  const c=capture();
  const output=await sendHologramVia2D({message:'consulta',
    fetchImpl:c.wrap((url)=>url.endsWith('/v4/chat') ? jsonResponse({status:'ok',data:{}})
      : {ok:true,status:200,body:ndjson({type:'result',payload:{answer:'respuesta respaldada'}})}),
  });
  assert.equal(output.answer,'respuesta respaldada');
  assert.equal(c.routes.length,2);
});

test('el stream NDJSON entrega resultados tras silencios mayores de 25 segundos (simulado)',async()=>{
  const c=capture();
  const stream=new ReadableStream({
    start(controller) {
      controller.enqueue(enc.encode(`${JSON.stringify({type:'progress',message:'Trabajando'})}\n`));
      setTimeout(()=>{
        controller.enqueue(enc.encode(`${JSON.stringify({type:'result',payload:{answer:'Datos listos'}})}\n`));
        controller.close();
      },80);
    },
  });
  const start=Date.now();
  const output=await sendHologramVia2D({message:'personal',
    streamTimeoutMs:350,
    fetchImpl:c.wrap((url)=>url.endsWith('/v4/chat')?jsonResponse({error:'no'},404):{ok:true,status:200,body:stream}),
  });
  assert.equal(output.answer,'Datos listos');
  assert.ok(Date.now()-start>=70);
  assert.equal(c.routes.length,2);
});

test('cancelar con AbortController no salta a otra ruta',async()=>{
  const c=capture();
  const ac=new AbortController();
  const run=sendHologramVia2D({message:'personal',signal:ac.signal,
    llmTimeoutMs:3000,
    fetchImpl:c.wrap(()=>new Promise(()=>{})),
  });
  setTimeout(()=>ac.abort(),40);
  await assert.rejects(run,(e)=>e instanceof HologramApiError && e.code==='cancelled');
  assert.equal(c.routes.length,1);
});

test('si falla todo no devuelve cifras ni resultados ficticios',async()=>{
  const c=capture();
  await assert.rejects(sendHologramVia2D({message:'trabajando',
    fetchImpl:c.wrap(()=>jsonResponse({error:'indisponible'},503))
  }),(e)=>e instanceof HologramApiError && e.code==='upstream-unavailable');
  assert.equal(c.routes.length,3);
});

test('documentos y comparativas se conservan sin inventar datos',()=>{
  const out=normalizeHologramApiResult({answer:'Informe generado',data:{
    cards:[{label:'Vacaciones',value:4}],
    documentos:[],
    comparacion:[{area:'Restaurante',trabajadores:18},{area:'Cocina',trabajadores:9}],
  }});
  assert.ok(out.presentations.some(p=>p.cards));
  assert.ok(out.presentations.some(p=>p.rows?.length===2));
  assert.ok(!JSON.stringify(out.presentations).includes('Total trabajando'));
});

test('el parche altera solamente el holograma, no la ruta legacy ni el modelo',async()=>{
  const main=await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  const html=await readFile(new URL('../src/worlds/hologram/index.html',import.meta.url),'utf8');
  const dir=await readFile(new URL('../src/worlds/hologram/hologram-director-v52.js',import.meta.url),'utf8');
  for (const mark of ['sendHologramVia2D','adaptHologramResult','hologramExecutiveCopy','voice?.cycle()','new MiaHologramDirectorV52','welcomeVoice.replay'])
    assert.ok(main.includes(mark),mark);
  assert.ok(!main.includes('sendHologramTurn('));
  assert.ok(!main.includes('QUERY_INACTIVITY_MS'));
  assert.ok(html.includes('main.js?v=5.2.5'));
  assert.ok(dir.includes("scene.play('mIA_IDLE_SAFE'"));
  assert.deepEqual(HOLOGRAM_COMPAT_ROUTES.map(r=>r.path),
    ['/api/mia/v4/chat','/api/mia/chat/stream','/api/mia/chat']);
});
