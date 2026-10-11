import test from 'node:test';
import assert from 'node:assert/strict';
import { hasPresentationData, presentationType, PAGE_SIZE } from '../src/core/premium-tables.js';
import { renderHologramBrief } from '../src/core/hologram-brief.js';
import { MiaBehaviorV4 } from '../src/core/behavior-v4.js';
import { renderPresentation } from '../src/core/present.js';
import { trackMatchesMask } from '../src/core/animations.js';

test('No card/window for natural conversation', () => {
  assert.equal(hasPresentationData([]), false);
  assert.equal(hasPresentationData([{ type: 'text', text: 'Hola' }]), false);
  assert.equal(hasPresentationData([{ type: 'table', rows: [], columns: ['Nombre'] }]), false);
  assert.equal(hasPresentationData([{ type: 'message', text: 'Buenos días' }]), false);
});

test('Real structured data produces a presentation', () => {
  assert.equal(hasPresentationData([{ type: 'table', rows: [['Ana', 10]], columns: ['Nombre','Total'] }]), true);
  assert.equal(hasPresentationData([{ type: 'dashboard', kpis: { total: 0 } }]), true);
  assert.equal(hasPresentationData([{ type: 'download', url: '/api/reports/123' }]), true);
  assert.equal(hasPresentationData([{ type: 'person', data: { employee360: { name: 'Ana' } } }]), true);
  assert.equal(presentationType([{ type: 'report', title: 'Informe de turnos' }]), 'document');
  assert.equal(presentationType([{ type: 'comparison', title: 'Comparativa de costes' }]), 'comparison');
  assert.equal(PAGE_SIZE, 20);
});

test('Hologram is brief; does not dump full 200-row tables', () => {
  const source = [{ type:'dashboard', title:'Operativa', kpis:{ empleados:42, vacaciones:3 }, tables:[{title:'Turnos',columns:['Nombre','Estado'],rows:Array.from({length:200},(_,i)=>[`Fila${i}`,'Trabajo'])}] }];
  const html = renderHologramBrief(source, {type:'analytics'});
  assert.match(html, /42/);
  assert.match(html, /200 registros/);
  assert.match(html, /Fila4/);
  assert.doesNotMatch(html, /Fila5/);
  assert.doesNotMatch(html, /Fila199/);
});

test('Hologram sanitizes markup in data', () => {
  const html = renderHologramBrief([{type:'table',title:'<script>',columns:['A'],rows:[['<img src=x onerror=alert(1)>']]}]);
  assert.doesNotMatch(html, /<script>|<img /);
  assert.match(html, /&lt;script&gt;/);
});

test('V4 behavior plays exported composite clips according to context', () => {
  let id = 0;
  globalThis.window = {
    matchMedia: () => ({matches:true}),
    setTimeout: () => ++id,
    clearTimeout: () => {},
  };
  const names = ['mIA_IDLE', 'mIA_SEQ_BIENVENIDA', 'mIA_SEQ_CONSULTANDO_DATOS',
    'mIA_THINK', 'mIA_SEQ_PRESENTAR_KPI', 'mIA_SEQ_COMPARAR_DATOS',
    'mIA_SEQ_EXPLICAR_DIAGRAMA', 'mIA_SEQ_DESPEDIDA', 'mIA_TALK'];
  const played=[];
  const scene={actions:new Map(names.map(n=>[n,{}])),play:(...args)=>played.push(args),stopGesture:()=>{},clipDuration:()=>5};
  const behavior=new MiaBehaviorV4({scene});
  behavior.enter('greeting');
  assert.equal(played.at(-1)[0],'mIA_SEQ_BIENVENIDA');
  behavior.enter('presenting',{presentationType:'analytics'});
  assert.equal(played.at(-1)[0],'mIA_SEQ_PRESENTAR_KPI');
  behavior.enter('presenting',{presentationType:'comparison'});
  assert.equal(played.at(-1)[0],'mIA_SEQ_COMPARAR_DATOS');
  behavior.enter('presenting',{presentationType:'document'});
  assert.equal(played.at(-1)[0],'mIA_SEQ_EXPLICAR_DIAGRAMA');
  behavior.enter('farewell');
  assert.equal(played.at(-1)[0],'mIA_SEQ_DESPEDIDA');
  behavior.destroy();
});


test('Full backend tables are NOT truncated at 100; mixed rows supported', () => {
  const html = renderPresentation({ type:'table', columns:['Nombre', 'Total'], rows:Array.from({length:123},(_,i)=>({Nombre:`Empleado ${i+1}`,Total:i+1})) });
  assert.match(html, /Empleado 123/);
  assert.match(html, /Empleado 1/);
  assert.doesNotMatch(html, /Mostrando 100/);
});

test('Links reject JavaScript URLs and escape user strings', () => {
  assert.equal(renderPresentation({type:'download',url:'javascript:alert(1)',title:'Malicioso'}).includes('javascript:'), false);
  assert.match(renderPresentation({type:'document',url:'https://example.org/data.pdf',title:'Informe'}), /example.org/);
});

test('SmartRig animation masks recognize V4 bone naming', () => {
  assert.equal(trackMatchesMask('smartrig:LeftArm.quaternion', 'upper'), true);
  assert.equal(trackMatchesMask('smartrig:RightForeArm.position', 'upper'), true);
  assert.equal(trackMatchesMask('smartrig:LeftLeg.quaternion', 'upper'), false);
});
