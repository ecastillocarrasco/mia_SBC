/** Read-only calendar supplied by the backend. Shared by web worlds and bundled Desktop. */
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));


export function calendarPresentations(reply) {
  const native = Array.isArray(reply?.presentations) ? reply.presentations.filter(p => p?.type === 'calendar') : [];
  return native.length ? native : (Array.isArray(reply?.data?.calendars) ? reply.data.calendars : []);
}

function eventHtml(event, day) {
  const time = event.all_day ? 'Todo el día' : `${day > event.start_day ? 'Continúa' : event.start_time} – ${day < event.end_day ? 'continúa' : event.end_time}`;
  const meeting = typeof event.online_url === 'string' && /^https:\/\//i.test(event.online_url)
    ? `<a href="${esc(event.online_url)}" target="_blank" rel="noopener noreferrer">Abrir reunión online</a>` : '';
  return `<article class="mia-calendar-event"><time class="mia-calendar-time">${esc(time)}</time><details><summary>${esc(event.subject || 'Sin asunto')}</summary><dl><dt>Inicio</dt><dd>${esc(event.start_label)}</dd><dt>Fin</dt><dd>${esc(event.end_label)}</dd></dl>${meeting}</details>${event.location ? `<small>${esc(event.location)}</small>` : ''}<small>${esc(event.ref || '')}</small></article>`;
}

export function renderCalendar(presentation) {
  if (presentation?.confirmation) return confirmationHtml(presentation);
  const days = Array.isArray(presentation?.days) ? presentation.days : [];
  const events = (Array.isArray(presentation?.events) ? presentation.events : []).filter(e => e && e.status !== 'cancelled')
    .slice().sort((a,b) => String(a.start).localeCompare(String(b.start)));
  let html = `<section class="mia-calendar" aria-label="Calendario de reuniones"><header><h3>${esc(presentation?.title || 'Agenda')}</h3><span>Zona horaria: ${esc(presentation?.timezone)}</span></header>`;
  if (!events.length) html += '<p class="mia-calendar-empty-range">No hay reuniones en el intervalo consultado.</p>';
  if (!days.length) return html + '<p>No hay un intervalo de calendario disponible.</p></section>';
  html += '<div class="mia-calendar-scroll">';
  for (let index = 0; index < days.length; index += 7) {
    const week = days.slice(index, index + 7);
    html += `<div class="mia-calendar-week mia-calendar-week--${week.length}">`;
    for (const day of week) {
      const items = events.filter(e => e.start_day <= day.date && e.end_day >= day.date);
      html += `<section class="mia-calendar-day" aria-label="${esc(day.label)}"><h4>${esc(day.label)}</h4>${items.map(e => eventHtml(e, day.date)).join('') || '<p class="mia-calendar-empty">Sin eventos</p>'}</section>`;
    }
    html += '</div>';
  }
  return html + '</div></section>';
}

