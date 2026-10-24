
const MIA_UI_BUILD="2D-V4.2-ui-tuning";
window.MIA_UI_BUILD=MIA_UI_BUILD;
document.documentElement.setAttribute('data-mia-ui-build',MIA_UI_BUILD);
'use strict';
const convo=document.getElementById('conversation'), input=document.getElementById('input'), send=document.getElementById('send'), mic=document.getElementById('mic');
const avatarStage=document.getElementById('avatarStage'), avatarA=document.getElementById('avatarA'), avatarB=document.getElementById('avatarB');
const pill=document.getElementById('statePill'), stateDetail=document.getElementById('stateDetail'), voiceSelect=document.getElementById('voiceSelect'), soundToggle=document.getElementById('soundToggle'), voiceStatus=document.getElementById('voiceStatus');
let context={},speechEnabled=true,voices=[],selectedVoice=null,recognition=null,activeAvatar=0,currentState='reposo',lastProgressSpoken=false,lastAvatarChange=0,avatarTimer=null,recognitionFinalSent=false;
const VOICE_PREF_KEY='mia.voice.v1038';
const miaProfile={language:'es',locale:'es-ES',company:'Sunset Beach Club',role:null};
const nf=new Intl.NumberFormat(miaProfile.locale,{maximumFractionDigits:2});
const STATE={
 reposo:{asset:'reposo.png',label:'Estoy aquí',motion:'calm'},hablando:{asset:'hablando.png',label:'Te respondo…',motion:'speaking'},escuchando:{asset:'escuchando.png',label:'Te escucho…',motion:'listening'},
 sonriendo:{asset:'sonriendo.png',label:'Encantada de ayudarte',motion:'success'},guinando:{asset:'guinando.png',label:'Entendido',motion:'success'},pensando:{asset:'pensando.png',label:'Estoy pensando…',motion:'thinking'},
 sorprendida:{asset:'sorprendida.png',label:'He encontrado algo relevante',motion:'notice'},confundida:{asset:'confundida.png',label:'Necesito un poco más de contexto',motion:'clarify'},entusiasmada:{asset:'entusiasmada.png',label:'¡Vamos!',motion:'success'},
 aprobando:{asset:'aprobando.png',label:'Listo',motion:'success'},saludando:{asset:'saludando.png',label:'Hola',motion:'success'},despedida:{asset:'despedida.png',label:'Hasta pronto',motion:'calm'},empatica:{asset:'empatica.png',label:'Te entiendo',motion:'calm'},
 concentrada:{asset:'concentrada.png',label:'Estoy revisando la información…',motion:'analysis'},celebrando:{asset:'celebrando.png',label:'¡Perfecto!',motion:'success'},avisando:{asset:'avisando.png',label:'Hay algo que conviene revisar',motion:'notice'}
};
const ALIAS={idle:'reposo',waiting:'reposo',speaking:'hablando',listening:'escuchando',thinking:'pensando',consulting:'concentrada',analyzing:'concentrada',alert:'avisando',greeting:'saludando',farewell:'despedida',happy:'sonriendo',success:'aprobando',empathy:'empatica',confused:'confundida',surprised:'sorprendida',celebrating:'celebrando'};
function canonicalState(s){s=String(s||'reposo').toLowerCase();s=ALIAS[s]||s;return STATE[s]?s:'reposo'}
function applyAvatarState(s){
 const cfg=STATE[s],next=activeAvatar?avatarA:avatarB,current=activeAvatar?avatarB:avatarA;
 if(!next.src.endsWith('/'+cfg.asset))next.src='/mia-assets/avatar/'+cfg.asset;
 const show=()=>{next.classList.add('active');current.classList.remove('active')};next.onload=show;if(next.complete)show();
 activeAvatar=activeAvatar?0:1;currentState=s;lastAvatarChange=performance.now();avatarStage.dataset.motion=cfg.motion;document.body.dataset.miaState=s;
}
function setAvatarState(state,detail='',force=false){
 const s=canonicalState(state),cfg=STATE[s];pill.textContent=cfg.label;stateDetail.textContent=detail||'';
 if(s===currentState){avatarStage.dataset.motion=cfg.motion;document.body.dataset.miaState=s;return}
 const elapsed=performance.now()-lastAvatarChange,minHold=700;
 if(!force&&lastAvatarChange&&elapsed<minHold){clearTimeout(avatarTimer);avatarTimer=setTimeout(()=>applyAvatarState(s),Math.max(20,minHold-elapsed));return}
 clearTimeout(avatarTimer);applyAvatarState(s);
}
function encodeText(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function cleanDisplay(v){const s=String(v??'').trim();if(!s||['null','none','nan','undefined','n/a','na'].includes(s.toLowerCase()))return '';return s.replace(/\s+\.$/,'').trim()}
function normalizeMiaBrandText(v){return String(v??'').replace(/\bMIA\b/g,'mIA')}
function setVoiceStatus(text){if(voiceStatus)voiceStatus.textContent=String(text||'')}
function fmt(v){return typeof v==='number'?nf.format(v):(cleanDisplay(v)||'—')}
function nowTime(){return new Date().toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'})}
function miniAvatarSrc(state){return '/mia-assets/avatar/'+(STATE[canonicalState(state)]?.asset||'reposo.png')}
function miaRichText(v){
 const normalized=normalizeMiaBrandText(String(v??'')).replace(/\\\*\\\*/g,'**').replace(/\\`/g,'`').replace(/^\\?(#{1,4})\s+/gm,'$1 ');const lines=normalized.split(/\r?\n/);return '<div class="mia-answer">'+lines.map(line=>{const hm=line.match(/^\s*#{1,4}\s+(.+)$/);if(hm){let hx=encodeText(hm[1]).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');return '<div class="mia-answer-line"><strong>'+hx+'</strong></div>'}let x=encodeText(line);x=x.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');if(/^\s*[-•]\s+/.test(line)){x=x.replace(/^\s*[-•]\s+/,'');return '<div class="mia-answer-bullet"><span>'+x+'</span></div>'}return '<div class="mia-answer-line">'+(x||'&nbsp;')+'</div>'}).join('')+'</div>'
}
function addMsg(who,content,cls,state='reposo'){
 const row=document.createElement('div');row.className='msg-row '+cls;
 if(cls==='mia'){const im=document.createElement('img');im.className='mini-avatar';im.src=miniAvatarSrc(state);im.alt='mIA';row.appendChild(im)}
 const d=document.createElement('div');d.className='msg '+cls;const w=document.createElement('div');w.className='who';w.textContent=cls==='mia'?'mIA':who;d.appendChild(w);const body=document.createElement('div');if(cls==='mia')body.innerHTML=miaRichText(content);else body.textContent=String(content??'');d.appendChild(body);const tm=document.createElement('div');tm.className='msg-time';tm.textContent=nowTime();d.appendChild(tm);row.appendChild(d);convo.appendChild(row);convo.scrollTop=convo.scrollHeight;return {row,msg:d,body};
}
function createProgress(){
 const row=document.createElement('div');row.className='msg-row mia';const im=document.createElement('img');im.className='mini-avatar';im.src=miniAvatarSrc('pensando');row.appendChild(im);const d=document.createElement('div');d.className='msg mia progress-card';d.innerHTML='<div class="who">mIA</div><div class="progress-main"><div class="spinner"></div><div class="progress-title">Entendiendo tu consulta…</div></div><div class="progress-detail"></div><div class="progress-elapsed"></div>';row.appendChild(d);convo.appendChild(row);convo.scrollTop=convo.scrollHeight;return {row,img:im,title:d.querySelector('.progress-title'),detail:d.querySelector('.progress-detail'),elapsed:d.querySelector('.progress-elapsed')};
}
function updateProgress(p,event){const state=canonicalState(event.state||'pensando');p.title.textContent=cleanDisplay(event.message)||'Estoy trabajando en ello…';p.detail.textContent=cleanDisplay(event.detail);p.elapsed.textContent=event.elapsed_ms>1000?`${(event.elapsed_ms/1000).toFixed(1)} s · consulta en curso`:'';p.img.src=miniAvatarSrc(state);const largeState=(state==='avisando'||state==='confundida')?state:(event.elapsed_ms<650?'pensando':'concentrada');setAvatarState(largeState,event.detail||'');convo.scrollTop=convo.scrollHeight;if(event.elapsed_ms>=4500&&!lastProgressSpoken){lastProgressSpoken=true;speakProgress('Sigo revisándolo. En cuanto lo tenga, te digo.',largeState)}}
function renderResponseMeta(r,wrap){const meta=r.meta||{},q=r.data_quality||r.calidad||(r.data||{}).calidad||{};const bar=document.createElement('div');bar.className='response-meta';let quality='';if(q&&typeof q==='object')quality=cleanDisplay(q.estado);if(quality){const qp=document.createElement('span');qp.className='meta-pill '+(quality==='con_observaciones'?'warn':'ok');qp.innerHTML='<span class="meta-dot"></span>'+(quality==='con_observaciones'?'Datos con observaciones':'Datos validados con las reglas disponibles');bar.appendChild(qp)}if(meta.elapsed_ms!==undefined){const t=document.createElement('span');t.className='meta-pill';t.textContent=`${nf.format(Number(meta.elapsed_ms)||0)} ms`;bar.appendChild(t)}if(bar.childNodes.length)wrap.appendChild(bar)}
function renderQuerySummary(data,wrap){const txt=cleanDisplay(data?.query_summary);if(!txt)return;const d=document.createElement('div');d.className='query-summary';d.innerHTML='<span class="qs-dot"></span><strong>He interpretado:</strong><span>'+encodeText(txt)+'</span>';wrap.appendChild(d)}
function renderInsights(data,wrap){const arr=Array.isArray(data.insights)?data.insights:[];if(!arr.length)return;const p=document.createElement('div');p.className='insight-panel';p.innerHTML='<div class="result-head"><strong>Lectura contextual</strong><span>mIA</span></div>';const l=document.createElement('div');l.className='insight-list';arr.forEach(x=>{const txt=cleanDisplay(typeof x==='string'?x:x?.mensaje);if(!txt)return;const i=document.createElement('div');i.className='insight-item';i.innerHTML='<span class="insight-dot"></span><span>'+encodeText(txt)+'</span>';l.appendChild(i)});p.appendChild(l);wrap.appendChild(p)}
function renderQuality(data,r,wrap){let arr=Array.isArray(data.alertas_calidad)?data.alertas_calidad:[];if(!arr.length){const m=data.motor_departamental||{};arr=Array.isArray(m.alertas_calidad)?m.alertas_calidad:[]}if(!arr.length)return;const p=document.createElement('div');p.className='quality-panel';p.innerHTML='<div class="result-head"><strong>Observaciones de calidad</strong><span>No se ocultan</span></div>';const l=document.createElement('div');l.className='quality-list';arr.forEach(x=>{const txt=cleanDisplay(typeof x==='string'?x:x?.mensaje);if(!txt)return;const i=document.createElement('div');i.className='quality-item';i.innerHTML='<span class="quality-dot"></span><span>'+encodeText(txt)+'</span>';l.appendChild(i)});p.appendChild(l);wrap.appendChild(p)}
function renderComparison(data,wrap){const rows=Array.isArray(data.comparacion)?data.comparacion:[];if(!rows.length)return;const keys=Object.keys(rows[0]).filter(k=>!['metrica','unidad'].includes(k));const p=document.createElement('div');p.className='compare-panel';p.innerHTML='<div class="result-head"><strong>Comparativa homogénea</strong><span>Mismo criterio y periodo</span></div>';const sc=document.createElement('div');sc.className='compare-scroll';const t=document.createElement('table');t.className='compare-table';const th=document.createElement('thead'),tr=document.createElement('tr');['Indicador',...keys].forEach(k=>{const e=document.createElement('th');e.textContent=k;tr.appendChild(e)});th.appendChild(tr);t.appendChild(th);const tb=document.createElement('tbody');rows.forEach(r=>{const rr=document.createElement('tr');const m=document.createElement('td');m.textContent=cleanDisplay(r.metrica)||'Indicador';rr.appendChild(m);keys.forEach(k=>{const td=document.createElement('td');td.textContent=fmt(r[k])+(cleanDisplay(r.unidad)?' '+cleanDisplay(r.unidad):'');rr.appendChild(td)});tb.appendChild(rr)});t.appendChild(tb);sc.appendChild(t);p.appendChild(sc);wrap.appendChild(p)}
function hhmmToMin(v){const s=cleanDisplay(v),m=s.match(/^(\d{1,2}):(\d{2})$/);if(!m)return null;const h=+m[1],mi=+m[2];return h>=0&&h<=23&&mi>=0&&mi<=59?h*60+mi:null}
function shiftSegments(x){const out=[];(Array.isArray(x.Tramos)?x.Tramos:[]).forEach(t=>{const a=cleanDisplay(t?.Inicio),b=cleanDisplay(t?.Fin);if(a&&b)out.push({Inicio:a,Fin:b})});if(!out.length){const a=cleanDisplay(x.HoraInicio),b=cleanDisplay(x.HoraFin);if(a&&b)out.push({Inicio:a,Fin:b})}return out}
function renderShiftTimeline(data,turnos,wrap){const rows=turnos.map(x=>({Empleado:cleanDisplay(x.Empleado)||'Persona',Turno:cleanDisplay(x.Turno),Area:cleanDisplay(x.Area),EsPartido:Boolean(x.EsPartido),Tramos:shiftSegments(x)})).filter(x=>x.Tramos.length);if(!rows.length)return;const rg=[];rows.forEach(x=>x.Tramos.forEach(t=>{let a=hhmmToMin(t.Inicio),b=hhmmToMin(t.Fin);if(a===null||b===null)return;if(b<=a)b+=1440;rg.push({a,b})}));if(!rg.length)return;let min=Math.floor(Math.min(...rg.map(x=>x.a))/60)*60,max=Math.ceil(Math.max(...rg.map(x=>x.b))/60)*60;if(max-min<360)max=min+360;max=Math.min(max,1800);const span=Math.max(60,max-min);const p=document.createElement('div');p.className='shift-panel';const h=document.createElement('div');h.className='shift-head';h.innerHTML=`<div class="shift-head-title"><strong>Planificación de turnos</strong><span>${encodeText([cleanDisplay(data.departamento),cleanDisplay(data.fecha),cleanDisplay(data.criterio_operativo)].filter(Boolean).join(' · '))}</span></div><div class="shift-badge">${encodeText(cleanDisplay(data.franja)||rows.length+' turnos')}</div>`;p.appendChild(h);const axis=document.createElement('div');axis.className='shift-axis';axis.innerHTML='<div class="shift-axis-spacer"></div><div class="shift-axis-hours"></div>';const ah=axis.lastElementChild;for(let i=0;i<6;i++){const m=min+span*i/5,s=document.createElement('span');s.style.left=`${i*20}%`;s.textContent=`${String(Math.floor((m%1440)/60)).padStart(2,'0')}:${String(Math.round(m%60)).padStart(2,'0')}`;ah.appendChild(s)}p.appendChild(axis);const list=document.createElement('div');list.className='shift-list';rows.forEach(x=>{const r=document.createElement('div');r.className='shift-row';const person=document.createElement('div');person.innerHTML=`<div class="shift-person-name">${encodeText(x.Empleado)}</div><div class="shift-person-meta"><span class="shift-time">${encodeText(x.Turno||x.Tramos.map(t=>t.Inicio+'–'+t.Fin).join(' / '))}</span>${x.EsPartido?'<span class="split-chip">Turno partido</span>':''}${x.Area?'<span class="area-chip">'+encodeText(x.Area)+'</span>':''}</div>`;r.appendChild(person);const track=document.createElement('div');track.className='shift-track';x.Tramos.forEach(t=>{let a=hhmmToMin(t.Inicio),b=hhmmToMin(t.Fin);if(a===null||b===null)return;if(b<=a)b+=1440;const bar=document.createElement('div');bar.className='shift-bar'+(x.EsPartido?' split':'');bar.style.left=`${Math.max(0,(a-min)/span*100)}%`;bar.style.width=`${Math.max(1,(b-a)/span*100)}%`;bar.title=`${x.Empleado} · ${t.Inicio}-${t.Fin}`;track.appendChild(bar)});r.appendChild(track);list.appendChild(r)});p.appendChild(list);if(data.criterio_franja){const n=document.createElement('div');n.className='shift-note';n.textContent='Criterio: '+cleanDisplay(data.criterio_franja)+'.';p.appendChild(n)}if(data.criterio_horario_provisional){const n=document.createElement('div');n.className='shift-note warn';n.textContent='Franja provisional pendiente de validar con el criterio operativo específico de este departamento.';p.appendChild(n)}wrap.appendChild(p)}
function renderTurnsTable(data,turnos,wrap){if(!turnos.length)return;const p=document.createElement('details');p.className='table-panel';const s=document.createElement('summary');s.style.cssText='cursor:pointer;padding:12px 14px;font-size:9.5px;font-weight:800;color:#6d5142';s.textContent='Ver listado detallado · '+turnos.length+' registros';p.appendChild(s);const sc=document.createElement('div');sc.className='table-scroll';const t=document.createElement('table');t.className='data-table';const hasArea=turnos.some(x=>cleanDisplay(x.Area));t.innerHTML='<thead><tr><th>Colaborador</th><th>Horario</th>'+(hasArea?'<th>Sección</th>':'')+'</tr></thead>';const tb=document.createElement('tbody');turnos.forEach(x=>{const tr=document.createElement('tr');const name=cleanDisplay(x.Empleado)||'—',time=cleanDisplay(x.Turno)||shiftSegments(x).map(t=>t.Inicio+'–'+t.Fin).join(' / ')||'—';tr.innerHTML='<td>'+encodeText(name)+'</td><td class="time">'+encodeText(time)+'</td>'+(hasArea?'<td class="area">'+encodeText(cleanDisplay(x.Area)||'Sin sección')+'</td>':'');tb.appendChild(tr)});t.appendChild(tb);sc.appendChild(t);p.appendChild(sc);wrap.appendChild(p)}
function renderGenericTable(cfg,wrap){
 if(!cfg||!Array.isArray(cfg.rows))return;const rows=cfg.rows,cols=(Array.isArray(cfg.columns)?cfg.columns:[]).filter(c=>c&&c.key);const p=document.createElement('div');p.className='generic-table-panel';
 const head=document.createElement('div');head.className='generic-table-head';const title=document.createElement('div');title.className='generic-table-title';title.innerHTML='<strong>'+encodeText(cleanDisplay(cfg.title)||'Detalle')+'</strong><span>'+encodeText(cleanDisplay(cfg.subtitle)||'Información estructurada')+'</span>';head.appendChild(title);const count=document.createElement('div');count.className='generic-table-count';count.textContent=nf.format(Number(cfg.total??rows.length))+' '+((Number(cfg.total??rows.length)===1)?'registro':'registros');head.appendChild(count);p.appendChild(head);
 let filterInput=null;if(cfg.searchable&&rows.length>8){const f=document.createElement('div');f.className='generic-filter';filterInput=document.createElement('input');filterInput.type='search';filterInput.placeholder='Filtrar este listado…';f.appendChild(filterInput);p.appendChild(f)}
 const sc=document.createElement('div');sc.className='generic-table-scroll';const t=document.createElement('table');t.className='generic-table';const th=document.createElement('thead'),tr=document.createElement('tr');cols.forEach(c=>{const e=document.createElement('th');e.textContent=cleanDisplay(c.label)||cleanDisplay(c.key);tr.appendChild(e)});th.appendChild(tr);t.appendChild(th);const tb=document.createElement('tbody');t.appendChild(tb);
 const paint=(q='')=>{tb.innerHTML='';const nq=cleanDisplay(q).toLowerCase();let visible=0;rows.forEach(row=>{const values=cols.map(c=>cleanDisplay(row?.[c.key]));if(nq&&!values.join(' ').toLowerCase().includes(nq))return;visible++;const rr=document.createElement('tr');cols.forEach((c,i)=>{const td=document.createElement('td');td.dataset.label=cleanDisplay(c.label)||cleanDisplay(c.key);const val=values[i];if(c.type==='status'&&val){const sp=document.createElement('span');sp.className='status-chip';sp.textContent=val;td.appendChild(sp)}else td.textContent=val||'—';rr.appendChild(td)});tb.appendChild(rr)});if(!visible){const rr=document.createElement('tr'),td=document.createElement('td');td.colSpan=Math.max(1,cols.length);td.className='generic-empty';td.textContent='No hay resultados con ese filtro.';rr.appendChild(td);tb.appendChild(rr)}};paint();if(filterInput)filterInput.addEventListener('input',()=>paint(filterInput.value));sc.appendChild(t);p.appendChild(sc);wrap.appendChild(p)
}

function prettyKey(k){
 const map={
  Situacion:'Situación',Departamento:'Departamento',Puesto:'Puesto',FechaNacimiento:'Fecha de nacimiento',Edad:'Edad',FechaAlta:'Fecha de incorporación',Antiguedad:'Antigüedad',
  SaldoActual:'Saldo disponible',SaldoTotal:'Días asignados',SaldoConsumido:'Días consumidos',Periodo:'Periodo',periodo_ultima:'Última nómina',total:'Total',total_documentos:'Documentos',
  FechaInicio:'Desde',FechaFin:'Hasta',Dias:'Días',Activa:'Activa',Estado:'Estado',TipoSolicitud:'Tipo',Turno:'Turno',Tipo:'Situación',Area:'Área',HoraInicio:'Inicio',HoraFin:'Fin',Fecha:'Fecha',FechaISO:'Fecha',
  NombreArchivo:'Documento',TieneDocumento:'Documento',ResponsableDirecto:'Responsable directo',Seccion:'Sección',periodos_detectados:'Periodos registrados',actualmente_de_vacaciones:'Actualmente de vacaciones',
  current_on_leave:'Actualmente de baja',currently_on_leave:'Actualmente de baja',currently_on_vacation:'Actualmente de vacaciones',published_days_current_week:'Días publicados esta semana',scheduled_work_days_current_week:'Días de trabajo publicados esta semana',vacation_balance_pct:'Saldo de vacaciones',
  por_categoria:'Por categoría',ultima:'Última',ultimo:'Último documento',proxima:'Próximo periodo',proximas:'Próximos periodos',ultima_finalizada:'Último periodo finalizado',reincorporacion_confirmada:'Primer turno posterior publicado'
 };
 if(map[k])return map[k];return String(k||'').replace(/_/g,' ').replace(/([a-záéíóú])([A-Z])/g,'$1 $2').replace(/^./,c=>c.toUpperCase())
}
const MONTHS_ES=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
function parseDateValue(v){
 const s=cleanDisplay(v);if(!s)return null;let m=s.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);if(m)return {d:+m[1],m:+m[2],y:+m[3]};
 m=s.match(/^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/);if(m)return {d:+m[3],m:+m[2],y:+m[1]};return null
}
function humanDate(v,short=false){const d=parseDateValue(v);if(!d)return cleanDisplay(v);if(short)return `${d.d} ${MONTHS_ES[d.m-1]}`;return `${d.d} de ${MONTHS_ES[d.m-1]} de ${d.y}`}
function humanMonth(v){const s=cleanDisplay(v),m=s.match(/^(\d{4})-(\d{2})$/);if(!m)return s;const i=+m[2];return i>=1&&i<=12?`${MONTHS_ES[i-1]} de ${m[1]}`:s}
function humanRange(a,b){const da=parseDateValue(a),db=parseDateValue(b);if(!da&&!db)return 'No consta';if(da&&db&&da.y===db.y&&da.m===db.m)return `del ${da.d} al ${db.d} de ${MONTHS_ES[da.m-1]} de ${da.y}`;if(da&&db)return `${humanDate(a)} → ${humanDate(b)}`;return humanDate(a||b)}
function displayValue(v){
 if(v===true)return 'Sí';if(v===false)return 'No';if(v===null||v===undefined||v==='')return '—';
 if(typeof v==='string'){const date=parseDateValue(v);if(date)return humanDate(v);if(/^\d{4}-\d{2}$/.test(v))return humanMonth(v);return cleanDisplay(v)||'—'}
 if(Array.isArray(v)){if(!v.length)return '—';if(v.every(x=>typeof x!=='object'))return v.map(displayValue).filter(Boolean).join(', ');return nf.format(v.length)+' elementos'}
 if(typeof v==='object'){
  const a=cleanDisplay(v.FechaInicio),b=cleanDisplay(v.FechaFin);if(a||b)return humanRange(a,b);
  const turno=cleanDisplay(v.Turno)||cleanDisplay(v.Tipo),area=cleanDisplay(v.Area),fecha=cleanDisplay(v.Fecha)||cleanDisplay(v.FechaISO);if(turno)return [turno,area,fecha?humanDate(fecha):''].filter(Boolean).join(' · ');
  const name=cleanDisplay(v.nombre||v.Nombre||v.Title||v.DisplayName||v.Empleado);if(name)return name;
  const period=cleanDisplay(v.Periodo||v.periodo);if(period)return humanMonth(period);
  const file=cleanDisplay(v.NombreArchivo);if(file)return file;
  return 'Información disponible'
 }
 return fmt(v)
}
const HIDDEN_EMPLOYEE_KEYS=new Set(['FechaAltaEstado','FechaAltaNota','DatosContactoVisibilidad','MailsDepartamento','Mails Departamento','Mails_Departamento','EmailsDepartamento','Emails','Mails','scope','history_loaded','metodo_busqueda','principles']);
function makeDefGrid(obj,skip=[]){
 const box=document.createElement('div');box.className='e360-defs';const blocked=new Set([...skip,...HIDDEN_EMPLOYEE_KEYS]);
 Object.entries(obj||{}).forEach(([k,v])=>{if(blocked.has(k)||k.startsWith('_')||v===null||v===undefined||v===''||typeof v==='object')return;
  let label=prettyKey(k),value=displayValue(v);if(k==='FechaAlta'&&!value)return;if(k==='DatosContactoDisponibles')label='Datos de contacto';
  const d=document.createElement('div');d.className='e360-def';d.innerHTML='<div class="e360-def-k">'+encodeText(label)+'</div><div class="e360-def-v">'+encodeText(value)+'</div>';box.appendChild(d)
 });return box
}
function describeShift(x){if(!x||typeof x!=='object')return 'Sin información publicada';const t=cleanDisplay(x.Turno)||cleanDisplay(x.Tipo),a=cleanDisplay(x.Area),f=cleanDisplay(x.Fecha)||cleanDisplay(x.FechaISO);return [t,a,f?humanDate(f):''].filter(Boolean).join(' · ')||'Sin información publicada'}
function describeVacation(x){if(Array.isArray(x))x=x[0];if(!x||typeof x!=='object')return 'No consta';const a=cleanDisplay(x.FechaInicio),b=cleanDisplay(x.FechaFin);return a||b?humanRange(a,b):(cleanDisplay(x.Estado)||'No consta')}
function renderSpotlight(data,body){const b=document.createElement('div');b.className='e360-spotlight';const items=[['Turno / situación de hoy',describeShift(data?.turno)],['Vacaciones actuales',describeVacation(data?.vacaciones_actuales)],['Baja actual',data?.baja_actual?describeVacation(data.baja_actual):'No consta baja actual']];items.forEach(([k,v])=>{const r=document.createElement('div');r.className='e360-spot';r.innerHTML='<div class="e360-spot-label">'+encodeText(k)+'</div><div class="e360-spot-value">'+encodeText(v)+'</div>';b.appendChild(r)});body.appendChild(b)}
function renderWeek(items,body){
 if(!Array.isArray(items)||!items.length){body.innerHTML='<div class="e360-empty">No hay turnos publicados para esta semana.</div>';return}
 const note=document.createElement('div');note.className='e360-empty';note.style.textAlign='left';note.style.padding='0 0 8px';note.textContent='Información publicada en Turnos para la semana actual.';body.appendChild(note);
 const g=document.createElement('div');g.className='e360-week';const today=new Date().toISOString().slice(0,10);items.forEach(x=>{const d=document.createElement('div');d.className='e360-day'+(cleanDisplay(x.FechaISO)===today?' today':'');const raw=cleanDisplay(x.Fecha)||cleanDisplay(x.FechaISO);d.innerHTML='<div class="e360-day-date">'+encodeText(humanDate(raw,true)||'—')+'</div><div class="e360-day-turn">'+encodeText(cleanDisplay(x.Turno)||cleanDisplay(x.Tipo)||'—')+'</div><div class="e360-day-meta">'+encodeText(cleanDisplay(x.Area)||cleanDisplay(x.Departamento)||'')+'</div>';g.appendChild(d)});body.appendChild(g)
}
function renderTimeline(items,body){if(!Array.isArray(items)||!items.length){body.innerHTML='<div class="e360-empty">No hay próximos hitos publicados.</div>';return}const g=document.createElement('div');g.className='e360-timeline';items.forEach(x=>{const e=document.createElement('div');e.className='e360-event '+cleanDisplay(x.state);const raw=cleanDisplay(x.display_date)||cleanDisplay(x.date),sub=cleanDisplay(x.subtitle);e.innerHTML='<div class="e360-event-date">'+encodeText(humanDate(raw,true)||'—')+'</div><div class="e360-event-rail"><span class="e360-event-dot"></span></div><div><div class="e360-event-title">'+encodeText(cleanDisplay(x.title)||'Hito')+'</div><div class="e360-event-sub">'+encodeText(sub.replace(/(\d{2}\/\d{2}\/\d{4})/g,m=>humanDate(m)))+'</div></div>';g.appendChild(e)});body.appendChild(g)}
function renderPeople(data,body){
 const w=document.createElement('div');w.className='e360-people';const seen=new Set();const add=(name,direct=false)=>{name=cleanDisplay(name);if(!name||seen.has(name.toLowerCase()))return;seen.add(name.toLowerCase());const c=document.createElement('div');c.className='e360-person'+(direct?' direct':'');c.innerHTML='<span class="e360-person-dot"></span>'+encodeText(name)+(direct?' · responsable directo':'');w.appendChild(c)};
 const direct=data?.ResponsableDirecto;if(direct)add(typeof direct==='string'?direct:(direct.nombre||direct.Nombre||direct.Title||direct.DisplayName||direct.Empleado),true);
 ['Responsables','responsables','ResponsablesDepartamento','responsables_departamento'].forEach(k=>{const a=data?.[k];if(Array.isArray(a))a.forEach(x=>add(typeof x==='string'?x:(x?.nombre||x?.Nombre||x?.Title||x?.DisplayName)))});
 if(!w.childNodes.length){body.appendChild(makeDefGrid(data||{}));return}body.appendChild(w);const dep=cleanDisplay(data?.Departamento);if(dep){const meta=document.createElement('div');meta.className='e360-empty';meta.style.textAlign='left';meta.style.padding='9px 0 0';meta.textContent='Responsables asociados al departamento de '+dep+'.';body.appendChild(meta)}
}
function vacationObj(v){if(Array.isArray(v))return v[0]||null;return v&&typeof v==='object'?v:null}
function renderVacationData(data,body){
 const saldo=data?.saldo&&typeof data.saldo==='object'?data.saldo:{};const actual=vacationObj(data?.actual);const prox=vacationObj(data?.proxima)||vacationObj(data?.proximas);const last=vacationObj(data?.ultima_finalizada);const re=data?.reincorporacion_confirmada;
 const g=document.createElement('div');g.className='e360-metrics';const add=(k,v)=>{if(!cleanDisplay(v))return;const c=document.createElement('div');c.className='e360-metric';c.innerHTML='<strong>'+encodeText(k)+'</strong><span>'+encodeText(v)+'</span>';g.appendChild(c)};
 if(actual)add('Periodo actual',describeVacation(actual));
 const sa=saldo.SaldoActual,st=saldo.SaldoTotal;if(sa!==null&&sa!==undefined)add('Saldo disponible',`${displayValue(sa)}${st!==null&&st!==undefined?' de '+displayValue(st):''} días`);
 if(prox)add('Próximo periodo',describeVacation(prox));if(re)add('Primer turno de trabajo publicado posterior',describeShift(re));if(last)add('Último periodo finalizado',describeVacation(last));
 if(!g.childNodes.length)add('Vacaciones','No hay información adicional disponible.');body.appendChild(g)
}
function renderAbsenceData(data,body){const g=document.createElement('div');g.className='e360-metrics';const n=Number(data?.periodos_detectados);if(Number.isFinite(n)){const c=document.createElement('div');c.className='e360-metric';c.innerHTML='<strong>Histórico de bajas</strong><span>'+(n===0?'No constan periodos registrados':encodeText(n+' '+(n===1?'periodo registrado':'periodos registrados')))+'</span>';g.appendChild(c)}if(data?.actual){const c=document.createElement('div');c.className='e360-metric';c.innerHTML='<strong>Baja actual</strong><span>'+encodeText(describeVacation(data.actual))+'</span>';g.appendChild(c)}if(data?.ultima){const c=document.createElement('div');c.className='e360-metric';c.innerHTML='<strong>Última baja</strong><span>'+encodeText(describeVacation(data.ultima))+'</span>';g.appendChild(c)}if(!g.childNodes.length){body.innerHTML='<div class="e360-empty">No consta información de bajas.</div>';return}body.appendChild(g)}
function renderDocumentsData(data,body){
 const pay=data?.nominas&&typeof data.nominas==='object'?data.nominas:{},docs=data?.documentos_firmados&&typeof data.documentos_firmados==='object'?data.documentos_firmados:{};const g=document.createElement('div');g.className='e360-metrics';const add=(k,v)=>{if(v===null||v===undefined||v==='')return;const c=document.createElement('div');c.className='e360-metric';c.innerHTML='<strong>'+encodeText(k)+'</strong><span>'+encodeText(String(v))+'</span>';g.appendChild(c)};
 const last=cleanDisplay(pay.periodo_ultima)||cleanDisplay(pay?.ultima?.Periodo)||cleanDisplay(pay?.ultima?.periodo);if(last)add('Última nómina',humanMonth(last));const pt=pay.total_documentos??pay.total;if(pt!==null&&pt!==undefined)add('Documentos de nómina/retribución',nf.format(Number(pt)||0));
 const dt=docs.total??docs.total_documentos;if(dt!==null&&dt!==undefined)add('Documentos firmados',nf.format(Number(dt)||0));if(docs.por_categoria&&typeof docs.por_categoria==='object'){const cats=Object.entries(docs.por_categoria).filter(([,v])=>Number(v)>0).map(([k,v])=>`${k}: ${v}`).join(' · ');if(cats)add('Por categoría',cats)}
 if(!g.childNodes.length)body.innerHTML='<div class="e360-empty">No hay información documental adicional.</div>';else body.appendChild(g)
}
function renderEmploymentData(data,body){const clean={};['Situacion','Departamento','Puesto','FechaNacimiento','Edad','FechaAlta','Antiguedad','DatosContactoDisponibles'].forEach(k=>{if(data?.[k]!==undefined&&data?.[k]!==null&&data?.[k]!=='')clean[k]=data[k]});const g=makeDefGrid(clean);if(!g.childNodes.length){body.innerHTML='<div class="e360-empty">Sin información laboral adicional.</div>';return}body.appendChild(g);if(!data?.FechaAlta&&cleanDisplay(data?.FechaAltaEstado).includes('no_disponible')){const note=document.createElement('div');note.className='e360-empty';note.style.textAlign='left';note.style.padding='9px 0 0';note.textContent='La fecha real de incorporación no está disponible en una fuente autoritativa.';body.appendChild(note)}}
function renderMetricData(data,body){if(!data||typeof data!=='object'){body.innerHTML='<div class="e360-empty">Sin información adicional.</div>';return}const g=document.createElement('div');g.className='e360-metrics';Object.entries(data).forEach(([k,v])=>{if(HIDDEN_EMPLOYEE_KEYS.has(k)||k.startsWith('_')||v===null||v===undefined||v===''||(Array.isArray(v)&&!v.length))return;const c=document.createElement('div');c.className='e360-metric';let value=Array.isArray(v)?v.slice(0,3).map(x=>displayValue(x)).join(' · '):displayValue(v);c.innerHTML='<strong>'+encodeText(prettyKey(k))+'</strong><span>'+encodeText(value)+'</span>';g.appendChild(c)});if(!g.childNodes.length)body.innerHTML='<div class="e360-empty">Sin información adicional.</div>';else body.appendChild(g)}
function renderCompactData(data,body){renderDocumentsData(data,body)}
function sectionIcon(id){
 const icons={today:'◉',week:'▦',next:'→',employment:'▤',organization:'◎',vacations:'☀',absence:'＋',documents:'▣'};
 return icons[cleanDisplay(id)]||'•'
}
function renderEmployeeSection(sec,container){
 let card=null,body=null,id='section';
 try{
  sec=(sec&&typeof sec==='object')?sec:{};id=cleanDisplay(sec.id)||'section';
  card=document.createElement('div');card.className='e360-section'+(['week','next'].includes(id)?' full':'');card.dataset.section=id;
  const head=document.createElement('div');head.className='e360-section-head';let title=cleanDisplay(sec.title)||prettyKey(id);if(id==='week')title='Semana publicada en Turnos';
  head.innerHTML='<div class="e360-section-title"><span class="e360-section-icon">'+encodeText(sectionIcon(id))+'</span>'+encodeText(title)+'</div>';card.appendChild(head);
  body=document.createElement('div');body.className='e360-section-body';card.appendChild(body);
  if(sec.layout==='spotlight')renderSpotlight(sec.data||{},body);else if(sec.layout==='week_strip')renderWeek(Array.isArray(sec.items)?sec.items:[],body);else if(sec.layout==='timeline')renderTimeline(Array.isArray(sec.items)?sec.items:[],body);else if(id==='employment')renderEmploymentData(sec.data||{},body);else if(sec.layout==='people_chips')renderPeople(sec.data||{},body);else if(id==='vacations')renderVacationData(sec.data||{},body);else if(id==='absence')renderAbsenceData(sec.data||{},body);else if(id==='documents')renderDocumentsData(sec.data||{},body);else renderMetricData(sec.data||sec.items||{},body);
 }catch(sectionError){
  console.warn('[mIA Employee360 section]',id,sectionError);
  if(!card){card=document.createElement('div');card.className='e360-section e360-section-degraded';card.dataset.section=id}
  else card.classList.add('e360-section-degraded');
  if(!body){body=document.createElement('div');body.className='e360-section-body';card.appendChild(body)}
  body.innerHTML='<div class="e360-empty">Esta sección no se ha podido representar en formato visual. El dato completo permanece disponible en el resumen de la ficha.</div>';
 }
 if(card&&!card.parentNode)container.appendChild(card);
 return !!card
}
function e360Root(data){return (data?.employee360&&typeof data.employee360==='object')?data.employee360:data}
function synthesizeEmployee360Presentation(data){
 const root=e360Root(data);if(!root||typeof root!=='object')return null;const emp=root.empleado||{},labor=root.datos_laborales||{},org=root.organizacion||root.contexto_organizativo||{},shifts=root.turnos_inteligentes||{},vac=root.vacaciones_inteligentes||{},saldo=root.saldo_vacaciones||{},absence=root.bajas||{},pay=root.nominas||{},docs=root.documentos_firmados||{};const name=cleanDisplay(emp.Nombre||root.nombre_empleado||root.Empleado);if(!name)return null;const initials=name.split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase();const latestPay=pay.periodo_ultima||pay?.ultima?.Periodo||pay?.ultima?.periodo||'—';const timeline=[];const pushEvent=(date,title,subtitle,state='info')=>{if(!date&&!subtitle)return;timeline.push({date,display_date:date,title,subtitle,state})};if(vac.proxima){const v=vacationObj(vac.proxima);pushEvent(v?.FechaInicio,'Próximas vacaciones',describeVacation(v),'vacation')}if(shifts.proximo_turno)pushEvent(shifts.proximo_turno.Fecha,'Próximo turno',describeShift(shifts.proximo_turno),'work');if(shifts.proximo_dia_libre)pushEvent(shifts.proximo_dia_libre.Fecha,'Próximo descanso',describeShift(shifts.proximo_dia_libre),'rest');
 return {schema:'mia.employee360.presentation',version:'frontend-fallback-2',layout:'employee_360_premium',hero:{title:name,subtitle:[emp.Puesto,emp.Departamento].filter(Boolean).join(' · '),initials,status:emp.Activo===false?'inactive':'active',badges:[emp.Puesto,emp.Departamento,org.Seccion].filter(Boolean)},kpis:[
  {id:'status',label:'Situación',value:labor.Situacion||(emp.Activo===false?'Inactivo':'Activo'),variant:'success'},
  {id:'shift_today',label:'Turno hoy',value:shifts?.hoy?.Turno||shifts?.hoy?.Tipo||'Sin turno publicado',variant:'primary'},
  {id:'vacation_balance',label:'Saldo vacaciones',value:saldo.SaldoActual,unit:'días',variant:'info'},
  {id:'latest_payroll',label:'Última nómina',value:latestPay,variant:'neutral'}
 ],sections:[
  {id:'today',title:'Hoy',layout:'spotlight',data:{turno:shifts.hoy,baja_actual:absence.actual,vacaciones_actuales:vac.actual}},
  {id:'week',title:'Semana actual',layout:'week_strip',items:shifts.semana_actual||[]},
  {id:'next',title:'Próximos hitos',layout:'timeline',items:timeline},
  {id:'employment',title:'Ficha laboral',layout:'definition_grid',data:labor},
  {id:'organization',title:'Organización',layout:'people_chips',data:org},
  {id:'vacations',title:'Vacaciones',layout:'metric_detail',data:{saldo,...vac}},
  {id:'absence',title:'Bajas',layout:'metric_detail',data:absence},
  {id:'documents',title:'Documentación y nóminas',layout:'compact_cards',data:{nominas:pay,documentos_firmados:docs}}
 ],quick_actions:[
  {id:'shifts',label:'Ver turnos',prompt:'Muéstrame sus turnos'}, {id:'vacations',label:'Ver vacaciones',prompt:'Muéstrame sus vacaciones'},
  {id:'absence',label:'Ver bajas',prompt:'Muéstrame sus bajas'}, {id:'payroll',label:'Ver nóminas',prompt:'Muéstrame sus nóminas'},
  {id:'documents',label:'Ver documentos',prompt:'Muéstrame sus documentos'}
 ]}
}
function renderEmployee360FullPayload(data,body){
 const root=e360Root(data);if(!root)return;const rows=[];const add=(k,v)=>{if(v===null||v===undefined||v===''||HIDDEN_EMPLOYEE_KEYS.has(k))return;rows.push([k,v])};
 const emp=root.empleado||{},labor=root.datos_laborales||{},org=root.organizacion||{},sh=root.turnos_inteligentes||{},vac=root.vacaciones_inteligentes||{},saldo=root.saldo_vacaciones||{},ba=root.bajas||{},pay=root.nominas||{},docs=root.documentos_firmados||{};
 add('Nombre',emp.Nombre);add('Situación',labor.Situacion||(emp.Activo===false?'Inactivo':'Activo'));add('Puesto',emp.Puesto||labor.Puesto);add('Departamento',emp.Departamento||labor.Departamento);add('Fecha de nacimiento',emp.FechaNacimiento||labor.FechaNacimiento);add('Edad',emp.Edad||labor.Edad);
 add('Turno de hoy',sh.hoy?describeShift(sh.hoy):null);add('Próximo turno',sh.proximo_turno?describeShift(sh.proximo_turno):null);add('Próximo descanso',sh.proximo_dia_libre?describeShift(sh.proximo_dia_libre):null);add('Vacaciones actuales',vac.actual?describeVacation(vac.actual):null);add('Próximas vacaciones',vac.proxima?describeVacation(vac.proxima):null);if(saldo.SaldoActual!==undefined)add('Saldo de vacaciones',`${displayValue(saldo.SaldoActual)}${saldo.SaldoTotal!==undefined?' de '+displayValue(saldo.SaldoTotal):''} días`);add('Periodos de baja registrados',ba.periodos_detectados);add('Última nómina',pay.periodo_ultima?humanMonth(pay.periodo_ultima):null);add('Documentos firmados',docs.total);
 if(!rows.length)return;const details=document.createElement('details');details.className='e360-full';details.open=true;const sum=document.createElement('summary');sum.innerHTML='<span>Resumen completo de la ficha</span><small>'+rows.length+' datos</small>';details.appendChild(sum);const content=document.createElement('div');content.className='e360-full-body';const grid=document.createElement('div');grid.className='e360-full-grid';rows.forEach(([k,v])=>{const item=document.createElement('div');item.className='e360-full-item';item.innerHTML='<div class="e360-full-k">'+encodeText(k)+'</div><div class="e360-full-v">'+encodeText(typeof v==='string'?v:displayValue(v))+'</div>';grid.appendChild(item)});content.appendChild(grid);details.appendChild(content);body.appendChild(details)
}
async function downloadGeneratedReport(action,presentation,button){if(!action||action.enabled===false||action.action!=='generate_report')return;const old=button.textContent;button.classList.add('busy');button.textContent='Generando…';try{const payload={modulo:action.module||'ficha360',formato:action.format||'pdf',nombre:cleanDisplay(presentation?.hero?.title)};const res=await fetch(action.endpoint||'/api/mia/informes/generar',{method:action.method||'POST',headers:{'Content-Type':'application/json; charset=utf-8',...await miaAuthHeaders()},body:JSON.stringify(payload)});if(!res.ok){let detail='';try{detail=(await res.json())?.error||''}catch(_){}throw new Error(detail||('HTTP '+res.status))}const blob=await res.blob();let filename='mIA_'+(payload.modulo||'informe')+'.'+(payload.formato==='xlsx'?'xlsx':'pdf');const cd=res.headers.get('Content-Disposition')||'';const m=cd.match(/filename="?([^";]+)"?/i);if(m)filename=m[1];const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2500);button.textContent='✓ Generado';setTimeout(()=>button.textContent=old,1800)}catch(e){button.textContent='Error al generar';button.title=String(e?.message||e);setTimeout(()=>button.textContent=old,2400)}finally{button.classList.remove('busy')}}
function renderEmployee360Presentation(presentation,data,wrap){
 if(!presentation||presentation.schema!=='mia.employee360.presentation')return false;const panel=document.createElement('div');panel.className='e360';const hero=presentation.hero||{};const h=document.createElement('div');h.className='e360-hero';const badgeVals=Array.isArray(hero.badges)?hero.badges:[];const seen=new Set();const badges=badgeVals.filter(x=>{const z=cleanDisplay(x).toLowerCase();if(!z||seen.has(z))return false;seen.add(z);return true}).map(x=>'<span class="e360-badge">'+encodeText(cleanDisplay(x))+'</span>').join('');h.innerHTML='<div class="e360-avatar">'+encodeText(cleanDisplay(hero.initials)||'E')+'</div><div class="e360-hero-copy"><div class="e360-hero-title">'+encodeText(cleanDisplay(hero.title)||'Ficha de empleado')+'</div><div class="e360-hero-sub">'+encodeText(cleanDisplay(hero.subtitle)||'Employee360')+'</div><div class="e360-badges">'+badges+'</div></div><div class="e360-status '+(hero.status==='inactive'?'inactive':'')+'"><span class="e360-status-dot"></span>'+(hero.status==='inactive'?'Inactivo':'Activo')+'</div>';panel.appendChild(h);const body=document.createElement('div');body.className='e360-body';panel.appendChild(body);
 const kpis=Array.isArray(presentation.kpis)?presentation.kpis.filter(x=>x&&typeof x==='object'):[];if(kpis.length){const g=document.createElement('div');g.className='e360-kpis';kpis.forEach(x=>{const k=document.createElement('div');k.className='e360-kpi '+cleanDisplay(x.variant);let val=displayValue(x.value);k.innerHTML='<div class="e360-kpi-label">'+encodeText(cleanDisplay(x.label)||'Dato')+'</div><div class="e360-kpi-value">'+encodeText(val)+(cleanDisplay(x.unit)?'<span class="e360-kpi-unit">'+encodeText(cleanDisplay(x.unit))+'</span>':'')+'</div>';g.appendChild(k)});body.appendChild(g)}
 const sections=document.createElement('div');sections.className='e360-sections';const sectionItems=Array.isArray(presentation.sections)?presentation.sections:[];sectionItems.forEach(sec=>renderEmployeeSection(sec,sections));if(sections.childNodes.length)body.appendChild(sections);
 try{const pa=(data?.people_analytics&&typeof data.people_analytics==='object'?data.people_analytics:(e360Root(data)?.people_analytics||null));if(pa&&pa.metrics&&typeof pa.metrics==='object'){const entries=Object.entries(pa.metrics).filter(([k,v])=>!HIDDEN_EMPLOYEE_KEYS.has(k)&&v!==null&&v!==undefined);if(entries.length){const a=document.createElement('div');a.className='e360-analytics';a.innerHTML='<div class="e360-analytics-head"><strong>Indicadores personales</strong><span>datos descriptivos</span></div>';const grid=document.createElement('div');grid.className='e360-analytics-grid';entries.forEach(([k,v])=>{const c=document.createElement('div');c.className='e360-analytic';let value=displayValue(v);if(k==='vacation_balance_pct'&&typeof v==='number')value=nf.format(v)+' %';c.innerHTML='<div class="e360-analytic-k">'+encodeText(prettyKey(k))+'</div><div class="e360-analytic-v">'+encodeText(value)+'</div>';grid.appendChild(c)});a.appendChild(grid);body.appendChild(a)}}}catch(analyticsError){console.warn('[mIA Employee360 analytics]',analyticsError)}
 try{renderEmployee360FullPayload(data,body)}catch(fullError){console.warn('[mIA Employee360 full summary]',fullError)}
 const qa=Array.isArray(presentation.quick_actions)?presentation.quick_actions:[];if(qa.length){try{const acts=document.createElement('div');acts.className='e360-actions';qa.forEach(x=>{if(!x||typeof x!=='object')return;const b=document.createElement('button');b.type='button';b.className='e360-action'+(x.action==='generate_report'?' report':'');b.textContent=cleanDisplay(x.label)||'Acción';if(x.enabled===false)b.disabled=true;if(x.prompt)b.addEventListener('click',()=>ask(x.prompt));else if(x.action==='generate_report')b.addEventListener('click',()=>downloadGeneratedReport(x,presentation,b));acts.appendChild(b)});if(acts.childNodes.length)body.appendChild(acts)}catch(actionsError){console.warn('[mIA Employee360 actions]',actionsError)}}wrap.appendChild(panel);return true
}

function renderDocuments(data,wrap){
 const docs=Array.isArray(data?.documents)?data.documents:(data?.document&&typeof data.document==='object'?[data.document]:[]);if(!docs.length)return;
 const p=document.createElement('div');p.className='document-panel';p.innerHTML='<div class="result-head"><strong>Documento CV</strong><span>CVDocs · archivo validado</span></div>';
 const list=document.createElement('div');list.className='document-list';docs.forEach((d,i)=>{const url=cleanDisplay(d.Url||d.url),name=cleanDisplay(d.FileName||d.file_name)||('CV '+(i+1)),ext=(cleanDisplay(d.Extension)||name.split('.').pop()||'CV').toUpperCase(),who=cleanDisplay(d.Nombre||data?.candidate?.Nombre),mod=cleanDisplay(d.Modified);const c=document.createElement('div');c.className='document-card';const meta=[who,mod?('Actualizado '+humanDate(mod)):'',cleanDisplay(d.Source)||'CVDocs'].filter(Boolean).join(' · ');c.innerHTML='<div class="document-icon">'+encodeText(ext.slice(0,5))+'</div><div class="document-copy"><div class="document-name">'+encodeText(name)+'</div><div class="document-meta">'+encodeText(meta)+'</div></div>';if(url){const a=document.createElement('a');a.className='document-open';a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Abrir CV ↗';c.appendChild(a)}list.appendChild(c)});p.appendChild(list);wrap.appendChild(p)
}
function renderLlmBadge(r,msg){const llm=r?._llm_v4;if(!llm)return;const general=llm.general_assistant||llm?.responder_meta?.general_assistant_version;const rm=llm.responder_meta||{};const natural=general||(!rm.degraded&&!rm.error&&(rm.composer_version||rm.request_id||rm.response_id));if(!natural)return;const b=document.createElement('div');b.className='llm-answer-badge';b.textContent=general?'Respuesta · mIA LLM':'Respuesta natural · LLM';const who=msg.querySelector('.who');if(who&&who.nextSibling)msg.insertBefore(b,who.nextSibling);else msg.appendChild(b)}
function renderEmployee360EmergencyCard(presentation,data,wrap,error){
 try{
  const root=e360Root(data)||{},emp=(root.empleado&&typeof root.empleado==='object')?root.empleado:{},hero=(presentation&&presentation.hero)||{};
  const name=cleanDisplay(hero.title)||cleanDisplay(emp.Nombre)||cleanDisplay(root.nombre_empleado)||'Ficha de empleado';
  const subtitle=cleanDisplay(hero.subtitle)||[cleanDisplay(emp.Puesto),cleanDisplay(emp.Departamento)].filter(Boolean).join(' · ')||'Employee360';
  const initials=cleanDisplay(hero.initials)||name.split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase()||'E';
  const active=hero.status!=='inactive'&&emp.Activo!==false;
  const panel=document.createElement('div');panel.className='e360 e360-emergency';panel.setAttribute('data-renderer','emergency-safe');
  const h=document.createElement('div');h.className='e360-hero';
  h.innerHTML='<div class="e360-avatar">'+encodeText(initials)+'</div><div class="e360-hero-copy"><div class="e360-hero-title">'+encodeText(name)+'</div><div class="e360-hero-sub">'+encodeText(subtitle)+'</div><div class="e360-badges"><span class="e360-badge">Employee360</span><span class="e360-badge">UI '+encodeText(MIA_UI_BUILD)+'</span></div></div><div class="e360-status '+(active?'':'inactive')+'"><span class="e360-status-dot"></span>'+(active?'Activo':'Inactivo')+'</div>';
  panel.appendChild(h);
  const body=document.createElement('div');body.className='e360-body';panel.appendChild(body);
  const pKpis=Array.isArray(presentation?.kpis)?presentation.kpis:[];
  const fallbacks=[
   {label:'Departamento',value:emp.Departamento||'—'},
   {label:'Puesto',value:emp.Puesto||'—'},
   {label:'Saldo vacaciones',value:root?.saldo_vacaciones?.SaldoActual,unit:'días'},
   {label:'Última nómina',value:root?.nominas?.periodo_ultima||root?.indicadores?.UltimaNominaPeriodo||'—'}
  ];
  const kpis=pKpis.length?pKpis.slice(0,4):fallbacks;
  const g=document.createElement('div');g.className='e360-kpis';
  kpis.forEach(x=>{const k=document.createElement('div');k.className='e360-kpi '+cleanDisplay(x?.variant);const val=(x&&x.value!==undefined&&x.value!==null&&x.value!=='')?displayValue(x.value):'—';k.innerHTML='<div class="e360-kpi-label">'+encodeText(cleanDisplay(x?.label)||'Dato')+'</div><div class="e360-kpi-value">'+encodeText(val)+(cleanDisplay(x?.unit)?'<span class="e360-kpi-unit">'+encodeText(cleanDisplay(x.unit))+'</span>':'')+'</div>';g.appendChild(k)});
  body.appendChild(g);
  const note=document.createElement('div');note.className='e360-natural-note';note.textContent=error?'La ficha completa se ha cargado con el renderer seguro porque una sección visual produjo un error. Los datos Employee360 siguen disponibles.':'Ficha Employee360 cargada con renderer seguro.';body.appendChild(note);
  renderEmployee360FullPayload(data,body);
  wrap.appendChild(panel);return true;
 }catch(emergencyError){console.error('[mIA Employee360 emergency renderer]',emergencyError);return false}
}
function renderWebSources(data,wrap){
 const arr=Array.isArray(data?.web_sources)?data.web_sources.filter(x=>x&&typeof x==='object'&&cleanDisplay(x.url)):[];
 if(!arr.length)return false;
 const d=document.createElement('details');d.className='sources-details web-sources';d.open=true;
 const summary=document.createElement('summary');summary.textContent='Fuentes web consultadas · '+arr.length;d.appendChild(summary);
 const list=document.createElement('div');list.className='web-source-list';
 arr.forEach((x,i)=>{const a=document.createElement('a');a.className='web-source-item';a.href=cleanDisplay(x.url);a.target='_blank';a.rel='noopener noreferrer';let host='';try{host=new URL(a.href).hostname.replace(/^www\./,'')}catch(_){}a.innerHTML='<span class="web-source-num">'+(i+1)+'</span><span class="web-source-copy"><strong>'+encodeText(cleanDisplay(x.title)||host||'Fuente')+'</strong><small>'+encodeText(host)+'</small></span><span class="web-source-open">↗</span>';list.appendChild(a)});
 d.appendChild(list);wrap.appendChild(d);return true
}
function resultExecutor(r){
 return cleanDisplay(r?._v12_execution?.executor||r?.data?._v12_execution?.executor||r?.meta?.architecture_v12?.executor)
}
function resultDomain(r,data){
 const ctx=r?.context||{};
 const semantic=data?.semantic_v12||{};
 const domains=Array.isArray(semantic.domains)?semantic.domains:[];
 return cleanDisplay(ctx.last_domain||semantic.domain||domains[0]||data?.domain||'').toLowerCase()
}
function mailPayload(data){
 const nested=(data?.data&&typeof data.data==='object')?data.data:{};
 const summary=(data?.mail_summary&&typeof data.mail_summary==='object')?data.mail_summary:((nested.mail_summary&&typeof nested.mail_summary==='object')?nested.mail_summary:{});
 const rows=Array.isArray(data?.mail_rows)?data.mail_rows:(Array.isArray(data?.mail_threads)?data.mail_threads:(Array.isArray(nested.mail_rows)?nested.mail_rows:[]));
 const filters=(data?.mail_filters&&typeof data.mail_filters==='object')?data.mail_filters:((nested.mail_filters&&typeof nested.mail_filters==='object')?nested.mail_filters:((summary.filters&&typeof summary.filters==='object')?summary.filters:{}));
 const security=(data?.mail_security&&typeof data.mail_security==='object')?data.mail_security:{};
 return {summary,rows,filters,security}
}
function genericRowsFromData(data){
 if(Array.isArray(data?.table?.rows))return data.table.rows;
 if(Array.isArray(data?.rows))return data.rows;
 if(Array.isArray(data?.items))return data.items;
 return []
}
function detectResultKind(r,data){
 const exe=resultExecutor(r).toLowerCase(),domain=resultDomain(r,data),intent=cleanDisplay(r?.intent).toLowerCase();
 const mail=mailPayload(data);
 if(mail.rows.length||Object.keys(mail.summary).length||exe.includes('mail')||domain==='correo'||intent.includes('mail'))return 'mail';
 if(Array.isArray(data.news_rows)&&data.news_rows.length||domain==='noticias'||intent.includes('noticia'))return 'noticias';
 const nativeEmployeePresentation=(data.presentation&&typeof data.presentation==='object'&&data.presentation.schema==='mia.employee360.presentation');
 const employee360Root=(data.employee360&&typeof data.employee360==='object');
 if(nativeEmployeePresentation||employee360Root||data.employee360_version||intent.includes('employee360')||domain==='employee360')return 'employee360';
 if(Array.isArray(data.turnos)&&data.turnos.length||domain==='turnos'||intent.includes('turno'))return 'turnos';
 if(domain.includes('vacacion')||intent.includes('vacacion'))return 'vacaciones';
 if(domain.includes('baja')||domain.includes('ausencia')||intent.includes('baja')||intent.includes('ausencia'))return 'ausencias';
 if(domain.includes('nomina')||domain.includes('nómina')||intent.includes('nomina')||intent.includes('nómina'))return 'nominas';
 if(Array.isArray(data.documents)||data.document||domain.includes('document')||domain.includes('cv')||intent.includes('document')||intent.includes('curriculum')||intent.includes('currículum'))return 'documents';
 if(Array.isArray(data.comparacion)||Array.isArray(r?.visualizations)||Array.isArray(data.cards)||data.people_analytics||intent.includes('analytics')||intent.includes('histor')||intent.includes('ranking')||intent.includes('compar'))return 'analytics';
 if(Array.isArray(data.web_sources)&&data.web_sources.length)return 'web';
 if(data.table||genericRowsFromData(data).length)return 'list';
 return 'scalar'
}
function applyResultKind(msg,kind){
 if(!msg)return;
 msg.classList.add('mia-result-host','mia-result-'+kind);
 msg.dataset.resultKind=kind;
 document.body.dataset.resultKind=kind
}
function formatMailDate(v){
 const s=cleanDisplay(v);if(!s)return '';
 const d=new Date(s);if(Number.isNaN(d.getTime()))return s;
 const now=new Date();
 const sameDay=d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()&&d.getDate()===now.getDate();
 if(sameDay)return d.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
 return d.toLocaleDateString('es-ES',{day:'2-digit',month:'short',year:d.getFullYear()===now.getFullYear()?undefined:'numeric'})
}
function mailStateLabel(v){
 const s=cleanDisplay(v).toLowerCase();
 const map={stale_pending:'Pendiente antiguo',resolved_update:'Resuelto',operational_report:'Informe operativo',official_followup:'Oficial',official:'Oficial',action_required:'Requiere acción',informational:'Informativo',pending_reply:'Pendiente de respuesta'};
 return map[s]||cleanDisplay(v).replace(/_/g,' ')
}
function mailFilterLabel(k,v){
 if(v===null||v===undefined||v===false||v==='')return '';
 if(k==='sender')return 'Remitente: '+v;
 if(k==='has_attachments')return v?'Con adjuntos':'';
 if(k==='state')return mailStateLabel(v);
 if(k==='action')return 'Acción: '+v;
 if(k==='today')return v?'Hoy':'';
 if(k==='wants_request')return v?'Petición concreta':'';
 return ''
}
function mailSender(row){
 return cleanDisplay(row?.sender_name)||cleanDisplay(row?.sender_address)||cleanDisplay((row?.conversation_sender_names||[])[0])||'Remitente no identificado'
}
function renderMailWorkspace(data,r,wrap){
 const {summary,rows,filters}=mailPayload(data);
 if(!rows.length&&!Object.keys(summary).length)return false;
 const panel=document.createElement('section');panel.className='mail-panel';panel.setAttribute('aria-label','Resultado de correo');
 const head=document.createElement('div');head.className='mail-head';
 const title=document.createElement('div');title.className='mail-title';
 title.innerHTML='<span class="mail-icon" aria-hidden="true">✉</span><div><strong>Correo</strong><small>'+encodeText(cleanDisplay(summary.mailbox)||'Bandeja de entrada')+'</small></div>';
 head.appendChild(title);
 const mode=document.createElement('span');mode.className='mail-readonly';mode.textContent='Solo lectura';head.appendChild(mode);panel.appendChild(head);
 const activeFilters=Object.entries(filters||{}).map(([k,v])=>mailFilterLabel(k,v)).filter(Boolean);
 if(activeFilters.length){const chips=document.createElement('div');chips.className='mail-filters';activeFilters.forEach(x=>{const c=document.createElement('span');c.textContent=x;chips.appendChild(c)});panel.appendChild(chips)}
 const filtered=activeFilters.length>0;
 const matchedMessages=Number(summary.matched_unread_messages??rows.reduce((a,x)=>a+Number(x?.conversation_unread_count||1),0));
 const stats=filtered?[
  ['Conversaciones',summary.matched_conversations??rows.length],
  ['Mensajes',matchedMessages]
 ]:[
  ['Sin leer',summary.total_unread??matchedMessages],
  ['Conversaciones',summary.total_conversations??rows.length],
  ['Requieren atención',summary.requires_attention],
  ['Pendientes de respuesta',summary.requires_reply]
 ];
 const validStats=stats.filter(([,v])=>v!==undefined&&v!==null&&v!=='');
 if(validStats.length){const sg=document.createElement('div');sg.className='mail-stats';validStats.forEach(([label,value])=>{const x=document.createElement('div');x.className='mail-stat';x.innerHTML='<strong>'+encodeText(fmt(Number(value)))+'</strong><span>'+encodeText(label)+'</span>';sg.appendChild(x)});panel.appendChild(sg)}
 const list=document.createElement('div');list.className='mail-list';
 if(!rows.length){const empty=document.createElement('div');empty.className='mail-empty';empty.textContent='No hay conversaciones que coincidan con esta consulta.';list.appendChild(empty)}
 rows.forEach(row=>{
  const item=document.createElement('article');item.className='mail-item';
  const attention=Boolean(row?.requires_attention),urgent=cleanDisplay(row?.urgency).toLowerCase()==='high';
  if(attention)item.classList.add('attention');if(urgent)item.classList.add('urgent');
  const top=document.createElement('div');top.className='mail-item-top';
  const sender=document.createElement('div');sender.className='mail-sender';sender.textContent=mailSender(row);top.appendChild(sender);
  const when=document.createElement('time');when.className='mail-time';when.textContent=formatMailDate(row?.received_at||row?.receivedDateTime||row?.received);top.appendChild(when);item.appendChild(top);
  const subject=document.createElement('div');subject.className='mail-subject';subject.textContent=cleanDisplay(row?.subject)||'(sin asunto)';item.appendChild(subject);
  const meta=document.createElement('div');meta.className='mail-meta';
  const state=mailStateLabel(row?.mail_state);if(state){const c=document.createElement('span');c.className='mail-chip state';c.textContent=state;meta.appendChild(c)}
  const unread=Number(row?.conversation_unread_count||1);if(unread>1){const c=document.createElement('span');c.className='mail-chip';c.textContent=unread+' no leídos';meta.appendChild(c)}
  if(row?.conversation_has_attachments===true||row?.has_attachments===true){const c=document.createElement('span');c.className='mail-chip attachment';c.textContent='Adjuntos';meta.appendChild(c)}
  if(urgent){const c=document.createElement('span');c.className='mail-chip urgent';c.textContent='Prioridad alta';meta.appendChild(c)}
  item.appendChild(meta);
  const action=cleanDisplay(row?.requested_action);if(action){const a=document.createElement('div');a.className='mail-action';a.innerHTML='<span>Acción</span><strong>'+encodeText(action)+'</strong>';item.appendChild(a)}
  list.appendChild(item)
 });
 panel.appendChild(list);wrap.appendChild(panel);return true
}
function selectTableColumns(cfg,kind){
 if(!cfg||!Array.isArray(cfg.rows))return cfg;
 const rows=cfg.rows,defined=(Array.isArray(cfg.columns)?cfg.columns:[]).filter(c=>c&&c.key);
 if(!defined.length)return cfg;
 const prefs={
  vacaciones:['Empleado','Nombre','FechaInicio','FechaFin','Dias','Días','Estado','Departamento'],
  ausencias:['Empleado','Nombre','Tipo','FechaInicio','FechaFin','Dias','Días','Estado','Departamento'],
  nominas:['Empleado','Nombre','Periodo','periodo','Fecha','NombreArchivo','Documento','Estado'],
  list:[]
 };
 const wanted=prefs[kind]||[];if(!wanted.length)return cfg;
 const keysLower=new Set(wanted.map(x=>String(x).toLowerCase()));
 let cols=defined.filter(c=>keysLower.has(String(c.key).toLowerCase())||keysLower.has(String(c.label||'').toLowerCase()));
 if(!cols.length){const technical=/^(id|guid|scope|source|url|weburl|fileurl|conversation|_)/i;cols=defined.filter(c=>!technical.test(String(c.key))).slice(0,6)}
 return {...cfg,columns:cols,title:cfg.title||({vacaciones:'Vacaciones',ausencias:'Bajas y ausencias',nominas:'Nóminas'}[kind]||'Detalle')}
}
function renderDomainTable(data,wrap,kind){
 const cfg=data?.table;if(!cfg||!Array.isArray(cfg.rows))return false;
 renderGenericTable(selectTableColumns(cfg,kind),wrap);return true
}
function renderResultHeader(kind,wrap,data){
 const labels={turnos:['Turnos','Planificación operativa'],vacaciones:['Vacaciones','Periodos y personas'],ausencias:['Bajas y ausencias','Situación y periodos'],nominas:['Nóminas','Información salarial disponible'],documents:['Documentos','Archivos y evidencias'],analytics:['Análisis','Indicadores y comparativas'],web:['Información externa','Fuentes consultadas'],list:['Resultados','Detalle estructurado'],noticias:['Noticias','Prensa y comunicados corporativos']};
 const pair=labels[kind];if(!pair)return;
 const h=document.createElement('div');h.className='adaptive-result-head';h.innerHTML='<div><strong>'+encodeText(pair[0])+'</strong><span>'+encodeText(pair[1])+'</span></div>';wrap.appendChild(h)
}
function analyticsPeriodLabel(report){
 const p=report?.periodo||{};
 return cleanDisplay(p.label)||[cleanDisplay(p.desde),cleanDisplay(p.hasta)].filter(Boolean).join(' → ')
}
function analyticsRows(data){
 return Array.isArray(data?.table?.rows)?data.table.rows:[]
}
function analyticsColumns(data){
 const cols=Array.isArray(data?.table?.columns)?data.table.columns:[];
 if(cols.length)return cols.map(c=>({key:c.key,label:cleanDisplay(c.label)||prettyKey(c.key)}));
 const row=analyticsRows(data)[0];if(!row||typeof row!=='object')return [];
 return Object.keys(row).map(k=>({key:k,label:prettyKey(k)}))
}
function metricLabel(k){
 const map={
  PlantillaActiva:'Plantilla activa',PersonasVacaciones:'Personas de vacaciones',EmpleadosVacaciones:'Empleados de vacaciones',SolicitudesVacaciones:'Solicitudes de vacaciones',
  EmpleadosConBaja:'Empleados con baja',DiasBajaAcumulados:'Días de baja',DuracionMediaBaja:'Duración media de baja',HorasTrabajoCalculables:'Horas de trabajo',
  JornadasPublicadas:'Jornadas publicadas',JornadasTrabajo:'Jornadas de trabajo',SaldoMedioActual:'Saldo medio',SaldosNegativos:'Saldos negativos',
  HorasETT:'Horas ETT',PersonasETT:'Personas ETT',CosteHistoricoETT:'Coste ETT',TurnosVinculacionPct:'Vinculación turnos',EdadMedia:'Edad media',EmpleadosConEdad:'Empleados con edad'
 };
 return map[k]||prettyKey(k)
}
function metricUnit(k){
 if(/Pct$/i.test(k))return '%';
 if(/Horas/i.test(k))return 'h';
 if(/Dias|Duracion/i.test(k))return 'días';
 if(/Coste/i.test(k))return '€';
 if(/Saldo/i.test(k))return 'días';
 if(/EdadMedia/i.test(k))return 'años';
 return ''
}
function renderAnalyticsReportHeader(data,wrap){
 const report=data?.report;if(!report||typeof report!=='object')return false;
 const dep=cleanDisplay(report.departamento)||'People Analytics';
 const period=analyticsPeriodLabel(report);
 const section=document.createElement('section');section.className='analytics-report-head';
 section.innerHTML='<div class="analytics-report-icon" aria-hidden="true">◫</div><div class="analytics-report-copy"><span>People Analytics</span><strong>'+encodeText(dep)+'</strong><small>'+encodeText(period||'Informe histórico')+'</small></div><div class="analytics-report-badge">Informe</div>';
 wrap.appendChild(section);return true
}
function renderAnalyticsDepartmentCompare(data,wrap){
 const rows=analyticsRows(data);if(rows.length!==2||!rows.every(x=>x&&typeof x==='object'&&('Departamento'in x)))return false;
 const excluded=new Set(['Departamento']);
 const keys=Object.keys(rows[0]).filter(k=>!excluded.has(k)&&rows.some(r=>r[k]!==undefined&&r[k]!==null&&r[k]!==''));
 if(keys.length<2)return false;
 const panel=document.createElement('section');panel.className='analytics-compare';
 const head=document.createElement('div');head.className='analytics-compare-head';head.innerHTML='<div><span>Comparativa</span><strong>'+encodeText(cleanDisplay(rows[0].Departamento))+' <i>vs</i> '+encodeText(cleanDisplay(rows[1].Departamento))+'</strong></div><small>'+keys.length+' indicadores</small>';panel.appendChild(head);
 const grid=document.createElement('div');grid.className='analytics-compare-grid';
 keys.slice(0,14).forEach(k=>{const item=document.createElement('div');item.className='analytics-compare-row';const a=rows[0][k],b=rows[1][k],u=metricUnit(k);item.innerHTML='<div class="analytics-compare-value left"><strong>'+encodeText(displayValue(a))+'</strong><small>'+encodeText(u)+'</small></div><div class="analytics-compare-metric">'+encodeText(metricLabel(k))+'</div><div class="analytics-compare-value right"><strong>'+encodeText(displayValue(b))+'</strong><small>'+encodeText(u)+'</small></div>';grid.appendChild(item)});
 panel.appendChild(grid);wrap.appendChild(panel);return true
}
function renderAnalyticsAgeBands(data,wrap){
 const rows=analyticsRows(data);if(!rows.length||!rows.every(x=>x&&x.TramoEdad!==undefined&&x.Empleados!==undefined))return false;
 const panel=document.createElement('section');panel.className='analytics-bars-panel';panel.innerHTML='<div class="analytics-section-label"><span>Distribución</span><strong>Plantilla por tramos de edad</strong></div>';
 const max=Math.max(1,...rows.map(x=>Number(x.Empleados)||0));const bars=document.createElement('div');bars.className='analytics-age-bars';
 rows.forEach(x=>{const n=Number(x.Empleados)||0;const row=document.createElement('div');row.className='analytics-age-row';row.innerHTML='<span>'+encodeText(cleanDisplay(x.TramoEdad))+'</span><div><i style="width:'+Math.max(2,n/max*100)+'%"></i></div><strong>'+encodeText(fmt(n))+'</strong>';bars.appendChild(row)});
 panel.appendChild(bars);wrap.appendChild(panel);return true
}
function renderAnalyticsRanking(data,wrap){
 const rows=analyticsRows(data);if(!rows.length||!rows.every(x=>x&&x.Departamento!==undefined&&x.EdadMedia!==undefined))return false;
 const sorted=[...rows].sort((a,b)=>(Number(a.EdadMedia)||0)-(Number(b.EdadMedia)||0));
 const panel=document.createElement('section');panel.className='analytics-ranking';panel.innerHTML='<div class="analytics-section-label"><span>Ranking</span><strong>Edad media por departamento</strong></div>';
 const list=document.createElement('div');list.className='analytics-ranking-list';
 sorted.slice(0,13).forEach((x,i)=>{const item=document.createElement('div');item.className='analytics-ranking-item';item.innerHTML='<span class="rank-pos">'+(i+1)+'</span><strong>'+encodeText(cleanDisplay(x.Departamento))+'</strong><span class="rank-value">'+encodeText(fmt(Number(x.EdadMedia)))+' <small>años</small></span>';list.appendChild(item)});panel.appendChild(list);wrap.appendChild(panel);return true
}
function renderAnalyticsSingleMetric(data,wrap){
 const rows=analyticsRows(data);if(rows.length!==1||!rows[0]||typeof rows[0]!=='object')return false;
 const row=rows[0],entries=Object.entries(row).filter(([k,v])=>k!=='Ambito'&&v!==null&&v!==undefined&&v!=='');if(!entries.length)return false;
 const panel=document.createElement('section');panel.className='analytics-single';
 const scope=document.createElement('div');scope.className='analytics-single-scope';scope.textContent=cleanDisplay(row.Ambito)||'Resultado';panel.appendChild(scope);
 const grid=document.createElement('div');grid.className='analytics-single-grid';entries.slice(0,4).forEach(([k,v])=>{const x=document.createElement('div');x.innerHTML='<span>'+encodeText(metricLabel(k))+'</span><strong>'+encodeText(displayValue(v))+'</strong><small>'+encodeText(metricUnit(k))+'</small>';grid.appendChild(x)});panel.appendChild(grid);wrap.appendChild(panel);return true
}
const MIA_CHART_PALETTE=['var(--coral)','var(--gold)','var(--burgundy)','var(--coral2)','var(--gold2)','var(--success)'];
function chartSeriesValues(chart){const s=(Array.isArray(chart.series)?chart.series:[])[0];return Array.isArray(s?.values)?s.values.map(v=>Number(v)||0):[]}
function renderDonutChart(chart,box){
 const labels=Array.isArray(chart.labels)?chart.labels:[],values=chartSeriesValues(chart);
 const total=values.reduce((a,b)=>a+Math.abs(b),0);if(!total)return;
 let offset=0;const slices=values.map((v,i)=>{const start=offset/total*100;offset+=Math.abs(v);const end=offset/total*100;return MIA_CHART_PALETTE[i%MIA_CHART_PALETTE.length]+' '+start.toFixed(2)+'% '+end.toFixed(2)+'%'}).join(',');
 const layout=document.createElement('div');layout.className='mia-chart-donut-layout';
 const donut=document.createElement('div');donut.className='mia-chart-donut';donut.style.background='conic-gradient('+slices+')';donut.innerHTML='<span><b>'+encodeText(fmt(total))+'</b></span>';layout.appendChild(donut);
 const legend=document.createElement('div');legend.className='mia-chart-legend';
 values.forEach((v,i)=>{const pct=total?Math.round(Math.abs(v)/total*100):0;const row=document.createElement('div');row.innerHTML='<i style="background:'+MIA_CHART_PALETTE[i%MIA_CHART_PALETTE.length]+'"></i><span>'+encodeText(cleanDisplay(labels[i])||'—')+'</span><b>'+encodeText(fmt(v))+' <small>'+pct+'%</small></b>';legend.appendChild(row)});
 layout.appendChild(legend);box.appendChild(layout)
}
function renderBarChart(chart,box){
 const labels=Array.isArray(chart.labels)?chart.labels:[],values=chartSeriesValues(chart);if(!labels.length)return;
 const max=Math.max(1,...values.map(v=>Math.abs(v)));const list=document.createElement('div');list.className='mia-chart-bars';
 labels.forEach((label,i)=>{const v=values[i]||0;const row=document.createElement('div');row.className='mia-chart-bar-row';row.innerHTML='<span>'+encodeText(cleanDisplay(label))+'</span><div class="mia-chart-bar-track"><div class="mia-chart-bar-fill" style="width:'+Math.max(2,Math.abs(v)/max*100)+'%"></div></div><strong>'+encodeText(fmt(v))+'</strong>';list.appendChild(row)});
 box.appendChild(list)
}
function renderLineChart(chart,box){
 const labels=Array.isArray(chart.labels)?chart.labels:[],series=Array.isArray(chart.series)?chart.series:[];if(!series.length)return;
 const allValues=series.flatMap(s=>Array.isArray(s.values)?s.values.map(v=>Number(v)||0):[]);if(!allValues.length)return;
 const max=Math.max(...allValues),min=Math.min(0,...allValues),w=320,h=120,pad=10;
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.setAttribute('class','mia-chart-line-svg');svg.setAttribute('preserveAspectRatio','none');
 series.forEach((s,si)=>{const vals=Array.isArray(s.values)?s.values:[];if(!vals.length)return;const step=(w-2*pad)/Math.max(1,vals.length-1);
  const pts=vals.map((v,i)=>{const x=pad+i*step,y=h-pad-((Number(v)||0-min)/((max-min)||1))*(h-2*pad);return x+','+y}).join(' ');
  const poly=document.createElementNS('http://www.w3.org/2000/svg','polyline');poly.setAttribute('points',pts);poly.setAttribute('fill','none');poly.setAttribute('stroke',MIA_CHART_PALETTE[si%MIA_CHART_PALETTE.length]);poly.setAttribute('stroke-width','2.5');poly.setAttribute('stroke-linecap','round');poly.setAttribute('stroke-linejoin','round');svg.appendChild(poly)
 });
 box.appendChild(svg);
 if(labels.length){const axis=document.createElement('div');axis.className='mia-chart-line-axis';labels.forEach(l=>{const s=document.createElement('span');s.textContent=cleanDisplay(l);axis.appendChild(s)});box.appendChild(axis)}
}
function renderCharts(data,wrap){
 const charts=Array.isArray(data?.charts)?data.charts:[];if(!charts.length)return false;
 const panel=document.createElement('section');panel.className='mia-charts-panel';
 charts.forEach(chart=>{
  if(!chart||typeof chart!=='object')return;
  const box=document.createElement('div');box.className='mia-chart-box';
  const head=document.createElement('div');head.className='mia-chart-title';head.textContent=cleanDisplay(chart.title)||'Gráfico';box.appendChild(head);
  const type=cleanDisplay(chart.type);
  if(type==='donut')renderDonutChart(chart,box);else if(type==='line')renderLineChart(chart,box);else renderBarChart(chart,box);
  panel.appendChild(box)
 });
 wrap.appendChild(panel);return true
}
// ---------------------------------------------------------------- Job Manager (Fase H)
// Integra el mismo backend ya construido en la Fase G (`mia.reporting.job_manager`, endpoints
// `/api/jobs/...`): nunca se simula el progreso con un temporizador visual — cada actualización viene
// de una consulta real al servidor, igual tanto para la tarjeta que aparece en el chat como para el
// panel de historial (misma tarjeta reutilizada; un trabajo puede estar representado por ambas a la
// vez y las dos se mantienen sincronizadas desde el mismo sondeo).
// Script clasico (no type="module"): no puede hacer `import` de auth-gate.js, por eso lee el
// token de la cuenta MSAL activa a traves del global que esa capa ya expone (window.miaGetAccessToken).
// Si el login esta desactivado (modo dev/easyauth) ese global no existe o devuelve null.
async function miaAuthHeaders(){try{const t=typeof window.miaGetAccessToken==='function'?await window.miaGetAccessToken():null;return t?{Authorization:'Bearer '+t}:{}}catch(_){return {}}}
const MIA_JOBS_API='/api/jobs';
const MIA_JOB_POLL_MS=2500;
const miaJobCardsByJob=new Map();
const miaJobsState=new Map();
const miaJobPollTimers=new Map();
const miaJobFirstSeenAt=new Map();
function jobStatusLabel(status){
 const map={queued:'En cola',running:'En curso',completed:'Completado',failed:'Error',cancelled:'Cancelado'};
 return map[status]||cleanDisplay(status)||'—'
}
function registerJobCard(jobId,card){let set=miaJobCardsByJob.get(jobId);if(!set){set=new Set();miaJobCardsByJob.set(jobId,set)}set.add(card);if(!miaJobFirstSeenAt.has(jobId))miaJobFirstSeenAt.set(jobId,Date.now())}
function updateJobsBadge(jobs){const badge=document.getElementById('jobsBadge');if(!badge)return;const list=jobs||Array.from(miaJobsState.values());const active=list.filter(j=>j.status==='queued'||j.status==='running').length;if(active>0){badge.style.display='';badge.textContent=String(active)}else badge.style.display='none'}
function paintJobCard(card,job){
 const statusEl=card.querySelector('.mia-job-status');statusEl.className='mia-job-status mia-job-status-'+encodeText(job.status||'');statusEl.textContent=jobStatusLabel(job.status);
 card.querySelector('.mia-job-meta').textContent=[cleanDisplay(job.periodo),cleanDisplay(job.formato)?cleanDisplay(job.formato).toUpperCase():''].filter(Boolean).join(' · ')||'Análisis económico de nóminas';
 card.querySelector('.mia-job-progress-fill').style.width=(Math.max(0,Math.min(1,Number(job.progress)||0))*100)+'%';
 card.querySelector('.mia-job-message').textContent=cleanDisplay(job.progress_message)||'';
 const actions=card.querySelector('.mia-job-actions');actions.innerHTML='';
 if(job.status==='queued'||job.status==='running'){const b=document.createElement('button');b.type='button';b.className='mia-job-cancel';b.textContent='Cancelar trabajo';b.addEventListener('click',()=>cancelJob(job.job_id));actions.appendChild(b)}
 if(job.status==='completed'&&job.report_id){const a=document.createElement('a');a.className='mia-job-download';a.href='/api/reports/'+encodeURIComponent(job.report_id);a.setAttribute('download','');a.textContent='↓ Descargar informe';actions.appendChild(a)}
 let note=card.querySelector('.mia-job-note');
 const firstSeen=miaJobFirstSeenAt.get(job.job_id)||Date.now(),elapsed=Date.now()-firstSeen;
 let noteText='';
 if(job._pollError)noteText='No se ha podido consultar el estado del trabajo. Reintentando…';
 else if(job.status==='failed')noteText='No se ha podido completar: '+(cleanDisplay(job.error_message)||'error desconocido');
 else if(job.status==='cancelled')noteText='Trabajo cancelado.';
 else if(job.status==='queued'&&elapsed>120000)noteText='Sigue en cola; está tardando más de lo habitual.';
 else if(job.status==='running'&&elapsed>240000)noteText='Sigue en curso; los volúmenes grandes pueden tardar varios minutos.';
 if(noteText){if(!note){note=document.createElement('div');note.className='mia-job-note';card.appendChild(note)}note.textContent=noteText}
 else if(note)note.remove();
}
function buildJobCard(job){
 const card=document.createElement('div');card.className='mia-job-card';card.dataset.jobId=job.job_id;
 card.innerHTML='<div class="mia-job-head"><strong>Informe en segundo plano</strong><span class="mia-job-status"></span></div><div class="mia-job-meta"></div><div class="mia-job-progress-track"><div class="mia-job-progress-fill"></div></div><div class="mia-job-message"></div><div class="mia-job-actions"></div>';
 paintJobCard(card,job);return card
}
function updateAllCardsForJob(jobId,job,pollError){
 miaJobsState.set(jobId,job);const set=miaJobCardsByJob.get(jobId);
 if(set)for(const card of Array.from(set)){if(!card.isConnected){set.delete(card);continue}paintJobCard(card,{...job,_pollError:Boolean(pollError)})}
 if(set&&!set.size)miaJobCardsByJob.delete(jobId);
 updateJobsBadge()
}
function stopJobPolling(jobId){const t=miaJobPollTimers.get(jobId);if(t){clearTimeout(t);miaJobPollTimers.delete(jobId)}}
async function pollJobOnce(jobId){
 try{
  const res=await fetch(MIA_JOBS_API+'/'+encodeURIComponent(jobId),{headers:await miaAuthHeaders()});if(!res.ok)throw new Error('HTTP '+res.status);
  const job=await res.json();updateAllCardsForJob(jobId,job,false);
  if(job.status==='queued'||job.status==='running')miaJobPollTimers.set(jobId,setTimeout(()=>pollJobOnce(jobId),MIA_JOB_POLL_MS));else stopJobPolling(jobId)
 }catch(e){
  const prev=miaJobsState.get(jobId);if(prev)updateAllCardsForJob(jobId,prev,true);
  miaJobPollTimers.set(jobId,setTimeout(()=>pollJobOnce(jobId),MIA_JOB_POLL_MS*2))
 }
}
function ensureJobPolling(jobId){if(!miaJobPollTimers.has(jobId))pollJobOnce(jobId)}
async function cancelJob(jobId){
 try{
  const res=await fetch(MIA_JOBS_API+'/'+encodeURIComponent(jobId),{method:'DELETE',headers:await miaAuthHeaders()});if(!res.ok)throw new Error('HTTP '+res.status);
  const job=await res.json();updateAllCardsForJob(jobId,job,false);
  if(job.status!=='queued'&&job.status!=='running')stopJobPolling(jobId)
 }catch(e){miaToast('No se ha podido cancelar el trabajo. Inténtalo de nuevo.')}
}
function renderJob(data,wrap){
 const job=data?.job;if(!job||typeof job!=='object'||!job.job_id)return false;
 const full={progress:0,progress_message:'',report_id:null,error_message:null,cancel_requested:false,...job};
 const card=buildJobCard(full);wrap.appendChild(card);registerJobCard(job.job_id,card);
 miaJobsState.set(job.job_id,full);updateJobsBadge();
 if(full.status==='queued'||full.status==='running')ensureJobPolling(job.job_id);
 return true
}
function renderJobsPanelList(jobs){
 const body=document.getElementById('jobsPanelBody');if(!body)return;body.innerHTML='';
 if(!jobs.length){body.innerHTML='<div class="jobs-panel-empty">No tienes trabajos en segundo plano todavía.</div>';return}
 jobs.forEach(job=>{const card=buildJobCard(job);registerJobCard(job.job_id,card);body.appendChild(card);if(job.status==='queued'||job.status==='running')ensureJobPolling(job.job_id)})
}
async function refreshJobsHistory(){
 try{
  const res=await fetch(MIA_JOBS_API,{headers:await miaAuthHeaders()});if(!res.ok)throw new Error('HTTP '+res.status);
  const jobs=await res.json();jobs.forEach(j=>miaJobsState.set(j.job_id,j));
  renderJobsPanelList(jobs);updateJobsBadge(jobs);
  jobs.filter(j=>j.status==='queued'||j.status==='running').forEach(j=>ensureJobPolling(j.job_id));
  return jobs
 }catch(e){
  const body=document.getElementById('jobsPanelBody');if(body)body.innerHTML='<div class="jobs-panel-empty">No se ha podido cargar el historial de trabajos.</div>';
  return []
 }
}
(function initJobsWidget(){
 const btn=document.getElementById('jobsBtn'),panel=document.getElementById('jobsPanel');if(!btn||!panel)return;
 btn.addEventListener('click',()=>{
  const opening=!panel.classList.contains('open');panel.classList.toggle('open',opening);
  panel.setAttribute('aria-hidden',opening?'false':'true');btn.setAttribute('aria-expanded',opening?'true':'false');
  if(opening)refreshJobsHistory()
 });
})();
function renderAnalyticsWorkspace(data,r,wrap){
 const out={tableHandled:false};
 renderAnalyticsReportHeader(data,wrap);
 if(renderAnalyticsDepartmentCompare(data,wrap)){out.tableHandled=true;return out}
 if(renderAnalyticsAgeBands(data,wrap)){out.tableHandled=true;return out}
 if(renderAnalyticsRanking(data,wrap)){out.tableHandled=true;return out}
 if(renderAnalyticsSingleMetric(data,wrap)){out.tableHandled=true;return out}
 return out
}
function renderData(r,msg){
 const data=r.data||{};
 const kind=detectResultKind(r,data);applyResultKind(msg,kind);
 const nativeEmployeePresentation=(data.presentation&&typeof data.presentation==='object'&&data.presentation.schema==='mia.employee360.presentation')?data.presentation:null;
 const employee360Root=(data.employee360&&typeof data.employee360==='object')?data.employee360:null;
 const looksLikeEmployee360=!!(employee360Root||data.employee360_version||(data.empleado&&typeof data.empleado==='object'&&(data.turnos_inteligentes||data.vacaciones_inteligentes||data.datos_laborales)));
 const presentation=nativeEmployeePresentation||(looksLikeEmployee360?synthesizeEmployee360Presentation(data):null);
 const cards=Array.isArray(data.cards)?data.cards:[],visual=Array.isArray(r.visualizations)?r.visualizations:[],actions=Array.isArray(r.actions)?r.actions:[],turnos=Array.isArray(data.turnos)?data.turnos:[],table=data.table,documents=Array.isArray(data.documents)?data.documents:(data.document?[data.document]:[]);
 const mail=mailPayload(data);
 const newsRows=Array.isArray(data.news_rows)?data.news_rows:[];
 const hasAny=kind==='mail'?Boolean(mail.rows.length||Object.keys(mail.summary).length):Boolean(presentation||cards.length||visual.length||actions.length||turnos.length||table||documents.length||newsRows.length||Array.isArray(data.comparacion)||(r.sources||[]).length||Array.isArray(data.web_sources)||data.alertas_calidad||data.insights||data.query_summary||(data.job&&typeof data.job==='object'&&data.job.job_id));
 if(!hasAny)return;
 const wrap=document.createElement('div');wrap.className='results results--'+kind;wrap.dataset.resultKind=kind;
 renderResponseMeta(r,wrap);renderQuerySummary(data,wrap);
 if(kind==='mail'){
  renderMailWorkspace(data,r,wrap);
  const renderedWebSources=renderWebSources(data,wrap);const src=(r.sources||[]).map(cleanDisplay).filter(Boolean);if(src.length&&!renderedWebSources){const d=document.createElement('details');d.className='sources-details';d.innerHTML='<summary>Ver fuentes consultadas</summary><div>'+encodeText(src.join(' · '))+'</div>';wrap.appendChild(d)}
  msg.appendChild(wrap);convo.scrollTop=convo.scrollHeight;return
 }
 if(kind!=='employee360')renderResultHeader(kind,wrap,data);
 let analyticsState={tableHandled:false};
 if(kind==='analytics'){renderComparison(data,wrap);analyticsState=renderAnalyticsWorkspace(data,r,wrap)}
 let renderedEmployee360=false;
 if(presentation){
  try{renderedEmployee360=renderEmployee360Presentation(presentation,data,wrap)}
  catch(employeeUiError){console.error('[mIA Employee360 renderer]',employeeUiError);renderedEmployee360=renderEmployee360EmergencyCard(presentation,data,wrap,employeeUiError)}
 }
 if(!renderedEmployee360&&looksLikeEmployee360){renderedEmployee360=renderEmployee360EmergencyCard(presentation||synthesizeEmployee360Presentation(data),data,wrap,null)}
 if(!renderedEmployee360&&cards.length){const g=document.createElement('div');g.className='kpis';cards.forEach(c=>{const k=document.createElement('div');k.className='kpi';k.innerHTML=`<div><span class="v">${encodeText(fmt(c.value))}</span>${cleanDisplay(c.unit)?'<span class="u">'+encodeText(cleanDisplay(c.unit))+'</span>':''}</div><div class="l">${encodeText(cleanDisplay(c.label)||'Dato')}</div>`;g.appendChild(k)});wrap.appendChild(g)}
 if(kind==='documents')renderDocuments(data,wrap);
 else if(documents.length&&kind!=='employee360')renderDocuments(data,wrap);
 if(kind==='vacaciones'||kind==='ausencias'||kind==='nominas')renderDomainTable(data,wrap,kind);
 else if(kind==='analytics'){if(!analyticsState.tableHandled)renderGenericTable(table,wrap)}
 else if(kind!=='turnos'&&kind!=='employee360'&&kind!=='noticias')renderGenericTable(table,wrap);
 if(turnos.length){renderShiftTimeline(data,turnos,wrap);renderTurnsTable(data,turnos,wrap)}
 renderInsights(data,wrap);renderQuality(data,r,wrap);renderCharts(data,wrap);renderJob(data,wrap);
 visual.forEach(v=>{const p=document.createElement('div');p.className='viz';const h=document.createElement('div');h.className='viz-head';h.innerHTML='<strong>'+encodeText(cleanDisplay(v.title)||'Resumen')+'</strong><span>Visualización</span>';p.appendChild(h);const rows=(v.data||[]).map(x=>({label:cleanDisplay(x.label??x.Mes??''),value:Number(x.value??x.Horas??0)})).filter(x=>x.label);const max=Math.max(1,...rows.map(x=>Math.abs(x.value)));const b=document.createElement('div');b.className='bars';rows.forEach(x=>{const r0=document.createElement('div');r0.className='barrow';r0.innerHTML=`<span>${encodeText(x.label)}</span><div class="track"><div class="fill" style="width:${Math.max(1,Math.abs(x.value)/max*100)}%"></div></div><strong>${encodeText(fmt(x.value))}</strong>`;b.appendChild(r0)});p.appendChild(b);wrap.appendChild(p)});
 if(actions.length){const a=document.createElement('div');a.className='actions';actions.forEach(x=>{if(!x.url)return;const t=cleanDisplay(x.type);if(!['download','open','open_document'].includes(t))return;if(documents.length&&t==='open_document')return;const l=document.createElement('a');l.className='action-btn';l.href=x.url;if(t==='download'){l.setAttribute('download','');l.textContent='↓ '+(cleanDisplay(x.label)||'Descargar')}else{l.target='_blank';l.rel='noopener noreferrer';l.textContent='↗ '+(cleanDisplay(x.label)||'Abrir documento')}a.appendChild(l)});if(a.childNodes.length)wrap.appendChild(a)}
 const renderedWebSources=renderWebSources(data,wrap);const src=(r.sources||[]).map(cleanDisplay).filter(Boolean);if(src.length&&!renderedWebSources){const d=document.createElement('details');d.className='sources-details';d.innerHTML='<summary>Ver fuentes consultadas</summary><div>'+encodeText(src.join(' · '))+'</div>';wrap.appendChild(d)}msg.appendChild(wrap);convo.scrollTop=convo.scrollHeight
}
function safeLocalGet(k){try{return localStorage.getItem(k)}catch(_){return null}}
function safeLocalSet(k,v){try{localStorage.setItem(k,v)}catch(_){}}
function voiceScore(v){
 const n=(v.name||'').toLowerCase(),l=(v.lang||'').toLowerCase();let s=0;
 if(l==='es-es')s+=120;else if(l.startsWith('es'))s+=70;
 if(n.includes('natural'))s+=110;if(n.includes('neural'))s+=100;if(n.includes('online'))s+=55;
 if(n.includes('elvira'))s+=95;if(n.includes('dalia'))s+=85;if(n.includes('helena'))s+=75;if(n.includes('monica')||n.includes('mónica'))s+=65;if(n.includes('lucia')||n.includes('lucía'))s+=60;
 if(n.includes('google español')||n.includes('google spanish'))s+=45;if(n.includes('microsoft'))s+=30;
 if(n.includes('male')||n.includes('alvaro')||n.includes('álvaro')||n.includes('jorge'))s-=18;
 return s
}
function loadVoices(){
 if(!('speechSynthesis'in window))return;
 const lang=((context.locale||miaProfile.locale||'es-ES').split('-')[0]||'es').toLowerCase(),all=speechSynthesis.getVoices();
 voices=all.filter(v=>(v.lang||'').toLowerCase().startsWith(lang));if(!voices.length)voices=all;voices.sort((a,b)=>voiceScore(b)-voiceScore(a));
 voiceSelect.innerHTML='';if(!voices.length){voiceSelect.innerHTML='<option>Voz del sistema</option>';selectedVoice=null;return}
 voices.forEach((v,i)=>{const o=document.createElement('option');o.value=i;o.textContent=v.name+' · '+v.lang;voiceSelect.appendChild(o)});
 let idx=0;const saved=safeLocalGet(VOICE_PREF_KEY);if(saved){try{const p=JSON.parse(saved),j=voices.findIndex(v=>v.name===p.name&&v.lang===p.lang);if(j>=0)idx=j}catch(_){}}
 selectedVoice=voices[idx]||voices[0];voiceSelect.value=String(idx)
}
voiceSelect.addEventListener('change',()=>{selectedVoice=voices[Number(voiceSelect.value)]||null;if(selectedVoice)safeLocalSet(VOICE_PREF_KEY,JSON.stringify({name:selectedVoice.name,lang:selectedVoice.lang}))});
if('speechSynthesis'in window){speechSynthesis.onvoiceschanged=loadVoices;loadVoices();setTimeout(loadVoices,250);setTimeout(loadVoices,1200)}
function speechDateNatural(s){const months=['','enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];return String(s).replace(/\b(\d{1,2})\/(\d{1,2})\/(20\d{2})\b/g,(m,d,mo,y)=>months[+mo]?`${+d} de ${months[+mo]} de ${y}`:m)}
function prepareSpeechText(text){
 let s=String(text||'').replace(/\s+/g,' ').trim();if(!s)return '';
 s=s.replace(/\bmIA\b/gi,'Mía').replace(/\bCVDocs\b/gi,'documentos de currículum');
 s=s.replace(/\b(\d+)\s+CVs?\b/gi,'$1 currículums vitae').replace(/\bCVs\b/gi,'currículums vitae').replace(/\bCV\b/gi,'currículum vitae');
 s=s.replace(/\bRR\.?\s*HH\.?\b/gi,'recursos humanos').replace(/\bETT\b/g,'trabajo temporal').replace(/\bOCR\b/g,'reconocimiento óptico de caracteres');
 s=s.replace(/Turnos\.Tipo\s*=\s*Trabajo/gi,'un turno clasificado como trabajo').replace(/Tipo\s*=\s*Trabajo/gi,'tipo trabajo');
 s=speechDateNatural(s);s=s.replace(/\b(\d+)[.,](\d+)\s*%/g,'$1 coma $2 por ciento').replace(/\b(\d+)\s*%/g,'$1 por ciento');
 s=s.replace(/\s*[→=]\s*/g,', ').replace(/\s*\/\s*/g,' o ');return s
}
function splitSpeech(text){const clean=prepareSpeechText(text),parts=clean.match(/[^.!?;:]+[.!?;:]?/g)||[clean],out=[];let cur='';for(const p0 of parts){const p=p0.trim();if(!p)continue;if((cur+' '+p).trim().length>145&&cur){out.push(cur.trim());cur=p}else cur=(cur+' '+p).trim()}if(cur)out.push(cur.trim());return out}
function utteranceFor(text,rate=.97,pitch=1.01){const u=new SpeechSynthesisUtterance(text);u.lang=context.locale||miaProfile.locale||'es-ES';u.rate=rate;u.pitch=pitch;u.volume=.98;if(selectedVoice)u.voice=selectedVoice;return u}
function speakProgress(text,returnState){if(!speechEnabled||!('speechSynthesis'in window)||speechSynthesis.speaking)return;const u=utteranceFor(prepareSpeechText(text),.98,1.0);u.onstart=()=>setAvatarState('hablando');u.onend=()=>setAvatarState(returnState);speechSynthesis.speak(u)}
function speak(text,finalState='sonriendo'){
 if(!speechEnabled||!('speechSynthesis'in window)||!text){setAvatarState(finalState);return}speechSynthesis.cancel();const chunks=splitSpeech(text);let i=0;
 const next=()=>{if(i>=chunks.length){setAvatarState(finalState);return}const chunk=chunks[i++],last=/[!?]$/.test(chunk),u=utteranceFor(chunk,last?.99:.965,1.01);u.onstart=()=>setAvatarState('hablando');u.onend=()=>setTimeout(next,/[,;:]$/.test(chunk)?150:95);u.onerror=()=>setAvatarState(finalState);speechSynthesis.speak(u)};next()
}
soundToggle.addEventListener('click',()=>{speechEnabled=!speechEnabled;soundToggle.textContent=speechEnabled?'🔊':'🔇';if(!speechEnabled&&'speechSynthesis'in window)speechSynthesis.cancel()});
const MIA_RUNTIME={
  isLocal:['localhost','127.0.0.1'].includes(location.hostname),
  backendBase:null,
  gatewayBase:null
};
MIA_RUNTIME.backendBase=window.MIA_BACKEND_BASE||(MIA_RUNTIME.isLocal?`${location.protocol}//${location.hostname}:5001`:location.origin);
MIA_RUNTIME.gatewayBase=window.MIA_GATEWAY_BASE||(MIA_RUNTIME.isLocal?`${location.protocol}//${location.hostname}:5002`:location.origin);
const MIA_API = {
  llmEnabled: true,
  llmCandidates: ['/api/mia/v4/chat'],
  backendChat: '/api/mia/chat',
  backendStream: '/api/mia/chat/stream',
  voice: '/api/mia/voice'
};
function _pendingAttachmentIds(){return typeof window._getAttachmentIds==='function'?window._getAttachmentIds():[]}
async function callNaturalLlm(q){
 if(!MIA_API.llmEnabled)throw new Error('LLM disabled');let last=null;
 const ids=_pendingAttachmentIds();const ctxPayload={...miaProfile,...context};if(ids.length)ctxPayload.attachment_ids=ids;
 const authHeaders=await miaAuthHeaders();
 for(const url of MIA_API.llmCandidates){try{const ctrl=new AbortController(),to=setTimeout(()=>ctrl.abort(),120000);const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json; charset=utf-8','Accept':'application/json',...authHeaders},body:JSON.stringify({message:q,context:ctxPayload}),signal:ctrl.signal});clearTimeout(to);if(!res.ok){last=new Error('HTTP '+res.status);continue}const j=await res.json();if(j&&typeof j==='object')return j}catch(e){last=e}}
 throw last||new Error('LLM gateway unavailable')
}
function _chatPayload(q){const ids=_pendingAttachmentIds();const p={message:q,context:{...miaProfile,...context}};if(ids.length)p.attachment_ids=ids;return p}
async function fallbackChat(q){const res=await fetch(MIA_API.backendChat,{method:'POST',headers:{'Content-Type':'application/json; charset=utf-8','Accept':'application/json',...await miaAuthHeaders()},body:JSON.stringify(_chatPayload(q))});return await res.json()}
async function callBackendStream(q,prog){let finalResult=null;const res=await fetch(MIA_API.backendStream,{method:'POST',headers:{'Content-Type':'application/json; charset=utf-8','Accept':'application/x-ndjson',...await miaAuthHeaders()},body:JSON.stringify(_chatPayload(q))});if(!res.ok||!res.body)throw new Error('stream unavailable');const reader=res.body.getReader(),decoder=new TextDecoder('utf-8');let buf='';while(true){const {value,done}=await reader.read();buf+=decoder.decode(value||new Uint8Array(),{stream:!done});let pos;while((pos=buf.indexOf('\n'))>=0){const line=buf.slice(0,pos).trim();buf=buf.slice(pos+1);if(!line)continue;let ev;try{ev=JSON.parse(line)}catch(_){continue}if(ev.type==='progress')updateProgress(prog,ev);else if(ev.type==='result'){finalResult=ev.payload;break}}if(finalResult||done)break}return finalResult||{}}
async function ask(raw){
 let q=String(raw||input.value||'').trim();if(!q)return;
 const mailReply=window.miaMailWatch?.consumeMailPrompt(q);
 if(mailReply?.action==='dismiss'){window.miaSpeakMailNotification?.('De acuerdo, seguimos con lo que estábamos.');return}
 if(mailReply?.action==='summary'||mailReply?.action==='details'){
  if(mailReply.action==='details')window.miaAutoOpenNextMail=true;
  q=window.miaMailWatch.mailPromptQuery(mailReply.correo,mailReply.action);
 }
 if('speechSynthesis'in window)speechSynthesis.cancel();input.value='';addMsg('Tú',q,'user');lastProgressSpoken=false;setAvatarState('pensando','Interpretando tu consulta y preparando una respuesta natural.');const prog=createProgress();prog.title.textContent='Entendiendo y consultando…';prog.detail.textContent='mIA está combinando interpretación conversacional y datos validados.';let finalResult=null;
 try{
  finalResult=await callNaturalLlm(q);
 }catch(llmErr){
  try{prog.title.textContent='Consultando datos validados…';prog.detail.textContent='La capa LLM no está disponible; uso directo del backend.';finalResult=await callBackendStream(q,prog)}catch(streamErr){try{finalResult=await fallbackChat(q)}catch(e){prog.row.remove();document.getElementById('backendStatus').textContent='sin conexión';setAvatarState('avisando','No puedo conectar con el servidor.');addMsg('mIA','Ahora mismo no puedo conectar con el servidor. No voy a inventar una respuesta: inténtalo de nuevo cuando la conexión esté disponible.','mia','avisando');return}}
 }
 prog.row.remove();window._clearAttachments?.();const r=finalResult||{};context=r.context||context;const finalState=canonicalState(r.avatar_state||r.avatar?.state||(r.status==='error'?'avisando':'sonriendo'));const answer=r.answer||r.natural_answer||r.response||'He terminado la consulta.';const m=addMsg('mIA',answer,'mia',finalState);renderLlmBadge(r,m.msg);renderData(r,m.msg);if(r.status==='error')setAvatarState('avisando');else speak(r.speech_text||answer,finalState)
}
send.addEventListener('click',()=>ask());input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask()}});
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(SR){recognition=new SR();recognition.lang=context.locale||miaProfile.locale;recognition.interimResults=true;recognition.continuous=false;recognition.maxAlternatives=3;recognition.onstart=()=>{recognitionFinalSent=false;if('speechSynthesis'in window)speechSynthesis.cancel();setAvatarState('escuchando','Te escucho. Habla con naturalidad.');};recognition.onresult=e=>{let finalText='',interim='';for(let i=e.resultIndex;i<e.results.length;i++){const t=e.results[i]?.[0]?.transcript||'';if(e.results[i].isFinal)finalText+=t+' ';else interim+=t+' '}input.value=(finalText||interim).trim();if(finalText.trim()&&!recognitionFinalSent){recognitionFinalSent=true;ask(finalText.trim())}};recognition.onerror=()=>setAvatarState('reposo','No te he entendido bien. Puedes repetirlo o escribirlo.');recognition.onend=()=>{if(currentState==='escuchando')setAvatarState('reposo','Lista para ayudarte.');};mic.addEventListener('click',()=>{try{recognition.start()}catch(_){}})}else mic.addEventListener('click',()=>addMsg('mIA','El reconocimiento de voz no está disponible en este navegador.','mia','avisando'));
async function boot(){setAvatarState('reposo','Lista para ayudarte.');let backend=false,llm=false;try{const r=await fetch('/api/version');backend=r.ok}catch(_){}try{const r=await fetch('/api/mia/v4/health');llm=r.ok}catch(_){}const label=document.getElementById('backendStatus');if(backend&&llm)label.textContent='mIA conectada';else if(backend)label.textContent='mIA · LLM no disponible';else label.textContent='sin conexión';if(backend)refreshJobsHistory()}boot();


// =============================================================================
// mIA 2D V1 - DUAL WORLD + SHARED SESSION + ELEVENLABS VOICE
// =============================================================================
// V5.2.9: contexto aislado 2D. El antiguo localStorage compartido no se consulta.
// El cambio de mundo transfiere el contexto una única vez, en la misma pestaña.
const MIA_WORLD_2D_KEY='mia.world.2d.session.v529';
const MIA_WORLD_HANDOFF_KEY='mia.world.pending-handoff.v529';
let miaSessionRestoring=false;
let miaCurrentAudio=null;
let miaAudioUrl=null;

function miaGreetingForNow(){
  const h=new Date().getHours();
  if(h>=6&&h<14)return 'Buenos días';
  if(h>=14&&h<21)return 'Buenas tardes';
  return 'Buenas noches';
}
function miaToast(text){
  const layer=document.getElementById('toastLayer');if(!layer)return;
  const t=document.createElement('div');t.className='mia-toast';t.textContent=String(text||'');layer.appendChild(t);
  setTimeout(()=>{t.style.opacity='';t.style.transform='translateY(7px)';setTimeout(()=>t.remove(),250)},2600);
}
function mia2dSafeObject(v){return v&&typeof v==='object'&&!Array.isArray(v)}
function mia2dRead(key){try{return JSON.parse(sessionStorage.getItem(key)||'null')}catch(_){return null}}
function mia2dInitialContext(){
  const transfer=mia2dRead(MIA_WORLD_HANDOFF_KEY);
  if(mia2dSafeObject(transfer)){
    const age=Date.now()-Number(transfer.at||0);
    if(transfer.from==='2d'||age<0||age>120000){
      try{sessionStorage.removeItem(MIA_WORLD_HANDOFF_KEY)}catch(_){}
    }else if((transfer.to==='any'||transfer.to==='2d')&&mia2dSafeObject(transfer.context)){
      try{sessionStorage.removeItem(MIA_WORLD_HANDOFF_KEY)}catch(_){}
      return transfer.context;
    }
  }
  const own=mia2dRead(MIA_WORLD_2D_KEY);
  return mia2dSafeObject(own?.context)?own.context:{};
}
function miaSaveWorld2d(){
  try{sessionStorage.setItem(MIA_WORLD_2D_KEY,JSON.stringify({context,at:Date.now()}))}catch(_){}
}
function miaHandoff2d(to='any'){
  miaSaveWorld2d();
  try{sessionStorage.setItem(MIA_WORLD_HANDOFF_KEY,JSON.stringify({from:'2d',to,at:Date.now(),context}))}catch(_){}
}
context={...context,...mia2dInitialContext()};
const __miaAskBase=ask;
ask=async function(raw){try{return await __miaAskBase(raw)}finally{miaSaveWorld2d()}};
// Handoff exclusivamente al pulsar un enlace de NAVEGACIÓN entre mundos.
document.addEventListener('click',(event)=>{
  const a=event.target?.closest?.('a[href]');
  if(!a||a.download||(a.target&&a.target!=='_self')||event.defaultPrevented||
     event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  let url;try{url=new URL(a.href)}catch(_){return}
  if(url.origin!==location.origin||!/\/(?:index|mia-2d)\.html$|\/src\/worlds\/(?:2d|3d|hologram)\/index\.html$/i.test(url.pathname))return;
  const to=/\/src\/worlds\/hologram\/index\.html$/i.test(url.pathname)?'hologram':
     /\/src\/worlds\/3d\/index\.html$/i.test(url.pathname)?'3d':'any';
  miaHandoff2d(to);
},true);

// Voice output is generated server-side so the ElevenLabs key never reaches the browser.
async function miaElevenLabsSpeak(text,finalState='sonriendo',returnState=null){
  const prepared=prepareSpeechText(text);if(!speechEnabled||!prepared){setAvatarState(finalState);return}
  try{
    if(miaCurrentAudio){miaCurrentAudio.pause();miaCurrentAudio=null}
    if(miaAudioUrl){URL.revokeObjectURL(miaAudioUrl);miaAudioUrl=null}
    const res=await fetch(MIA_API.voice,{method:'POST',headers:{'Content-Type':'application/json; charset=utf-8','Accept':'audio/mpeg',...await miaAuthHeaders()},body:JSON.stringify({text:prepared,locale:context.locale||miaProfile.locale||'es-ES'})});
    if(!res.ok)throw new Error(`Voice HTTP ${res.status}`);
    const blob=await res.blob();miaAudioUrl=URL.createObjectURL(blob);const audio=new Audio(miaAudioUrl);miaCurrentAudio=audio;
    setVoiceStatus('ElevenLabs · voz mIA');
    audio.onplay=()=>setAvatarState('hablando','Te respondo con mi voz.');
    audio.onended=()=>{miaCurrentAudio=null;if(miaAudioUrl){URL.revokeObjectURL(miaAudioUrl);miaAudioUrl=null}setAvatarState(returnState||finalState)};
    audio.onerror=()=>{miaCurrentAudio=null;setAvatarState(returnState||finalState)};
    await audio.play();
  }catch(err){
    console.warn('[mIA ElevenLabs]',err);setVoiceStatus('Voz mIA · fallback del sistema');
    if('speechSynthesis'in window){
      speechSynthesis.cancel();const chunks=splitSpeech(prepared);let i=0;const next=()=>{if(i>=chunks.length){setAvatarState(returnState||finalState);return}const u=utteranceFor(chunks[i++],.97,1.01);u.onstart=()=>setAvatarState('hablando');u.onend=()=>next();u.onerror=()=>setAvatarState(returnState||finalState);speechSynthesis.speak(u)};next();
    }else setAvatarState(returnState||finalState)
  }
}

speak=function(text,finalState='sonriendo'){miaElevenLabsSpeak(text,finalState)};
speakProgress=function(text,returnState){if(!speechEnabled||miaCurrentAudio)return;miaElevenLabsSpeak(text,returnState||'concentrada',returnState||'concentrada')};
const miaMailSpeechQueue=[];let miaMailSpeechTimer=null;
function drainMiaMailSpeech(){
 miaMailSpeechTimer=null;if(!miaMailSpeechQueue.length||!speechEnabled)return;
 if(['pensando','concentrada','escuchando','hablando'].includes(currentState)||miaCurrentAudio||('speechSynthesis'in window&&speechSynthesis.speaking)){
  miaMailSpeechTimer=setTimeout(drainMiaMailSpeech,800);return;
 }
 const text=miaMailSpeechQueue.shift();void miaElevenLabsSpeak(text,'avisando','reposo').finally(()=>{if(miaMailSpeechQueue.length)miaMailSpeechTimer=setTimeout(drainMiaMailSpeech,250)});
}
window.miaSpeakMailNotification=(text)=>{if(!speechEnabled||!String(text||'').trim())return;miaMailSpeechQueue.push(String(text).slice(0,300));if(!miaMailSpeechTimer)drainMiaMailSpeech()};

// The existing toggle also controls the ElevenLabs audio element.
soundToggle.addEventListener('click',()=>{if(!speechEnabled&&miaCurrentAudio){miaCurrentAudio.pause();miaCurrentAudio=null}setVoiceStatus(speechEnabled?'ElevenLabs · voz mIA':'Voz desactivada')});

// Dynamic greeting in Spanish by default.
(function miaPaintGreeting(){
  const g=miaGreetingForNow();const eg=document.getElementById('greetingEyebrow'),wg=document.getElementById('welcomeGreeting');
  if(eg)eg.textContent=g.toUpperCase();if(wg)wg.textContent=`${g}. Soy mIA.`;
})();

// Suggested prompts.
document.querySelectorAll('[data-prompt]').forEach(btn=>btn.addEventListener('click',()=>ask(btn.dataset.prompt||'')));

// Switch to the 3D world without dropping session context.
window.addEventListener('beforeunload',miaSaveWorld2d);

// Avoid broken-image UI if avatar assets are temporarily unavailable.
[avatarA,avatarB].forEach(img=>img.addEventListener('error',()=>{img.style.visibility='hidden'}));
[avatarA,avatarB].forEach(img=>img.addEventListener('load',()=>{img.style.visibility='visible'}));

// Mobile virtual keyboard support.
if(window.visualViewport){
  const syncViewport=()=>{const wrap=document.querySelector('.composer-wrap-premium');if(!wrap)return;const covered=Math.max(0,window.innerHeight-(visualViewport.height+visualViewport.offsetTop));wrap.style.setProperty('--keyboard-offset',covered+'px');if(innerWidth<=680)wrap.style.bottom=covered+'px'};
  visualViewport.addEventListener('resize',syncViewport);visualViewport.addEventListener('scroll',syncViewport);syncViewport();
}

console.log('### mIA 2D V3 · adaptive modules · Mail V12.4.2 · ElevenLabs ready ###');

// ═══════════════════════════════════════════════════════════
//  MÓDULO DE ADJUNTOS
// ═══════════════════════════════════════════════════════════
(function initAttachments() {
  const attachBtn = document.getElementById('attachBtn');
  const fileInput = document.getElementById('fileInput');
  const previews = document.getElementById('attachmentPreviews');
  const inputEl = document.getElementById('input');
  if (!attachBtn || !fileInput || !previews) return;

  // Estado
  const pendingAttachments = []; // [{id, filename, status}]

  function mimeIcon(filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    if (['pdf'].includes(ext)) return '📄';
    if (['docx', 'doc', 'txt', 'md'].includes(ext)) return '📝';
    if (['xlsx', 'xls', 'csv'].includes(ext)) return '📊';
    if (['png', 'jpg', 'jpeg', 'webp'].includes(ext)) return '🖼️';
    return '📎';
  }

  function renderPreviews() {
    previews.innerHTML = '';
    if (!pendingAttachments.length) { previews.style.display = 'none'; return; }
    previews.style.display = 'flex';
    pendingAttachments.forEach((att, i) => {
      const chip = document.createElement('div');
      chip.className = 'attachment-chip' + (att.status === 'error' ? ' error' : att.status === 'uploading' ? ' uploading' : '');
      chip.innerHTML =
        '<span class="att-icon">' + mimeIcon(att.filename) + '</span>' +
        '<span class="att-name">' + encodeText(att.filename) + '</span>' +
        (att.status === 'uploading' ? '<span class="att-status">Procesando…</span>' : '') +
        (att.status === 'error' ? '<span class="att-status err">' + encodeText(att.error || 'Error') + '</span>' : '') +
        '<button type="button" class="att-remove" data-idx="' + i + '" title="Quitar">✕</button>';
      previews.appendChild(chip);
    });
    previews.querySelectorAll('.att-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.idx, 10);
        pendingAttachments.splice(idx, 1);
        renderPreviews();
      });
    });
  }

  async function uploadFile(file) {
    const idx = pendingAttachments.length;
    pendingAttachments.push({ id: null, filename: file.name, status: 'uploading' });
    renderPreviews();

    try {
      const form = new FormData();
      form.append('file', file, file.name);
      const resp = await fetch('/api/adjuntos/upload', { method: 'POST', headers: await miaAuthHeaders(), body: form });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Error al subir el archivo' }));
        pendingAttachments[idx] = { id: null, filename: file.name, status: 'error', error: err.detail || 'Error' };
      } else {
        const data = await resp.json();
        pendingAttachments[idx] = { id: data.attachment_id, filename: data.filename || file.name, status: 'ready', content_type: data.content_type };
      }
    } catch (e) {
      pendingAttachments[idx] = { id: null, filename: file.name, status: 'error', error: 'Error de red' };
    }
    renderPreviews();
  }

  // Botón adjuntar → abre selector de archivos
  attachBtn.addEventListener('click', () => fileInput.click());

  // Selección de archivo
  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files || []);
    fileInput.value = '';
    for (const f of files) await uploadFile(f);
  });

  // Drag & drop sobre el form
  const composer = document.getElementById('composer');
  if (composer) {
    composer.addEventListener('dragover', e => { e.preventDefault(); composer.classList.add('drag-over'); });
    composer.addEventListener('dragleave', () => composer.classList.remove('drag-over'));
    composer.addEventListener('drop', async e => {
      e.preventDefault(); composer.classList.remove('drag-over');
      const files = Array.from(e.dataTransfer?.files || []);
      for (const f of files) await uploadFile(f);
    });
  }

  // Paste de imagen desde clipboard
  document.addEventListener('paste', async e => {
    const items = Array.from(e.clipboardData?.items || []);
    for (const item of items) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) await uploadFile(new File([file], 'captura.png', { type: file.type }));
      }
    }
  });

  // Inyectar attachment_ids en el payload del chat
  // Intercepta el envío del formulario para añadir adjuntos
  window._getAttachmentIds = function () {
    return pendingAttachments
      .filter(a => a.status === 'ready' && a.id)
      .map(a => a.id);
  };
  window._clearAttachments = function () {
    pendingAttachments.length = 0;
    renderPreviews();
  };
})();
