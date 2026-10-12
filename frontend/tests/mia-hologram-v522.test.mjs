import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { sendHologramTurn, HologramTurnError, parseSSEMessages } from '../src/worlds/hologram/hologram-turn-v522.js';
import { hologramExecutiveCopy, isWorkingNowQuestion, confirmedWorkforceTotal, compactVoice } from '../src/worlds/hologram/hologram-executive-v522.js';
import { HologramVoiceV522 } from '../src/worlds/hologram/hologram-voice-v522.js';

const encoder = new TextEncoder();
const sse = (type, data) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
const makeClient = () => ({apiBase:'',sessionId:null,persistSession:false,events:[],_emit(type,payload){this.events.push([type,payload]);},_handle(event){this.events.push([event.type,event.data]);if(event.type==='session')this.sessionId=event.data.session_id;}});
const stream = (chunks, {hang=false}={}) => new ReadableStream({
  start(controller){ for(const c of chunks) controller.enqueue(encoder.encode(c)); if(!hang)controller.close(); },
  cancel(){this.cancelled=true;}
});
const fakeFetch = (readable) => async () => ({ok:true,status:200,body:readable});

test('SSE reconstruye bloques fraccionados y maneja eventos múltiples', () => {
  const chunks = ['event: sess','ion\r\ndata: {"session_id":"abc"}\r\n\r\n','event: result\ndata: {"result":{"answer":"Listo"}}\n\n'];
  const list = parseSSEMessages(chunks);
  assert.equal(list[0].data.session_id,'abc');
  assert.equal(list[1].data.result.answer,'Listo');
});

test('Se entrega el primer result aunque el servidor deje el stream abierto', async () => {
  const client=makeClient();
  const reader=stream([sse('session',{session_id:'session-1'}),sse('progress',{message:'Consultando'}),sse('result',{result:{answer:'Hay 18 personas trabajando',presentations:[]}})],{hang:true});
  const started=Date.now();
  const result=await sendHologramTurn({client,message:'¿Quién trabaja ahora?',fetchImpl:fakeFetch(reader),timeoutMs:5000,inactivityMs:5000});
  assert.equal(result.answer,'Hay 18 personas trabajando');
  assert.equal(client.sessionId,'session-1');
  assert.ok(Date.now()-started<1000);
  assert.ok(client.events.some(([name])=>name==='progress'));
});

test('SSE entrega contenido final aunque el servidor cierre sin separador', async () => {
  const client=makeClient();
  const chunks=[sse('session',{session_id:'s2'}),'event: result\ndata: {"result":{"answer":"Confirmado"}}'];
  const result=await sendHologramTurn({client,message:'hola',fetchImpl:fakeFetch(stream(chunks))});
  assert.equal(result.answer,'Confirmado');
});

test('Una consulta sin resultado final no se queda en bucle', async () => {
  const client=makeClient();
  await assert.rejects(sendHologramTurn({client,message:'hola',fetchImpl:fakeFetch(stream([sse('progress',{message:'trabajando'})]))}),
    err=>err.code==='missing-result');
});

test('Una consulta colgada termina con timeout explícito', async () => {
  const client=makeClient();
  const stuckFetch=async (_url,{signal})=>new Promise((resolve,reject)=>{
    signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true});
  });
  const at=Date.now();
  await assert.rejects(sendHologramTurn({client,message:'personal ahora',fetchImpl:stuckFetch,timeoutMs:150,inactivityMs:5000}),
    err=>err instanceof HologramTurnError && err.code==='timeout');
  assert.ok(Date.now()-at<1300);
});

test('Una conexión muda termina con plazo de inactividad', async () => {
  const client=makeClient();
  const read=new ReadableStream({start(){}});
  await assert.rejects(sendHologramTurn({client,message:'personal ahora',fetchImpl:(_u,{signal}) => new Promise((resolve,reject)=>{
    // Una respuesta cuya lectura no acabará; el abort debe rechazar reader.read
    // en navegadores reales. Este mock solo prueba abort del fetch.
    signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true});
  }),timeoutMs:1000,inactivityMs:130}),err=>err.code==='inactivity');
});

test('No confunde recuento de filas con total de empleados trabajando', () => {
  const presentations=[{type:'table',columns:['Empleado','Departamento'],rows:[['Ana','Cocina'],['Luis','Restaurante']]}];
  assert.equal(confirmedWorkforceTotal({},presentations),null);
  const result=hologramExecutiveCopy({question:'¿Quién está trabajando ahora mismo?',response:{answer:'Estos son los resultados.'},presentations,counts:{rows:2}});
  assert.equal(result.confirmed,false);
  assert.match(result.caption,/2 registros recibidos/);
  assert.match(result.speech,/No puedo confirmar/);
});

test('Métrica declarada sí permite mostrar total confirmado', () => {
  const presentations=[{kpis:[{label:'Personal trabajando ahora',value:27}],tables:[]}];
  assert.equal(confirmedWorkforceTotal({},presentations),27);
  const copy=hologramExecutiveCopy({question:'¿Cuántos empleados trabajan ahora?',response:{answer:'Datos.'},presentations});
  assert.equal(copy.confirmed,true);
  assert.match(copy.speech,/27 personas trabajando/);
});

test('No convierte activos, vacaciones o descansos en personal trabajando', () => {
  const presentations=[{kpis:[{label:'Empleados activos',value:200},{label:'Personal no trabajando',value:16},{label:'De vacaciones',value:9}]}];
  assert.equal(confirmedWorkforceTotal({},presentations),null);
});

test('Interpreta la intención temporal sin aplicar totales falsos a ayer', () => {
  assert.equal(isWorkingNowQuestion('¿Quién está trabajando ahora mismo?'),true);
  assert.equal(isWorkingNowQuestion('¿Quién trabajó ayer?'),false);
  assert.equal(isWorkingNowQuestion('¿Cuántos empleados trabajan hoy?'),true);
});

test('Un resumen hablado evita leer informes enteros', () => {
  const answer='Primera frase de resultado. Segunda frase útil. '.repeat(30);
  const short=compactVoice(answer,150);
  assert.ok(short.length<=150);
  assert.ok(short.endsWith('.'));
});

test('La voz tiene timeout; no mantiene un audio en espera indefinida', async () => {
  // El fetch de voz ignora completamente el tiempo, el controlador lo aborta.
  let aborted=false;
  const voice=new HologramVoiceV522({fetchImpl:(_url,{signal})=>new Promise((_resolve,reject)=>{
    signal.addEventListener('abort',()=>{aborted=true;reject(Error('abort'))},{once:true});
  }),maxMs:140,fetchTimeoutMs:1000,speechSynthesis:null});
  const result=await voice.speak('Resumen en voz');
  assert.equal(result.status,'voice-timeout');
  assert.equal(aborted,true);
});

test('La V5.2.2 conserva bienvenida con botón y micrófono de tres estados', async () => {
  const main=await readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  for (const value of ['new MiaVoiceV4','voice?.cycle()','welcomeVoice.replay','boot.complete({','new MiaHologramDirectorV52','adaptHologramResult','sendHologramTurn','hologramExecutiveCopy','hologramVoice.speak']) {
    assert.ok(main.includes(value),`Falta ${value}`);
  }
  assert.ok(!main.includes('await client.send(question)'));
  assert.ok(!main.includes('await client.speak('));
});