/** Desktop uses textContent exclusively; its CSP permits neither inline CSS nor HTML injection. */
export function mountCalendar(host, presentation) {
  if(presentation?.confirmation)return mountConfirmation(host,presentation);
  const doc=host.ownerDocument;
  const node=(tag,cls,text)=>{const element=doc.createElement(tag);if(cls)element.className=cls;if(text!=null)element.textContent=String(text);return element;};
  const root=node('section','mia-calendar');root.setAttribute('aria-label','Calendario de reuniones');
  const header=node('header');header.append(node('h3','',presentation.title||'Agenda'),node('span','',`Zona horaria: ${presentation.timezone||''}`));root.append(header);
  const days=Array.isArray(presentation.days)?presentation.days:[];
  const events=(Array.isArray(presentation.events)?presentation.events:[]).filter(e=>e&&e.status!=='cancelled').slice().sort((a,b)=>String(a.start).localeCompare(String(b.start)));
  if(!events.length)root.append(node('p','mia-calendar-empty-range','No hay reuniones en el intervalo consultado.'));
  const scroll=node('div','mia-calendar-scroll');
  for(let i=0;i<days.length;i+=7){const week=days.slice(i,i+7),grid=node('div',`mia-calendar-week mia-calendar-week--${week.length}`);
    for(const day of week){const column=node('section','mia-calendar-day');column.append(node('h4','',day.label));
      const items=events.filter(e=>e.start_day<=day.date&&e.end_day>=day.date);
      if(!items.length)column.append(node('p','mia-calendar-empty','Sin eventos'));
      for(const event of items){const article=node('article','mia-calendar-event');
        const time=event.all_day?'Todo el día':`${day.date>event.start_day?'Continúa':event.start_time} – ${day.date<event.end_day?'continúa':event.end_time}`;
        article.append(node('time','mia-calendar-time',time));const details=node('details');details.append(node('summary','',event.subject||'Sin asunto'));
        const list=node('dl');for(const [label,value] of [['Inicio',event.start_label],['Fin',event.end_label]])list.append(node('dt','',label),node('dd','',value));details.append(list);
        if(typeof event.online_url==='string'&&/^https:\/\//i.test(event.online_url)){const link=node('a','','Abrir reunión online');link.href=event.online_url;link.target='_blank';link.rel='noopener noreferrer';details.append(link);}
        article.append(details);if(event.location)article.append(node('small','',event.location));article.append(node('small','',event.ref||''));column.append(article);
      }grid.append(column);
    }scroll.append(grid);
  }root.append(scroll);host.append(root);return root;
}

function reviewLines(value, prefix='') {
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value).filter(([key])=>!['id','event_id','calendar_id','provider','payload_digest','snapshot','mail_snapshot'].includes(key)).flatMap(([key,item]) => {
    const label=(prefix?prefix+' · ':'')+key.replaceAll('_',' ');
    if(item && typeof item==='object')return reviewLines(item,label);
    return item==null?[]:[[label,String(item)]];
  });
}
function confirmationHtml(p) {
  const c=p.confirmation;
  return `<section class="mia-calendar"><h3>${esc(p.title)}</h3><dl>${reviewLines(c.review).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><p>Revisa los datos antes de confirmar. También puedes escribirlo o decirlo por voz.</p><button type="button" class="mia-calendar-confirm" data-calendar-confirm="${esc(c.prompt)}">${esc(c.label||'Sí, confirmo')} · ${esc(c.reference)}</button><p role="status" class="mia-calendar-confirm-status"></p></section>`;
}
function mountConfirmation(host,p) {
  const doc=host.ownerDocument,root=doc.createElement('section');root.className='mia-calendar';
  const add=(tag,text,parent=root)=>{const n=doc.createElement(tag);n.textContent=text;parent.append(n);return n;};
  add('h3',p.title);const list=doc.createElement('dl');root.append(list);
  for(const [k,v] of reviewLines(p.confirmation.review)){add('dt',k,list);add('dd',v,list);}
  add('p','Revisa los datos antes de confirmar. También puedes escribirlo o decirlo por voz.');
  const b=add('button',`${p.confirmation.label||'Sí, confirmo'} · ${p.confirmation.reference}`);b.type='button';b.className='mia-calendar-confirm';b.setAttribute('data-calendar-confirm',p.confirmation.prompt);
  const status=add('p','');status.className='mia-calendar-confirm-status';status.setAttribute('role','status');host.append(root);return root;
}
export function bindCalendarConfirmations(host, send) {
  host.addEventListener('click',async event=>{
    const button=event.target.closest?.('[data-calendar-confirm]');
    if(!button||!host.contains(button)||button.disabled)return;
    const prompt=button.getAttribute('data-calendar-confirm');
    if(!/^confirma cambio [1-9]\d*$/.test(prompt||''))return;
    button.disabled=true;const status=button.parentElement.querySelector('.mia-calendar-confirm-status');
    try {await send(prompt);if(status)status.textContent='Confirmación enviada. Consulta la respuesta de mIA.';}
    catch {button.disabled=false;if(status)status.textContent='No se pudo enviar. Puedes reintentarlo o confirmar por texto.';}
  });
}
if (typeof window !== 'undefined') window.MiaCalendarView = {render: renderCalendar, presentations: calendarPresentations, bind:bindCalendarConfirmations};
