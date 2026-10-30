'use strict';
// Los resultados proceden exclusivamente del backend autorizado. No se generan valores sintéticos.
const MAX_ROWS = 3000;
const MAX_COLS = 24;
const MAX_CARDS = 24;
const MAX_TABLES = 8;
const MAX_CELL = 1200;
const isObj = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const titleOf = (x, fallback) => String(x?.title || x?.titulo || x?.name || fallback).slice(0,140);
const primitive = x => x == null || ['string','number','boolean'].includes(typeof x);
const safeValue = x => primitive(x) ? (typeof x === 'string' ? x.slice(0, MAX_CELL) : x) :
  (Array.isArray(x) && x.length <= 8 && x.every(primitive) ? x.map(v=>String(v??'')).join(' · ').slice(0,MAX_CELL) : null);
const cleanColumn = x => {
  if (typeof x === 'string') return {key:x.slice(0,100),label:x.slice(0,120)};
  if (isObj(x)) {const key = x.key || x.field || x.id || x.nombre;
    return typeof key === 'string' ? {key:key.slice(0,100),label:String(x.label || x.title || x.nombre || key).slice(0,120)} : null;
  }
  return null;
};
function extractPresentation(reply) {
  const data = isObj(reply?.data) ? reply.data : {};
  const result = { tables:[], cards:[], notices:[], hasStructuredData:false };
  const nativeCalendars = Array.isArray(reply?.presentations) ? reply.presentations.filter(p=>p?.type==='calendar') : [];
  const calendars = nativeCalendars.length ? nativeCalendars : (Array.isArray(data.calendars)?data.calendars:[]);
  if(calendars.length){result.calendars=calendars.filter(isObj).map(p=>({
    type:'calendar',title:String(p.title||'Agenda'),timezone:String(p.timezone||''),
    ...(isObj(p.confirmation)?{confirmation:{prompt:String(p.confirmation.prompt||''),label:String(p.confirmation.label||'Sí, confirmo'),reference:String(p.confirmation.reference||''),review:p.confirmation.review}}:{}),
    days:(Array.isArray(p.days)?p.days:[]).filter(isObj).map(d=>({date:safeValue(d.date),label:safeValue(d.label)})),
    events:(Array.isArray(p.events)?p.events:[]).filter(isObj).map(e=>Object.fromEntries(
      ['id','ref','subject','start','end','start_day','end_day','start_time','end_time','start_label','end_label','location','online_url','all_day','status'].map(key=>[key,safeValue(e[key])])
    ))}));result.hasStructuredData=true;}
  const seen = new WeakSet();
  function addTable(raw, name='Listado') {
    if (result.tables.length >= MAX_TABLES || !raw) return;
    let rows = Array.isArray(raw) ? raw : raw.rows || raw.filas || raw.records || raw.registros;
    if (!Array.isArray(rows) || !rows.length || !rows.some(isObj)) return;
    if (seen.has(rows)) return;
    seen.add(rows);
    const fullCount = rows.length;
    const tableCfg = isObj(raw) ? raw : {};
    let columns = (Array.isArray(tableCfg.columns) ? tableCfg.columns : [])
      .map(cleanColumn).filter(Boolean);
    if (!columns.length) {
      const keys = [];
      for (const row of rows.slice(0,50)) if (isObj(row)) for (const [key,v] of Object.entries(row)) {
        if (primitive(v) && !keys.includes(key)) keys.push(key);
      }
      columns = keys.map(cleanColumn).filter(Boolean);
    }
    const originalColumns = columns.length;
    columns = columns.slice(0,MAX_COLS);
    if (!columns.length) return;
    const normalizedRows = rows.slice(0,MAX_ROWS).filter(isObj).map(row => {
      const out = Object.create(null);
      for (const {key} of columns) out[key] = safeValue(row[key]);
      return out;
    });
    if (!normalizedRows.length) return;
    const reportedTotal = Number(tableCfg.total ?? tableCfg.total_rows ?? tableCfg.total_registros);
    const total = Number.isFinite(reportedTotal) && reportedTotal > fullCount ? reportedTotal : fullCount;
    const truncated = fullCount > normalizedRows.length || originalColumns > columns.length;
    result.tables.push({ title:titleOf(tableCfg,name), columns, rows: normalizedRows,
      total, received:fullCount, truncated, // Solo "completo" si lo confirma el backend.
      complete:tableCfg.complete === true || tableCfg.completo === true || tableCfg.is_complete === true });
    result.hasStructuredData = true;
    if (truncated) result.notices.push(`El listado «${titleOf(tableCfg,name)}» supera el límite visual del prototipo. Se muestran ${normalizedRows.length} de ${fullCount} filas recibidas.`);
    if (total > fullCount) result.notices.push(`El backend indica ${total} registros pero solo ha enviado ${fullCount}. No se puede mostrar el listado completo.`);
  }
  function addCards(input) {
    if (!Array.isArray(input)) return;
    for (const card of input.slice(0,MAX_CARDS)) {
      if (!isObj(card)) continue;
      const value = card.value ?? card.valor ?? card.metric ?? card.total;
      if (!primitive(value) || value == null) continue;
      const label = card.label || card.title || card.titulo || card.nombre || card.name;
      if (!label) continue;
      // Datos técnicos de un artefacto NO son métricas financieras.
      const normalizedLabel=String(label).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[_-]/g,' ').trim();
      if(/^(secciones|caduca en horas|horas de caducidad|ttl|expires in hours|expiration hours|vencimiento|paginas del informe)$/.test(normalizedLabel))continue;
      result.cards.push({label:String(label).slice(0,100),value:safeValue(value),unit:typeof card.unit === 'string' ? card.unit.slice(0,30) : ''});
    }
    if (result.cards.length) result.hasStructuredData = true;
  }
  addCards(data.cards || data.kpis || reply.cards);
  const added = new WeakSet();
  function visit(value,path='',depth=0) {
    if (depth>3 || !value || typeof value !== 'object' || added.has(value)) return;
    added.add(value);
    if (Array.isArray(value)) {
      if (value.length && value.some(isObj)) addTable(value, path.replace(/_/g,' ') || 'Listado');
      return;
    }
    if (!isObj(value)) return;
    if (Array.isArray(value.rows) || Array.isArray(value.filas) || Array.isArray(value.records) || Array.isArray(value.registros)) {
      addTable(value, titleOf(value,path.replace(/_/g,' ') || 'Listado'));
      return;
    }
    for (const [key,child] of Object.entries(value)) {
      if (result.tables.length>=MAX_TABLES) break;
      if (/^(sources|fuentes|web_sources|permissions|permisos|actions|alerts|alertas|insights|logs|metadata|meta|quality|calidad|charts|visualizations|documents|documentos|messages|mensajes|context|provenance)$/i.test(key)) continue;
      if (['cards','kpis','calendars'].includes(key.toLowerCase())) continue;
      if (child && typeof child === 'object') visit(child,key,depth+1);
    }
  }
  visit(data,'Datos');
  if (isObj(reply?.presentation)) visit(reply.presentation,'Presentación');
  if (isObj(reply?.table) || Array.isArray(reply?.table)) visit(reply.table,'Listado');
  if (Array.isArray(reply?.rows)) visit(reply.rows,'Listado');
  if (Array.isArray(reply?.visualizations) && reply.visualizations.length && !result.tables.length && !result.cards.length)
    result.notices.push('El backend ha devuelto visualizaciones no tabulares. Esta versión todavía no interpreta ese formato.');
  return result;
}
module.exports = { extractPresentation };
