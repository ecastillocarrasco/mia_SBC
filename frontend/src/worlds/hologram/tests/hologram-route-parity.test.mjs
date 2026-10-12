import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sendHologramVia2D,createHologramApiContext,normalizeHologramApiResult } from '../hologram-api-v525.js';
import { createHologramReplyIntegrity } from '../hologram-integrity-v526.js';
import { hologramExecutiveCopy } from '../hologram-executive-v522.js';

const okJSON = (value) => new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});

test('Consulta laboral y social pasan por el mismo gateway LLM que el 2D',async()=>{
  for (const q of ['¿Cuántos empleados están trabajando ahora?', 'hola', '¿Qué hora es?']) {
    const calls=[];
    const result = await sendHologramVia2D({
      message:q,
      contextState:createHologramApiContext({department:'Restaurante'}),
      replyIntegrity:createHologramReplyIntegrity(),
      fetchImpl:async(url,opts)=>{
        calls.push({url,payload:JSON.parse(opts.body)});
        return okJSON({answer:`Respuesta de backend: ${q}`,context:{source:'real'}});
      }
    });
    assert.equal(calls.length,1);
    assert.equal(calls[0].url,'/api/mia/v4/chat');
    assert.equal(calls[0].payload.message,q);
    assert.equal(calls[0].payload.context.company,'Sunset Beach Club');
    assert.equal(calls[0].payload.context.department, q === 'hola' ? undefined : 'Restaurante');
    assert.equal(result.answer,`Respuesta de backend: ${q}`);
  }
});

test('Mismo orden de respaldo LLM -> backend NDJSON; preserva datos',async()=>{
  const called=[];
  const payload={type:'result',payload:{answer:'Resultado operativo',data:{rows:[{departamento:'Cocina',total:2}],columns:['departamento','total']}}};
  const result=await sendHologramVia2D({message:'Comparativa por departamento',fetchImpl:async(url)=>{
    called.push(url);
    if (called.length===1) return new Response('bad',{status:503});
    return new Response(JSON.stringify(payload)+'\n',{status:200,headers:{'Content-Type':'application/x-ndjson'}});
  }});
  assert.deepEqual(called,['/api/mia/v4/chat','/api/mia/chat/stream']);
  assert.equal(result.answer,'Resultado operativo');
  assert.ok(result.presentations.some(p=>p.rows?.[0]?.departamento==='Cocina'));
});

test('Si LLM y stream fallan, llega al JSON backend',async()=>{
  const called=[];
  const result=await sendHologramVia2D({message:'Turnos',fetchImpl:async(url)=>{
    called.push(url);
    if (called.length<3) return new Response('bad',{status:502});
    return okJSON({natural_answer:'Turnos recuperados'});
  }});
  assert.deepEqual(called,['/api/mia/v4/chat','/api/mia/chat/stream','/api/mia/chat']);
  assert.equal(result.answer,'Turnos recuperados');
});

test('Dos preguntas distintas con misma respuesta no causan rechazo espurio',async()=>{
  const integrity=createHologramReplyIntegrity();
  const options={fetchImpl:async()=>okJSON({answer:'No hay datos suficientes para responder esta solicitud.'}),replyIntegrity:integrity};
  await sendHologramVia2D({message:'Consulta X',...options});
  const result=await sendHologramVia2D({message:'Consulta Y',...options});
  assert.equal(result.answer,'No hay datos suficientes para responder esta solicitud.');
});

test('Eco del servidor con otra pregunta se rechaza y activa respaldo',async()=>{
  const routes=[];
  const result=await sendHologramVia2D({message:'Consulta verdadera',replyIntegrity:createHologramReplyIntegrity(),
    fetchImpl:async(url)=>{
      routes.push(url);
      if (routes.length===1) return okJSON({answer:'Dato antiguo',request:{message:'Consulta distinta'}});
      return new Response(JSON.stringify({type:'result',payload:{answer:'Dato correcto'}})+'\n');
    }});
  assert.equal(routes.length,2);
  assert.equal(result.answer,'Dato correcto');
});

test('Los resúmenes no convierten tarjetas en recuentos de plantilla',()=>{
  const copy=hologramExecutiveCopy({question:'¿Cuántos trabajan ahora?',response:{speech_text:'He consultado los turnos y estos son los datos disponibles.'},presentations:[{kpis:[{label:'Trabajando ahora',value:38}]}]});
  assert.equal(copy.speech,'He consultado los turnos y estos son los datos disponibles.');
  assert.equal(copy.confirmed,false);
});

test('Normalización mantiene filas y contextos extra del backend',()=>{
 const result=normalizeHologramApiResult({response:'Listo',data:{rows:[{mes:'enero',total:30}],columns:['mes','total'],cards:[{label:'Total',value:30}]}});
 assert.equal(result.answer,'Listo');
 assert.ok(result.presentations.some(p=>Array.isArray(p.rows)));
 assert.ok(result.presentations.some(p=>Array.isArray(p.cards)));
});
