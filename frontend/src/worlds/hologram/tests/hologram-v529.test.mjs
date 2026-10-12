import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sendHologramVia2D, createHologramApiContext, isReportGenerationIntent } from '../hologram-api-v525.js';
import { extractHologramJob, pollHologramJob, reportDownloadHref, jobIsActive } from '../hologram-jobs-v529.js';
import { readHologramWorldContext, saveHologramWorldContext,
 bindHologramWorldNavigation } from '../hologram-session-v529.js';
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});

test('Solicitud PDF económica se reconoce como creación no idempotente',()=>{
 assert.equal(isReportGenerationIntent('Genera un informe completo en PDF de comparativa de costes en nóminas por departamento en agosto de 2026'),true);
 assert.equal(isReportGenerationIntent('¿Qué informes de nóminas hay disponibles?'),false);
 assert.equal(isReportGenerationIntent('hola'),false);
});

test('Informe no se duplica entre tres rutas tras HTTP 504',async()=>{
 const urls=[];
 await assert.rejects(sendHologramVia2D({message:'Genera un informe PDF de nóminas en agosto 2026',
  fetchImpl:async(url)=>{urls.push(url);return json({detail:'timeout'},504);}}),e=>e.code==='report-state-uncertain');
 assert.deepEqual(urls,['/api/mia/v4/chat']);
});

test('Respuestas 202 con job sin answer se consideran terminales válidas',async()=>{
 const result=await sendHologramVia2D({message:'Genera un informe PDF por departamento',
  fetchImpl:async()=>json({job:{job_id:'J-100',status:'queued'}},202)});
 assert.equal(extractHologramJob(result).job_id,'J-100');
});

test('Informe asíncrono genera un GET por sondeo hasta completado; no POST adicional',async()=>{
 const received=[];let nth=0;
 const final=await pollHologramJob('safe report 1',{pollMs:0,sleep:async()=>{},
   fetchImpl:async(url,opts)=>{
     received.push({url,method:opts.method});
     nth++;
     return json({job_id:'safe report 1',status:nth===1?'queued':nth===2?'running':'completed',
       report_id:nth===3?'report_2026_08':null,progress:nth===1?0.1:nth===2?0.5:1});
   }});
 assert.equal(final.status,'completed');
 assert.equal(reportDownloadHref(final),'/api/reports/report_2026_08');
 assert.equal(received.length,3);
 assert.ok(received.every(c=>c.method==='GET' && c.url==='/api/jobs/safe%20report%201'));
});

test('No se da enlace al informe antes de completarse',()=>{
 const queued=extractHologramJob({data:{job:{job_id:'X',status:'queued',report_id:'R'}}});
 assert.equal(reportDownloadHref(queued),'');
 assert.equal(jobIsActive(queued),true);
 assert.equal(reportDownloadHref({...queued,status:'failed'}),'');
});

test('Fallo de informe recibido del servidor es final, sin bucle',async()=>{
 let calls=0;
 const status=await pollHologramJob('ABC',{fetchImpl:async()=>{calls++;return json({job_id:'ABC',status:'failed',error_message:'No hay datos'});}});
 assert.equal(status.status,'failed');
 assert.equal(calls,1);
});

test('Errores repetidos de estado terminan de forma acotada',async()=>{
 let calls=0;
 await assert.rejects(pollHologramJob('ABC',{pollMs:0,sleep:async()=>{},maxConsecutiveFailures:3,
   fetchImpl:async()=>{calls++;return json({},503);}}),e=>e.code==='poll-unavailable');
 assert.equal(calls,3);
});

test('Una entrada directa a HG no hereda la clave legacy ni el 2D',()=>{
 const entries=new Map();
 globalThis.sessionStorage={getItem:(key)=>entries.get(key)??null,setItem:(key,val)=>entries.set(key,val),removeItem:(key)=>entries.delete(key)};
 globalThis.localStorage={getItem:()=>{throw Error('Legacy global storage NO debe consultarse');}};
 assert.deepEqual(readHologramWorldContext(),{context:{},source:'new'});
 saveHologramWorldContext({intent:'solo_hg'});
 assert.deepEqual(readHologramWorldContext(),{context:{intent:'solo_hg'},source:'same-world'});
});

test('Transferencia explícita 2D -> HG se consume una sola vez, prioridad sobre propio mundo',()=>{
 const entries=new Map();
 globalThis.sessionStorage={getItem:(key)=>entries.get(key)??null,setItem:(key,val)=>entries.set(key,val),removeItem:(key)=>entries.delete(key)};
 sessionStorage.setItem('mia.world.hologram.session.v529',JSON.stringify({context:{department:'Cocina'}}));
 sessionStorage.setItem('mia.world.pending-handoff.v529',JSON.stringify({from:'2d',to:'hologram',at:Date.now(),context:{department:'Ventas'}}));
 assert.deepEqual(readHologramWorldContext(),{context:{department:'Ventas'},source:'world-switch'});
 assert.deepEqual(readHologramWorldContext(),{context:{department:'Cocina'},source:'same-world'});
});

test('No se consume transferencia expirada',()=>{
 const entries=new Map();
 globalThis.sessionStorage={getItem:(key)=>entries.get(key)??null,setItem:(key,val)=>entries.set(key,val),removeItem:(key)=>entries.delete(key)};
 sessionStorage.setItem('mia.world.pending-handoff.v529',JSON.stringify({from:'2d',to:'hologram',at:Date.now()-400000,context:{department:'Recepción'}}));
 assert.deepEqual(readHologramWorldContext(),{context:{},source:'new'});
 assert.equal(sessionStorage.getItem('mia.world.pending-handoff.v529'),null);
});

test('La consulta hola no reenvía filtro departamental al backend',async()=>{
 const payloads=[];
 await sendHologramVia2D({message:'Hola',contextState:createHologramApiContext({department:'Recepción',filter:{department:'Recepción'}}),
 fetchImpl:async(url,opts)=>{payloads.push(JSON.parse(opts.body));return json({answer:'Hola. ¿En qué puedo ayudarte?'})}});
 assert.equal(payloads.length,1);
 assert.equal(payloads[0].context.department,undefined);
 assert.equal(payloads[0].context.filter,undefined);
});


test('GET de seguimiento colgado agota plazo y no genera nuevos informes',async()=>{
 let calls=0;
 await assert.rejects(pollHologramJob('A',{maxConsecutiveFailures:1,requestTimeoutMs:25,
   fetchImpl:async(url,opts)=>{calls++;return new Promise(()=>{});}}),e=>e.code==='poll-unavailable');
 assert.equal(calls,1);
});

test('Navegar voluntariamente a portada prepara traspaso; descargar archivo no',()=>{
 const entries=new Map();
 globalThis.sessionStorage={getItem:(key)=>entries.get(key)??null,setItem:(key,val)=>entries.set(key,val),removeItem:(key)=>entries.delete(key)};
 globalThis.location={origin:'https://mia.local'};
 let onClick;
 const mockDocument={addEventListener:(_,callback)=>onClick=callback};
 bindHologramWorldNavigation(mockDocument,()=>({department:'Cocina'}));
 const click=(href,download='')=>onClick({target:{closest:()=>({href,download,target:''})},defaultPrevented:false});
 click('https://mia.local/api/reports/ABC','report.pdf');
 assert.equal(sessionStorage.getItem('mia.world.pending-handoff.v529'),null);
 click('https://mia.local/index.html');
 const record=JSON.parse(sessionStorage.getItem('mia.world.pending-handoff.v529'));
 assert.equal(record.from,'hologram');
 assert.equal(record.to,'any');
 assert.equal(record.context.department,'Cocina');
});
