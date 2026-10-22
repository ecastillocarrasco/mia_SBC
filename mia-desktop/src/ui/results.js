'use strict';
const $ = id => document.getElementById(id);
const bridge = window.miaDesktop;
const PAGE_SIZE = 50;
const fmt = new Intl.NumberFormat('es-ES');
let currentPayload = null;
function node(tag, cls, value) {
  const el=document.createElement(tag);
  if(cls) el.className=cls;
  if(value != null) el.textContent=String(value);
  return el;
}
function formatValue(v) {
  if(v == null || v === '') return '—';
  if(typeof v === 'boolean') return v ? 'Sí' : 'No';
  if(typeof v === 'number') return fmt.format(v);
  return String(v);
}
function availableChart(table){
  // Solo dibujamos valores NUMÉRICOS de filas reales; nada de totales inventados,
  // agrupaciones ambiguas, porcentajes agregados ni identificadores personales.
  if(!Array.isArray(table.rows) || table.rows.length<2)return null;
  const columns=table.columns||[];
  const labelCol=columns.find(c=>/^(departamento|área|area|categor[ií]a|mes|año|anio|periodo|secci[oó]n|concepto|tipo|centro|unidad|fecha)$/i.test(c.key));
  if(!labelCol)return null;
  const numericCols=columns.filter(c=>
    c.key!==labelCol.key && !/(?:^id$|^cod(?:igo)?$|documento|dni|nie|tel[eé]fono|nif|cuenta|iban|referencia|fecha|postal|año|anio|mes|periodo)/i.test(c.key) &&
    table.rows.every(row=>row[c.key] == null || typeof row[c.key]==='number') &&
    table.rows.some(row=>typeof row[c.key]==='number' && Number.isFinite(row[c.key]))
  );
  if(!numericCols.length)return null;
  const labels=table.rows.slice(0,12).map(r=>String(r[labelCol.key] ?? ''));
  if(labels.some(l=>!l || l.length>65) || new Set(labels).size!==labels.length)return null;
  return {labelCol,numericCols};
}
function renderBars(host,table,chart,metricKey){
  host.replaceChildren();
  const numeric=table.rows.slice(0,12).map(r=>({label:String(r[chart.labelCol.key] ?? ''),value:r[metricKey]})).filter(x=>typeof x.value==='number' && Number.isFinite(x.value));
  if(!numeric.length)return;
  const max=Math.max(1,...numeric.map(x=>Math.abs(x.value)));
  const plot=node('div','viz-bars');
  for (const {label,value} of numeric){
    const line=node('div','viz-row');
    const name=node('span','viz-label',label);name.title=label;
    const rail=node('div','viz-track');const bar=node('div',value<0?'viz-bar negative':'viz-bar');bar.style.width=`${Math.max(1,Math.abs(value)/max*100)}%`;
    rail.append(bar);
    const amount=node('strong','viz-value',formatValue(value));
    line.append(name,rail,amount);plot.append(line);
  }
  host.append(plot,node('p','viz-caption',`Visualización de hasta 12 filas recibidas (${fmt.format(table.rows.length)} filas en la tabla). Los valores no se agregan ni se recalculan. Los negativos aparecen en otro color.`));
}
function makeTable(table,tableIndex){
  const section=node('article','table-card');section.id=`table-${tableIndex+1}`;
  const head=node('div','table-head');
  const titleGroup=node('div','table-title-group');
  titleGroup.append(node('span','table-overline',`CONJUNTO DE DATOS · ${String(tableIndex+1).padStart(2,'0')}`),node('h3','',table.title||'Listado'));
  const incomplete=!!(table.truncated || table.total>table.received || !table.complete);
  titleGroup.append(node('p','',`${fmt.format(table.rows.length)} filas disponibles · ${fmt.format(table.total)} registros comunicados`));
  head.append(titleGroup);
  const controls=node('div','export-toolbar');
  const exportCSV=node('button','outline-action','↓ CSV');exportCSV.type='button';exportCSV.title='Exportar las filas filtradas a CSV';
  const exportExcel=node('button','gold-action','↓ Excel');exportExcel.type='button';exportExcel.title='Exportar las filas filtradas a Excel';
  const expand=node('button','outline-action expand-action','⤢ Ampliar');expand.type='button';expand.setAttribute('aria-pressed','false');
  controls.append(exportCSV,exportExcel,expand);head.append(controls);section.append(head);
  const strip=node('div','table-info-strip');
  strip.append(node('span',incomplete?'data-status partial':'data-status complete',incomplete?'◌ Datos recibidos, completitud no confirmada':'✓ Conjunto completo confirmado'));
  const status=node('small','export-status');status.setAttribute('role','status');strip.append(status);section.append(strip);
  const tools=node('div','data-tools');
  const searchWrap=node('label','search-wrap');searchWrap.append(node('span','search-icon','⌕'));
  const search=node('input','search');search.type='search';search.placeholder='Buscar en este conjunto de datos';search.setAttribute('aria-label','Filtrar listado');searchWrap.append(search);tools.append(searchWrap);
  const chartCfg=availableChart(table);
  let chartArea=null;
  if(chartCfg){
    const chartToggle=node('button','viz-toggle','◈ Explorar gráfico');chartToggle.type='button';chartToggle.setAttribute('aria-expanded','false');
    chartArea=node('section','chart-panel');chartArea.hidden=true;
    const intro=node('div','chart-intro');intro.append(node('div','chart-kicker','VISUALIZACIÓN INTERACTIVA'),node('h4','',`Distribución por ${chartCfg.labelCol.label||chartCfg.labelCol.key}`));
    const chartSelect=node('select','chart-select');chartSelect.setAttribute('aria-label','Seleccionar indicador');
    for(const col of chartCfg.numericCols){const op=node('option','',col.label||col.key);op.value=col.key;chartSelect.append(op);}
    intro.append(chartSelect);chartArea.append(intro);const chartContent=node('div','chart-content');chartArea.append(chartContent);
    chartSelect.addEventListener('change',()=>renderBars(chartContent,table,chartCfg,chartSelect.value));
    chartToggle.addEventListener('click',()=>{
      chartArea.hidden=!chartArea.hidden;chartToggle.setAttribute('aria-expanded',String(!chartArea.hidden));
      chartToggle.textContent=chartArea.hidden?'◈ Explorar gráfico':'◈ Ocultar gráfico';
      if(!chartArea.hidden)renderBars(chartContent,table,chartCfg,chartSelect.value);
    });tools.append(chartToggle);
  }
  tools.append(node('span','table-tools-hint','Ordena pulsando en las cabeceras'));
  section.append(tools);if(chartArea)section.append(chartArea);
  const tableBox=node('div','table-scroll');const tableEl=node('table','data-table');
  const thead=node('thead'),trHead=node('tr');const tbody=node('tbody');
  let sortKey=null,sortDirection=1;
  const headers=[];
  for(const col of table.columns){
    const th=node('th');th.scope='col';
    const sortButton=node('button','column-sort');sortButton.type='button';sortButton.title=`Ordenar por ${col.label||col.key}`;
    sortButton.append(node('span','',col.label||col.key),node('span','sort-symbol','↕'));
    sortButton.addEventListener('click',()=>{
      if(sortKey===col.key)sortDirection*=-1;else {sortKey=col.key;sortDirection=1;}
      page=0;paint();
    });th.append(sortButton);trHead.append(th);headers.push({key:col.key,th,button:sortButton});
  }
  thead.append(trHead);tableEl.append(thead,tbody);tableBox.append(tableEl);section.append(tableBox);
  const footer=node('div','table-footer');const pageInfo=node('span','page-info');
  const paging=node('div','pagination');const prev=node('button','page-btn','← Anterior');const next=node('button','page-btn','Siguiente →');
  paging.append(prev,next);footer.append(pageInfo,paging);section.append(footer);
  let page=0;
  const matches=()=>{
    const q=search.value.trim().toLocaleLowerCase('es');
    const included=table.rows.map((row,i)=>({row,i})).filter(({row})=>!q || table.columns.some(c=>formatValue(row[c.key]).toLocaleLowerCase('es').includes(q)));
    if(sortKey){
      included.sort((a,b)=>{
        const va=a.row[sortKey],vb=b.row[sortKey];
        if(va==null)return vb==null?a.i-b.i:1;
        if(vb==null)return -1;
        const comparison=typeof va==='number' && typeof vb==='number'?va-vb:String(va).localeCompare(String(vb),'es',{numeric:true,sensitivity:'base'});
        return comparison===0?a.i-b.i:comparison*sortDirection;
      });
    }
    return included;
  };
  async function exportData(format){
    const indices=matches().map(x=>x.i);
    status.textContent='Preparando exportación…';exportCSV.disabled=true;exportExcel.disabled=true;
    try{
      const outcome=await bridge.exportTable({tableIndex,rowIndices:indices,format});
      status.textContent=outcome?.ok?`✓ ${fmt.format(outcome.rows)} filas exportadas${outcome.partial?' · origen parcial':''}`:outcome?.canceled?'Exportación cancelada.':outcome?.error||'No se pudo exportar.';
    }catch{status.textContent='Error en la exportación.';}
    finally{exportCSV.disabled=false;exportExcel.disabled=false;}
  }
  exportCSV.addEventListener('click',()=>exportData('csv'));
  exportExcel.addEventListener('click',()=>exportData('xlsx'));
  expand.addEventListener('click',()=>{
    const open=section.classList.toggle('expanded-table');
    expand.textContent=open?'↙ Volver':'⤢ Ampliar';expand.setAttribute('aria-pressed',String(open));
    document.body.classList.toggle('has-expanded-table',open);
    if(open)section.scrollIntoView({behavior:'smooth',block:'start'});
  });
  function paint(){
    const filtered=matches(),pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));page=Math.min(page,pages-1);
    tbody.replaceChildren();
    for(const {row} of filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)){
      const tr=node('tr');table.columns.forEach((c,i)=>{
        const val=formatValue(row[c.key]);const td=node('td',i===0?'primary-cell':'',val);td.title=val;tr.append(td);
      });tbody.append(tr);
    }
    if(!filtered.length){const tr=node('tr'),td=node('td','no-matches','No hay registros que coincidan con este filtro.');td.colSpan=table.columns.length;tr.append(td);tbody.append(tr);}
    pageInfo.textContent=`${fmt.format(filtered.length)} filas filtradas · Página ${page+1} de ${pages}`;
    prev.disabled=page===0;next.disabled=page>=pages-1;
    headers.forEach(({key,button,th})=>{
      const isActive=key===sortKey;
      th.setAttribute('aria-sort',isActive?(sortDirection===1?'ascending':'descending'):'none');
      button.lastChild.textContent=isActive?(sortDirection===1?'↑':'↓'):'↕';
    });
  }
  search.addEventListener('input',()=>{page=0;paint();});
  prev.addEventListener('click',()=>{page=Math.max(0,page-1);paint();});next.addEventListener('click',()=>{page++;paint();});
  paint();return section;
}
function render(payload){
  if(!payload || typeof payload!=='object')return;
  currentPayload=payload;
  const report=payload.report;
  const pending=!!payload.reportPending;
  const section=$('documentSection');
  section.hidden=!(report||pending);
  $('downloadReport').hidden=!report?.available;
  $('downloadReport').disabled=false;
  $('documentTitle').textContent=report?.title||'Informe solicitado';
  $('documentDescription').textContent=report?.available?('Archivo '+report.format.toUpperCase()+' proporcionado por el motor de informes SBC.'): 'El servidor ha respondido, pero no ha enviado un enlace de descarga verificable. No es posible obtener el documento desde esta respuesta.';
  $('documentStatus').textContent=report?.available?'Disponible para descargar':'Descarga no disponible · revisar respuesta del backend';
  $('documentSection').dataset.format=report?.format||'pdf';
  $('query').textContent=payload.question||'Consulta sin especificar';
  $('answer').textContent=payload.answer||'No se ha recibido texto de respuesta.';
  const presentation=payload.presentation||{};
  const tables=Array.isArray(presentation.tables)?presentation.tables:[];
  const cards=Array.isArray(presentation.cards)?presentation.cards:[];
  const notices=Array.isArray(presentation.notices)?[...presentation.notices]:[];
  const rows=tables.reduce((sum,t)=>sum+(Array.isArray(t.rows)?t.rows.length:0),0);
  $('statRows').textContent=fmt.format(rows);
  $('statTables').textContent=fmt.format(tables.length);
  $('statKpis').textContent=fmt.format(cards.length);
  const structured=!!(tables.length||cards.length);
  if(!structured && !report?.available && !pending)notices.push('El backend no ha enviado tablas ni indicadores estructurados. El texto de la respuesta no equivale a registros recibidos.');
  $('state').textContent=report?.available?'● Documento disponible':pending?'◌ Documento no entregado':structured?'● Respuesta con datos':'◌ Sin datos estructurados';
  $('notices').replaceChildren();
  for(const warning of notices.slice(0,12)){
    const el=node('div','notice');el.append(node('span','notice-mark','!'),node('span','',warning));$('notices').append(el);
  }
  $('notices').hidden=!notices.length;
  $('cards').replaceChildren();
  cards.forEach((card,i)=>{
    const box=node('article','kpi');
    box.style.setProperty('--index',String(i));
    box.append(node('span','kpi-label',card.label),node('strong','kpi-value',formatValue(card.value)),node('small','kpi-unit',card.unit||'Indicador recibido'));
    box.append(node('span','kpi-shine'));
    $('cards').append(box);
  });
  $('cards').hidden=!cards.length;$('cardsEmpty').hidden=!!cards.length || !!report || pending;
  $('dashboard').hidden=!cards.length && (!!report || pending);
  $('tables').replaceChildren();tables.forEach((table,i)=>$('tables').append(makeTable(table,i)));
  $('empty').hidden=structured || !!report || pending;
  $('details').hidden=!tables.length;
}
$('downloadReport').addEventListener('click',async()=>{
  const button=$('downloadReport');button.disabled=true;$('documentStatus').textContent='Recuperando archivo del backend…';
  try{const r=await bridge.downloadReport();$('documentStatus').textContent=r?.ok?'Informe guardado correctamente.':r?.canceled?'Descarga cancelada.':r?.error||'No se pudo recuperar el archivo.';}
  catch{$('documentStatus').textContent='No se pudo establecer comunicación para descargar el archivo.';}
  finally{button.disabled=false;}
});
bridge.onResultsData(render);

window.addEventListener('error',()=>window.miaDesktop.reportRendererError('WINDOW_ERROR'));
window.addEventListener('unhandledrejection',()=>window.miaDesktop.reportRendererError('UNHANDLED_REJECTION'));
