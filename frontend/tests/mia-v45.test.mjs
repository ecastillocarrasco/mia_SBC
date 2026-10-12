import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolveWelcomeName, firstNameFromAccount, welcomeText, activeIdentity } from '../src/core/identity-v45.js';
import { MiaWelcomeVoiceV45 } from '../src/core/welcome-voice-v45.js';
import { render2DTableExtras, summarizeCoverage, presentationCoverageLabel } from '../src/core/presentation-parity-v45.js';
import { MiaBehaviorV4 } from '../src/core/behavior-v4.js';
import { friendlyProgress } from '../src/core/progress-language-v42.js';
import { waitMessage } from '../src/core/waiting-v4.js';
const code = (rel) => readFileSync(new URL('../'+rel, import.meta.url), 'utf8');

test('development greeting uses Enrique and NO last name', () => {
  assert.equal(resolveWelcomeName({development:true}), 'Enrique');
  assert.match(welcomeText({name:'Enrique'}), /^¡Hola Enrique!/);
  assert.doesNotMatch(welcomeText({name:'Enrique'}), /Carrasco|Castillo/);
});

test('MSAL given_name overrides dev fallback; no account in prod gives anonymous greeting', () => {
  const account={name:'María Pérez Rodríguez', username:'maria.perez@example.org', idTokenClaims:{given_name:'María', family_name:'Pérez'}};
  assert.equal(resolveWelcomeName({account, development:true}), 'María');
  assert.equal(firstNameFromAccount({name:'Juan Carlos Martínez'}), 'Juan');
  assert.equal(resolveWelcomeName({account:null,development:false}), '');
  assert.match(welcomeText(), /^¡Hola!/);
  assert.equal(activeIdentity({msalInstance:{getActiveAccount:()=>account}}), account);
  assert.equal(activeIdentity({msalInstance:{getActiveAccount:()=>null}}), null);
});

test('welcome voice requests TTS immediately and handles blocked autoplay', async () => {
  const calls=[];let blocked=0;
  globalThis.URL.createObjectURL = () => 'blob:fake';
  globalThis.URL.revokeObjectURL = (x) => calls.push(['revoke',x]);
  const player={pause(){calls.push(['pause']);},play(){calls.push(['play']);return Promise.reject(Object.assign(new Error('autoplay'),{name:'NotAllowedError'}));}};
  const welcome=new MiaWelcomeVoiceV45({fetchImpl:async (uri,options)=>{
    calls.push(['fetch',uri,JSON.parse(options.body).text]);return {ok:true,blob:async()=>new Blob(['data'])};
  }, audioFactory:()=>player, onBlocked:()=>{blocked++}});
  const state=await welcome.start('Hola Enrique');
  assert.equal(state.status,'blocked');
  assert.equal(calls.find(x=>x[0]==='fetch')?.[2],'Hola Enrique');
  assert.equal(blocked,1);
  welcome.cancel();
  assert.ok(calls.some(x=>x[0]==='revoke'));
});

test('welcome TTS is aborted when visitor submits a query, never starts stale audio', async () => {
  let abortObserved=false,playerCreated=false;
  const welcome=new MiaWelcomeVoiceV45({fetchImpl:(_uri,opt)=>new Promise((resolve,reject)=>{
    opt.signal.addEventListener('abort',()=>{abortObserved=true;reject(Object.assign(new Error('aborted'),{name:'AbortError'}));});
  }),audioFactory:()=>{playerCreated=true;return {play:()=>Promise.resolve(),pause(){}}}});
  const pending=welcome.start('Hola');
  welcome.cancel();
  assert.deepEqual(await pending,{status:'cancelled'});
  assert.equal(abortObserved,true);
  assert.equal(playerCreated,false);
});

test('3D renders all table metadata that 2D already shows', () => {
  const item={type:'table',title:'Personal trabajando', columns:['Empleado','Departamento'],rows:[['Ana','Restaurante'],['Luis','Cocina']],kpis:[{label:'Total',value:2}],charts:[{type:'bar',title:'Por departamento',labels:['Restaurante','Cocina'],series:[{name:'Personal',values:[1,1]}]}],stats:{type:'table',title:'Distribución', columns:['Área','Total'],rows:[['Restaurante',1],['Cocina',1]]}};
  const html=render2DTableExtras(item);
  assert.match(html,/Restaurante/);
  assert.match(html,/Cocina/);
  assert.match(html,/Total/);
  assert.match(html,/Distribución/);
  assert.equal(summarizeCoverage([item]).totalRows,2);
  assert.match(presentationCoverageLabel(summarizeCoverage([item])),/2 registros recibidos/);
  assert.match(code('src/worlds/3d/main.js'),/renderPresentation\(item\) \+ render2DTableExtras\(item\)/);
});

