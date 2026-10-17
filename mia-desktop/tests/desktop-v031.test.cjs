'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {sendPrompt}=require('../src/backend.cjs');
const {planPrompt}=require('../src/conversation.cjs');
function read(file){return fs.readFileSync(path.join(__dirname,'..',file),'utf8')}
test('sólo se reescribe referencia inequívoca a ficha de persona previamente identificada',()=>{
 assert.equal(planPrompt('Sí, es él, dame su ficha completa','Ángel García Franco').message,'Dame la ficha completa de Ángel García Franco.');
 assert.equal(planPrompt('Quiero el detalle de turnos','Ángel García Franco').message,'Quiero el detalle de turnos');
 assert.match(planPrompt('Sí, es él, dame la fecha','Ángel García Franco').clarification,/qué fecha/i);
 assert.equal(planPrompt('Sí, es él, dame su ficha completa',null).message,'Sí, es él, dame su ficha completa');
});
test('envía al backend sólo contexto conversacional devuelto por él, sin persistir fichas en disco',async()=>{
 const original=global.fetch;const session={backendContext:null,employeeSubject:null};const requests=[];
 global.fetch=async (_url,opt)=>{
  const msg=JSON.parse(opt.body);requests.push(msg);
  if(requests.length===1)return {ok:true,status:200,json:async()=>({answer:'Registro disponible',context:{session_id:'synthetic-123'},data:{empleado:{Nombre:'Ángel',Apellidos:'García Franco',Puesto:'Técnico'}}})};
  return {ok:true,status:200,json:async()=>({answer:'Ficha actualizada',data:{empleado:{Nombre:'Ángel',Apellidos:'García Franco',Puesto:'Técnico',Departamento:'Ejemplo'}}})};
 };
 try{
  const first=await sendPrompt('http://127.0.0.1:5001','Dame la ficha completa de Ángel García Franco',session);
  assert.equal(first.identitySelection,'PRIMARY_RECORD');
  assert.equal(session.employeeSubject,'Ángel García Franco');
  const second=await sendPrompt('http://127.0.0.1:5001','Sí, es él, dame su ficha completa',session);
  assert.equal(second.identitySelection,'PRIMARY_RECORD');
  assert.equal(requests[1].message,'Dame la ficha completa de Ángel García Franco.');
  assert.equal(requests[1].context.session_id,'synthetic-123');
  assert(!JSON.stringify(session).includes('Técnico'));
 }finally{global.fetch=original;}
});
test('no conserva identidad anterior si se consulta explícitamente a otra persona',async()=>{
 const original=global.fetch;const session={backendContext:{person:'synth-a'},employeeSubject:'Ángel García Franco'};
 let received;
 global.fetch=async (_url,opt)=>{received=JSON.parse(opt.body);return {ok:true,status:200,json:async()=>({answer:'No hay coincidencia'})}};
 try{
  const r=await sendPrompt('http://127.0.0.1:5001','Ficha de Sandra Asencio',session);
  assert.equal(r.identityCode,'IDENTITY_NOT_VERIFIED');
  assert.equal(session.employeeSubject,null);
  assert.equal(received.context.person,undefined);
 }finally{global.fetch=original;}
});
test('respuestas ambiguas o datos de terceras personas siguen bloqueadas',async()=>{
 const original=global.fetch;
 global.fetch=async()=>({ok:true,status:200,json:async()=>({answer:'3 candidatos',data:{table:{rows:[{Empleado:'Ángel García Franco'},{Empleado:'Ángel García Franco'},{Empleado:'Empleado Sintético'}]}}})});
 try{const r=await sendPrompt('http://127.0.0.1:5001','Ficha de Ángel García Franco',{backendContext:null,employeeSubject:null});assert.equal(r.identityCode,'AMBIGUOUS_EMPLOYEE');}
 finally{global.fetch=original;}
});
test('comandos corteses: una sola telemetría y confirmación para cerrar',()=>{
 const main=read('src/main.cjs'),avatar=read('src/ui/avatar.js'),voice=read('src/voice.cjs');
 assert.match(main,/performCeremony\('JOY_GREET'/);
 assert.match(main,/performCeremony\('FAREWELL'/);
 assert.match(main,/dialog\.showMessageBox/);
 assert.match(main,/mia:ceremony-finished/);
 assert.match(avatar,/JOY_GREET:'SEQ_BIENVENIDA'/);
 assert.match(avatar,/FAREWELL:'SEQ_DESPEDIDA'/);
 assert.match(avatar,/onAvatarCeremony/);
 assert.doesNotMatch(main,/diagnostics\.record\('voice_command',\{mode:'wake',code:command\}\)/);
 assert.match(voice,/diagnostics\.record\('voice_command'/);
 assert.doesNotMatch(voice,/function releaseIdle\(\)\{if\(!desiredWake&&!pendingDictation\)shutdown\(\);\}/);
});
test('Employee360 auténtico: extrae KPIs y ficha por identidad inequívoca',async()=>{
 const original=global.fetch;
 global.fetch=async()=>({ok:true,status:200,json:async()=>({
  answer:'Ficha 360',data:{employee360:{empleado:{Nombre:'Ángel García Franco',Puesto:'Ejemplo'},datos_laborales:{Situacion:'Activo'}},presentation:{
   schema:'mia.employee360.presentation',hero:{title:'Ángel García Franco'},kpis:[{label:'Turno hoy',value:'Tarde'}],sections:[{id:'employment',title:'Situación laboral',data:{Puesto:'Ejemplo'}}]
  }}
 })});
 try{
  const r=await sendPrompt('http://127.0.0.1:5001','Dame la ficha completa de Ángel García Franco',{backendContext:null,employeeSubject:null});
  assert.equal(r.identitySelection,'EMPLOYEE360_VERIFIED');
  assert.equal(r.presentation.cards[0].value,'Tarde');
  assert.equal(r.presentation.tables[0].rows[0].Valor,'Ángel García Franco');
  assert.equal(r.presentation.tables[0].complete,false);
 }finally{global.fetch=original;}
});
test('Employee360 de otra persona no se muestra aunque tenga secciones',async()=>{
 const original=global.fetch;
 global.fetch=async()=>({ok:true,status:200,json:async()=>({data:{presentation:{schema:'mia.employee360.presentation',hero:{title:'Persona Distinta'},kpis:[{label:'Dato personal',value:99}]}}})});
 try{const r=await sendPrompt('http://127.0.0.1:5001','Dame la ficha completa de Ángel García Franco');assert.equal(r.identityCode,'EMPLOYEE360_IDENTITY_MISMATCH');assert(!r.presentation);}
 finally{global.fetch=original;}
});
