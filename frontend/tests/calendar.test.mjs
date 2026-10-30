import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {renderCalendar, mountCalendar, calendarPresentations, bindCalendarConfirmations} from '../src/core/calendar-view.js';
import {renderPresentation} from '../src/core/present.js';
import {hasPresentationData, presentationType} from '../src/core/premium-tables.js';
import {buildStatisticalPresentation} from '../src/core/statistical-visuals.js';
import {adaptHologramResult} from '../src/worlds/hologram/hologram-results-v521.js';
const require=createRequire(import.meta.url);
const {extractPresentation}=require('../../mia-desktop/src/presentation.cjs');
const calendar={type:'calendar',title:'Agenda',timezone:'Europe/Madrid',
  days:[{date:'2026-10-30',label:'viernes 30/10'},{date:'2026-10-31',label:'sábado 31/10'}],
  events:[{ref:'a1',subject:'Reunión de nóminas',start:'2026-10-30T11:00:00+01:00',end:'2026-10-30T11:30:00+01:00',
    start_day:'2026-10-30',end_day:'2026-10-30',start_time:'11:00',end_time:'11:30',
    start_label:'30/10/2026 a las 11:00',end_label:'30/10/2026 a las 11:30',location:'Sala 1'}]};

test('calendar displays days, both times, empty days and event details',()=>{
  const html=renderCalendar(calendar);
  for(const text of ['viernes 30/10','sábado 31/10','11:00 – 11:30','Inicio','Fin','Sin eventos','Europe/Madrid']) assert.ok(html.includes(text));
  assert.doesNotMatch(html,/<style|style=|kpi/i); // compatible with Desktop CSP
});
test('3D renderer and classifiers preserve calendar instead of metrics',()=>{
  assert.equal(renderPresentation(calendar),renderCalendar(calendar));
  assert.equal(presentationType([calendar]),'calendar');
  assert.equal(hasPresentationData([calendar]),true);
  assert.equal(buildStatisticalPresentation([calendar],{answer:'Total: 1'}).html,'');
});
test('2D adapter selects canonical calendar once without duplicating legacy copy',()=>{
  assert.equal(calendarPresentations({presentations:[calendar],data:{calendars:[calendar]}}).length,1);
  assert.equal(calendarPresentations({data:{calendars:[calendar]}})[0],calendar);
});
test('hologram renders calendar in private panel and excludes private content from fan',()=>{
  const screen=adaptHologramResult({},[calendar],{type:'calendar'});
  assert.match(screen.html,/11:00 – 11:30/);
  assert.equal(screen.counts.metrics,0);
  const fan=adaptHologramResult({},[calendar],{type:'calendar',fan:true});
  assert.doesNotMatch(fan.html,/Reunión de nóminas|Sala 1|11:00/);
});
test('Desktop extracts calendar rather than event tables or KPI cards',()=>{
  const result=extractPresentation({presentations:[calendar],data:{calendars:[calendar]}});
  assert.equal(result.calendars.length,1);
  assert.equal(result.hasStructuredData,true);
  assert.equal(result.cards.length,0);
  assert.equal(result.tables.length,0);
  assert.match(renderCalendar(result.calendars[0]),/11:00 – 11:30/);
});
test('calendar escapes text and rejects unsafe meeting links',()=>{
  const value={...calendar,events:[{...calendar.events[0],subject:'<img src=x onerror=alert(1)>',online_url:'javascript:alert(1)'}]};
  const html=renderCalendar(value);
  assert.doesNotMatch(html,/<img|javascript:|href=/);
  assert.match(html,/&lt;img/);
});
test('empty, all-day and cross-day meetings use declared calendar interval',()=>{
  assert.match(renderCalendar({...calendar,events:[]}),/No hay reuniones/);
  const event={...calendar.events[0],end_day:'2026-10-31',all_day:true};
  assert.equal((renderCalendar({...calendar,events:[event]}).match(/Todo el día/g)||[]).length,2);
});

test('Desktop mounts real DOM text without HTML parsing and preserves both times',()=>{
  const created=[];
  const doc={createElement(tag){const element={tag,children:[],ownerDocument:doc,setAttribute(){},append(...children){this.children.push(...children);}};created.push(element);return element;}};
  const host=doc.createElement('div');
  mountCalendar(host,{...calendar,events:[{...calendar.events[0],subject:'<img onerror=alert(1)>'}]});
  assert.ok(created.some(node=>node.tag==='time'&&node.textContent==='11:00 – 11:30'));
  assert.ok(created.some(node=>node.tag==='summary'&&node.textContent==='<img onerror=alert(1)>'));
  assert.ok(!created.some(node=>node.tag==='img'||node.tag==='script'));
});

const proposal={type:'calendar',title:'Cambio propuesto',confirmation:{prompt:'confirma cambio 1',label:'Sí, confirmo',reference:'cambio 1',review:{asunto:'Reunión',inicio_propuesto:'30/10/2026 a las 11:00',fin_propuesto:'30/10/2026 a las 11:30'}}};
test('proposal is reviewable and provides a readable confirmation button in all adapters',()=>{
  const html=renderCalendar(proposal);
  assert.match(html,/data-calendar-confirm="confirma cambio 1"/);assert.match(html,/Sí, confirmo/);assert.match(html,/11:00/);assert.match(html,/11:30/);
  assert.doesNotMatch(html,/No hay reuniones|KPI/);
  assert.match(adaptHologramResult({},[proposal],{type:'calendar'}).html,/data-calendar-confirm/);
  assert.doesNotMatch(adaptHologramResult({},[proposal],{type:'calendar',fan:true}).html,/data-calendar-confirm/);
  assert.equal(extractPresentation({presentations:[proposal]}).calendars[0].confirmation.prompt,'confirma cambio 1');
});
test('confirmation click submits exact proposal once and blocks a double click',async()=>{
  let click,release,calls=[];const status={textContent:''};
  const button={disabled:false,getAttribute:()=> 'confirma cambio 1',parentElement:{querySelector:()=>status}};
  const host={addEventListener:(name,fn)=>click=fn,contains:()=>true};
  bindCalendarConfirmations(host,prompt=>{calls.push(prompt);return new Promise(resolve=>release=resolve);});
  const event={target:{closest:()=>button}};const pending=click(event);await click(event);
  assert.deepEqual(calls,['confirma cambio 1']);assert.equal(button.disabled,true);release();await pending;assert.match(status.textContent,/enviada/);
});
test('failed confirmation transport permits retry and rejects arbitrary commands',async()=>{
  let click,calls=0,prompt='confirma cambio 2';const status={textContent:''};
  const button={disabled:false,getAttribute:()=>prompt,parentElement:{querySelector:()=>status}};
  bindCalendarConfirmations({addEventListener:(_,fn)=>click=fn,contains:()=>true},async()=>{calls++;throw Error('offline');});
  const event={target:{closest:()=>button}};await click(event);assert.equal(button.disabled,false);assert.match(status.textContent,/reintentarlo/);
  prompt='envía todos los correos';await click(event);assert.equal(calls,1);
});