test('43 backend rows are kept: 20/20/3 in the common pager, none dropped at reception',()=>{
  const rows=Array.from({length:43},(_,i)=>[i+1, i%2?'Restaurante':'Cocina']);
  assert.equal(summarizeCoverage([{type:'table',rows}]).totalRows,43);
  const pager=code('src/core/premium-tables.js');
  assert.match(pager,/PAGE_SIZE = 20/);
  assert.match(pager,/rows\.slice\(page \* limit, \(page \+ 1\) \* limit\)/);
  assert.deepEqual([rows.slice(0,20).length,rows.slice(20,40).length,rows.slice(40,60).length],[20,20,3]);
});

test('POINT is layered over frontal idle instead of rotating full character', () => {
  const plays=[],gestures=[];
  const names=['mIA_IDLE_SAFE','mIA_POINT','mIA_SEQ_SENALAR_PANTALLA','mIA_SEQ_PRESENTAR_KPI','mIA_SEQ_COMPARAR_DATOS','mIA_TALK'];
  const scene={actions:new Map(names.map(x=>[x,true])),play:(name,options)=>plays.push({name,options}),playGesture:(name,opts)=>gestures.push({name,opts}),stopGesture(){},stopWaitOrbit(){},clipDuration(){return 4},isFrontFacingClip(){return true}};
  globalThis.window={setTimeout,clearTimeout,matchMedia:()=>({matches:false})};
  const b=new MiaBehaviorV4({scene});
  b.enter('presenting',{presentationType:'data'});
  assert.equal(plays.at(-1).name,'mIA_IDLE_SAFE');
  assert.equal(gestures.at(-1).name,'mIA_POINT');
  b.enter('presenting',{presentationType:'analytics'});
  assert.equal(plays.at(-1).name,'mIA_SEQ_PRESENTAR_KPI');
  b.destroy();
});

test('3D voice now starts on continue click; hologram retains load-time greeting',()=>{
  const world3d=code('src/worlds/3d/main.js');
  assert.match(world3d,/await boot\.complete\(\{ onContinue/);
  assert.match(world3d,/welcomeVoice\.replay\(greeting\)/);
  assert.match(world3d,/getWelcomeText\(/);
  assert.match(world3d,/welcomeVoice\.cancel\(\)/);
  const hg=code('src/worlds/hologram/main.js');
  assert.match(hg.slice(hg.indexOf('scene.load(')), /welcomeAutostart\.start\(welcomeMessage\)/);
});

test('technical status strings still show user-facing Spanish',()=>{
  assert.equal(friendlyProgress('analisis_financiero'),'Estamos tramitando tu solicitud.');
  assert.match(waitMessage(40),/tardando/i);
});

import { extractMarkdownTables, completePresentations } from '../src/core/answer-structure-v45.js';

test('3D recovers complete Markdown employee tables visible in 2D',()=>{
  const lines=['## Personal trabajando ahora','| Empleado | Departamento |','|---|---|'];
  for(let i=1;i<=43;i++)lines.push(`| Empleado ${i} | ${i%3===0?'Mantenimiento':i%2===0?'Restaurante':'Cocina'} |`);
  const markdown=lines.join('\n');
  const tables=extractMarkdownTables(markdown);
  assert.equal(tables.length,1);
  assert.equal(tables[0].rows.length,43);
  assert.equal(tables[0].rows[0][1],'Cocina');
  assert.equal(tables[0].rows.at(-1)[1],'Cocina');
  const all=completePresentations(markdown,[{type:'table',columns:['Empleado','Departamento'],rows:[['Empleado 99','Mantenimiento']]}]);
  assert.equal(all.length,2);
  assert.equal(summarizeCoverage(all).totalRows,44);
});

test('ordinary conversational greeting does not create a data panel',()=>{
  assert.deepEqual(extractMarkdownTables('Hola, ¿en qué puedo ayudarte?'),[]);
  assert.deepEqual(completePresentations('Hola, ¿en qué puedo ayudarte?',[]),[]);
});

test('Markdown table duplicate from an existing structured presentation is not repeated',()=>{
  const md='| Empleado | Departamento |\n|---|---|\n| Ana | Cocina |';
  const existing={type:'table',columns:['Empleado','Departamento'],rows:[['Ana','Cocina']]};
  assert.equal(completePresentations(md,[existing]).length,1);
});
