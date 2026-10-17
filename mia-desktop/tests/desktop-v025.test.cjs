'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {VisibilityGate}=require('../src/visibility.cjs');
const {normalizeConfig}=require('../src/config.cjs');
const {requestedEmployee,verifyEmployeeReply}=require('../src/identity.cjs');
const {sendPrompt}=require('../src/backend.cjs');

test('minimizar impide nuevos auto-show mientras carga la ventana',()=>{
  const x=new VisibilityGate();assert.equal(x.canAutoShow(),true);
  x.hide(1000);assert.equal(x.canAutoShow(),false);
  assert.equal(x.acceptVoiceShow(1400),false);
  assert.equal(x.acceptVoiceShow(2301),true);
  assert.equal(x.canAutoShow(),false);
  x.show();assert.equal(x.canAutoShow(),true);
});
test('modos de micrófono configurables, off no habilita escucha por si solo',()=>{
  assert.equal(normalizeConfig().voiceMode,'once');
  for(const voiceMode of ['off','once','conversation'])assert.equal(normalizeConfig({voiceMode}).voiceMode,voiceMode);
  assert.equal(normalizeConfig({voiceMode:'malicioso'}).voiceMode,'once');
});
test('tres frases personalizables y maliciosas descartadas',()=>{
  const x=normalizeConfig({wakePhrase:'Hola Mía',hidePhrase:'Escóndete Mía',exitPhrase:'Adiós Mía'});
  assert.equal(x.hidePhrase,'Escóndete Mía');assert.equal(x.exitPhrase,'Adiós Mía');
  assert.equal(normalizeConfig({exitPhrase:'&& shutdown'}).exitPhrase,'Cierra mIA');
});
test('detecta ficha de empleado singular, no listado general',()=>{
  assert.equal(requestedEmployee('Muéstrame la ficha de Marta García'),'Marta García');
  assert.equal(requestedEmployee('Quiero la ficha del empleado Marta García'),'Marta García');
  assert.equal(requestedEmployee('Dime la ficha de todos los empleados'),null);
  assert.equal(requestedEmployee('Muéstrame todos los empleados y sus puestos'),null);
});
test('elige una sola coincidencia de un listado, sin mezclar otras identidades',()=>{
  const {resolveEmployeeReply,selectedEmployeePresentation}=require('../src/identity.cjs');
  const query='ficha completa Sandra Asencio';
  const mixed={data:{table:{rows:[{Empleado:'Lucía Torres',Puesto:'Cocina'},{Empleado:'Sandra Asencio',Puesto:'Recepción'},{Empleado:'Carlos Vega',Puesto:'Bar'}]}}};
  const checked=resolveEmployeeReply(query,mixed);
  assert.equal(checked.ok,true);
  assert.equal(checked.selection,'MATCHED_LIST_ROW');
  const p=selectedEmployeePresentation(checked);
  assert.equal(p.tables.length,1);
  assert.equal(p.tables[0].rows.length,1);
  assert.equal(p.tables[0].rows[0].Empleado,'Sandra Asencio');
  assert(!JSON.stringify(p).includes('Lucía Torres'));
  assert(!JSON.stringify(p).includes('Carlos Vega'));
  assert.equal(p.tables[0].complete,false);
  assert.equal(verifyEmployeeReply(query,{answer:'Sin registro'}).code,'IDENTITY_NOT_VERIFIED');
  assert.equal(verifyEmployeeReply('Ficha de Sandra',{data:{table:{rows:[{Empleado:'Sandra Asencio'}]}}}).code,'FULL_NAME_REQUIRED');
});
test('no muestra otra persona ni acepta dos coincidencias ambiguas',()=>{
  assert.equal(verifyEmployeeReply('ficha completa Sandra Asencio',{data:{table:{rows:[{Empleado:'Carlos Vega'}]}}}).code,'IDENTITY_MISMATCH');
  assert.equal(verifyEmployeeReply('ficha completa Sandra Asencio',{data:{table:{rows:[{Empleado:'Sandra Asencio López'},{Empleado:'Sandra María Asencio'}]}}}).code,'AMBIGUOUS_EMPLOYEE');
});
test('si existe una ficha principal única ignora tablas auxiliares con otros nombres',()=>{
  const {resolveEmployeeReply,selectedEmployeePresentation}=require('../src/identity.cjs');
  const raw={data:{empleado:{Nombre:'Sandra',Apellidos:'Asencio',Puesto:'Recepción'},table:{rows:[{Empleado:'Carlos Vega',Puesto:'Bar'}]}}};
  const x=resolveEmployeeReply('Ficha completa Sandra Asencio',raw);
  assert.equal(x.ok,true);assert.equal(x.selection,'PRIMARY_RECORD');
  assert(!JSON.stringify(selectedEmployeePresentation(x)).includes('Carlos Vega'));
});
test('el backend devuelve únicamente registro comprobado y no reutiliza narrativa con otros nombres',async()=>{
  const original=global.fetch;
  global.fetch=async()=>({ok:true,status:200,json:async()=>({answer:'También aparecen Carlos Vega y Lucía Torres',speech_text:'Carlos Vega',data:{table:{rows:[{Empleado:'Sandra Asencio',Puesto:'Recepción'},{Empleado:'Carlos Vega'}]}}})});
  try{
    const r=await sendPrompt('http://127.0.0.1:5001','ficha completa Sandra Asencio');
    assert.equal(r.presentation.tables[0].rows.length,1);
    assert.equal(r.presentation.tables[0].rows[0].Empleado,'Sandra Asencio');
    assert(!JSON.stringify(r).includes('Carlos Vega'));
    assert(!JSON.stringify(r).includes('Lucía Torres'));
    assert.match(r.answer,/no puedo afirmar que sea la ficha completa/i);
    assert.equal(r.presentation.tables[0].complete,false);
  }finally{global.fetch=original;}
});
test('voice worker escucha tres órdenes y tiene ventanas de silencio más cortas',()=>{
  const ps=fs.readFileSync(path.join(__dirname,'../src/voice/windows-speech.ps1'),'utf8');
  assert.match(ps,/Emit 'COMMAND'/);assert.match(ps,/name='EXIT'/);assert.match(ps,/FromSeconds\(0\.8\)/);
});
test('pantalla incluye modo conversación y botón para detenerlo',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../src/ui/bubble.html'),'utf8');
  const config=fs.readFileSync(path.join(__dirname,'../src/ui/settings.html'),'utf8');
  assert.match(html,/id="stopConversation"/);
  assert.match(config,/value="conversation"/);
  assert.match(config,/id="exitPhrase"/);
});
test('el micrófono de comandos permanece disponible con el bocadillo abierto',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
  const part=source.match(/function openBubble\(options = \{\}\) \{([\s\S]*?)\n\}\nfunction openSettings/);
  assert(part,'No se encuentra openBubble');
  assert.match(part[1],/else if \(!wakeProcess && !microphoneInUse && !activePlaybackSenders\.size\) startWake\(\)/);
  assert.match(source,/if\(!wasHidden && bubbleWin\?\.isVisible\(\)\)return/);
});
test('las órdenes usan alternativas concretas de pronunciación y umbral estricto para cerrar',()=>{
  const code=fs.readFileSync(path.join(__dirname,'../src/voice/windows-speech.ps1'),'utf8');
  assert.match(code,/Oye Mía/);
  assert.match(code,/limit=0\.90/);
  assert.match(code,/FromSeconds\(0\.45\)/);
});
