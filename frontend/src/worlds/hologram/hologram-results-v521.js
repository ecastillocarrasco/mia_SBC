/**
 * mIA HG 5.2.1 — projection adapter, independent of other worlds.
 * The source of truth is the actual result event; all output is HTML-escaped.
 * Never invent KPIs, comparison values or employee data.
 */

const limit = (n, low, high) => Math.max(low, Math.min(high, n));
const asObj = (v) => v && typeof v === 'object' && !Array.isArray(v) ? v : null;
const str = (value) => String(value ?? '').trim();
const escapeHTML = (v) => str(v).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const humanize = (value) => str(value).replace(/[_-]/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2');
const fmt = (value) => typeof value === 'number' && Number.isFinite(value)
  ? new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 }).format(value)
  : str(value);
const printable = (value) => value == null || typeof value === 'object' ? '' : fmt(value);

function metric(label, value, unit = '') {
  if (value == null || typeof value === 'object' || value === '') return null;
  const title = str(label);
  if (!title || typeof value === 'number' && !Number.isFinite(value)) return null;
  return { label: humanize(title), value: fmt(value), unit: str(unit) };
}

function extractMetrics(presentations) {
  const result = [], seen = new Set();
  const add = (label, value, unit) => {
    const candidate = metric(label, value, unit);
    if (!candidate || seen.has(candidate.label.toLowerCase())) return;
    seen.add(candidate.label.toLowerCase());
    result.push(candidate);
  };
  for (const p of presentations) {
    if (!asObj(p)) continue;
    for (const key of ['kpis', 'metrics', 'indicators', 'cards']) {
      const group = p[key];
      if (Array.isArray(group)) {
        for (const raw of group) {
          if (!asObj(raw)) continue;
          add(raw.label || raw.title || raw.name || key, raw.value ?? raw.amount ?? raw.count,
            raw.unit ?? raw.suffix);
        }
      } else if (asObj(group)) {
        for (const [keyName, raw] of Object.entries(group)) {
          if (asObj(raw)) add(raw.label || raw.title || keyName,
            raw.value ?? raw.amount ?? raw.count, raw.unit ?? raw.suffix);
          else add(keyName, raw);
        }
      }
    }
    if (p.type === 'metric' || p.type === 'kpi') add(p.label || p.title || 'Indicador', p.value, p.unit);
  }
  return result.slice(0, 4);
}

function columnKey(column) {
  return typeof column === 'string' ? column :
    str(column?.key ?? column?.field ?? column?.id ?? column?.name ?? column?.label);
}
function columnLabel(column) {
  return typeof column === 'string' ? column :
    str(column?.label ?? column?.title ?? columnKey(column));
}
function normalizeTable(raw, sourceTitle = '') {
  if (!asObj(raw) || !Array.isArray(raw.rows) || !raw.rows.length) return null;
  const rows = raw.rows;
  let columns = Array.isArray(raw.columns) && raw.columns.length
    ? raw.columns.slice(0, 4)
    : asObj(rows[0]) ? Object.keys(rows[0]).slice(0, 4) :
      Array.isArray(rows[0]) ? rows[0].slice(0, 4).map((_, i) => `Columna ${i+1}`) : [];
  if (!columns.length) return null;
  const keys = columns.map(columnKey);
  const labels = columns.map(columnLabel);
  return {
    title: str(raw.title || sourceTitle || 'Datos recibidos'),
    count: rows.length,
    labels,
    rows: rows.slice(0, 5).map((row) => keys.map((k, i) =>
      printable(Array.isArray(row) ? row[i] : asObj(row) ? row[k] : undefined))),
  };
}
function numeric(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const v = str(value).replace(/\s|€/g, '');
  if (!/^[+-]?[\d.,]+%?$/.test(v)) return null;
  const clean = v.replace(/%$/, '');
  const number = Number(clean.includes(',') ? clean.replace(/\./g,'').replace(',','.') : clean);
  return Number.isFinite(number) ? number : null;
}
function normalizeChart(chart) {
  if (!asObj(chart)) return null;
  const points = chart.data || chart.points || chart.values;
  if (!Array.isArray(points) || points.length < 2) return null;
  const extracted = [];
  for (const point of points) {
    if (!asObj(point)) continue;
    const label = point.label ?? point.name ?? point.x ?? point.category ?? point.period;
    const val = point.value ?? point.y ?? point.count ?? point.total ?? point.amount;
    if (label == null || numeric(val) === null) continue;
    extracted.push([str(label), fmt(val)]);
    if (extracted.length >= 6) break;
  }
  if (extracted.length < 2) return null;
  return { title: str(chart.title || 'Comparativa'), count: extracted.length,
    labels: ['Categoría', 'Valor'], rows: extracted };
}
function extractTables(presentations) {
  for (const p of presentations) {
    if (!asObj(p)) continue;
    const all = [p, ...(Array.isArray(p.tables) ? p.tables : [])];
    for (const raw of all) {
      const table = normalizeTable(raw, p.title);
      if (table) return table;
    }
    const charts = [p.chart, ...(Array.isArray(p.charts) ? p.charts : []),
      /chart|graph|graf|plot/i.test(str(p.type)) ? p : null].filter(Boolean);
    for (const chart of charts) {
      const table = normalizeChart(chart);
      if (table) return table;
    }
    // Structured arrays returned under a named field, e.g. employees/items.
    for (const field of ['items', 'records', 'employees', 'people', 'personal', 'results']) {
      const records = p[field];
      if (!Array.isArray(records) || !records.length || !asObj(records[0])) continue;
      const table = normalizeTable({ title: p.title || humanize(field), rows: records }, p.title);
      if (table) return table;
    }
  }
  return null;
}

/** Minimal Markdown table fallback (when backend returns a table as prose only). */
function markdownTable(answer) {
  const lines = str(answer).split(/\r?\n/).map(s=>s.trim());
  for (let i=0; i<lines.length-2; i++) {
    if (!/^\|.+\|$/.test(lines[i]) ||
      !/^\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$/.test(lines[i+1])) continue;
    const split = line => line.replace(/^\|/,'').replace(/\|$/,'').split('|').map(v=>v.trim());
    const cols = split(lines[i]);
    const rows = [];
    for (let j=i+2; j<lines.length && rows.length<20 && /^\|.*\|$/.test(lines[j]); j++) {
      const row = split(lines[j]);
      if (row.length === cols.length) rows.push(row);
    }
    return normalizeTable({ title:'Datos de la respuesta',columns:cols,rows });
  }
  return null;
}
function extractDocuments(presentations) {
  const result = [];
  for (const p of presentations) {
    if (!asObj(p)) continue;
    if (p.url) result.push({ label: str(p.title || p.file_name || 'Informe'), url: p.url });
    if (Array.isArray(p.documents)) for (const doc of p.documents) {
      if (asObj(doc) && doc.url) result.push({ label: str(doc.title || 'Documento'),url:doc.url });
    }
    if (p.type === 'mail' && Array.isArray(p.adjuntos)) for (const att of p.adjuntos) {
      if (asObj(att) && att.url) result.push({ label: str(att.nombre || 'Adjunto'), url: att.url });
    }
  }
  return result.slice(0, 4);
}

/** Correo abierto (de, para, asunto, cuerpo) o un hilo completo (lista de mensajes). Los adjuntos
 * reales van por extractDocuments() — aquí nunca se muestra el texto extraído de un adjunto
 * (es solo para el LLM), sólo el cuerpo real del mensaje. */
function extractMail(presentations) {
  for (const p of presentations) {
    if (!asObj(p) || (p.type !== 'mail' && p.type !== 'mail_thread')) continue;
    return p;
  }
  return null;
}

function renderMailSection(mail) {
  if (!mail) return '';
  if (mail.type === 'mail') {
    const meta = [mail.de ? `De: ${str(mail.de)}` : '', mail.recibido ? str(mail.recibido) : '']
      .filter(Boolean).map(escapeHTML).join(' · ');
    const body = str(mail.texto).slice(0, 800);
    return `<section class="hg-brief hg-mail" aria-label="Correo"><header class="hg-brief-head"><span>mIA · CORREO</span>
      <h2>${escapeHTML(mail.asunto || '(sin asunto)')}</h2></header>
      <p class="hg-mail-meta">${meta}</p>
      <p class="hg-mail-body">${escapeHTML(body)}</p></section>`;
  }
  const rows = Array.isArray(mail.mail_rows) ? mail.mail_rows.slice(0, 8) : [];
  const items = rows.map((r) => `<li class="hg-mail-thread-item${r?.is_read ? '' : ' hg-mail-thread-item--unread'}">
    <b>${escapeHTML(r?.from || '')}</b><span>${escapeHTML(r?.subject || '')}</span></li>`).join('');
  return `<section class="hg-brief hg-mail" aria-label="Hilo de correo"><header class="hg-brief-head"><span>mIA · CORREO</span>
    <h2>${escapeHTML(mail.title || 'Hilo de correo')}</h2></header>
    <ol class="hg-mail-thread">${items}</ol></section>`;
}
/** Noticias corporativas y de grupo (Sunset Beach Club / Grupo FBD): información pública, pero
 * un listado de artículos no es contenido para la proyección física del fan (demasiado texto),
 * así que se trata como la pantalla, nunca el fan — igual que la tabla genérica. */
function extractNews(presentations) {
  for (const p of presentations) {
    if (asObj(p) && p.type === 'news_list') return p;
  }
  return null;
}

function renderNewsSection(news) {
  if (!news) return '';
  const rows = Array.isArray(news.news_rows) ? news.news_rows.slice(0, 8) : [];
  const items = rows.map((r) => {
    const href = safeHref(r?.url);
    const title = escapeHTML(r?.titulo || 'Noticia');
    const titleHTML = href
      ? `<a href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title;
    const meta = [r?.empresa, r?.categoria, r?.fecha].filter(Boolean).map(escapeHTML).join(' · ');
    return `<li class="hg-news-item"><b>${titleHTML}</b>${meta ? `<span>${meta}</span>` : ''}</li>`;
  }).join('');
  return `<section class="hg-brief hg-news" aria-label="Noticias"><header class="hg-brief-head"><span>mIA · NOTICIAS</span>
    <h2>${escapeHTML(news.title || 'Noticias corporativas y del grupo')}</h2></header>
    <ol class="hg-news-list">${items}</ol></section>`;
}
function safeHref(url) {
  const raw = str(url);
  if (/^\/api\/[\w/?=&%.-]+$/.test(raw)) return raw;
  try {
    const parsed = new URL(raw, 'http://localhost');
    if (/^https?:$/.test(parsed.protocol) && /^(https?:\/\/)/.test(raw)) return parsed.href;
  } catch { /* reject */ }
  return '';
}

export function adaptHologramResult(response, presentations = [], { type = 'analytics', fan = false } = {}) {
  const items = Array.isArray(presentations) ? presentations.filter(asObj) : [];
  const metrics = extractMetrics(items);
  const mail = extractMail(items);
  const news = extractNews(items);
  // El hilo completo y el listado de noticias ya traen su propia lista: no se duplican como
  // tabla genérica (extractTables() no distingue por `type`, solo mira si hay `rows`).
  const table = (mail?.type === 'mail_thread' || news) ? null : extractTables(items) || markdownTable(response?.answer);
  const docs = extractDocuments(items);
  const answer = str(response?.answer || response?.speech);
  const hasPayload = items.length > 0 || Boolean(table || metrics.length || docs.length || mail || news);
  if (!hasPayload) return { html:'', visible:false, hasPayload:false, counts:{ metrics:0, rows:0, docs:0 } };
  // Explicitly label the number of received rows, never claim this is the entire dataset.
  // Prioritize a meaningful graph instead of a synthetic-looking row-count KPI.
  // Row count is a fact, but cannot replace an actual categorical comparison.
  const isChartSource = items.some(p=> /^(chart|graph|grafica|graphic|comparison|comparativa)$/i.test(str(p.type)) ||
    asObj(p.chart) || (Array.isArray(p.charts) && p.charts.length));
  const firstColumn = str(table?.labels[0]).toLowerCase();
  const secondColumn = str(table?.labels[1]).toLowerCase();
  const aggregatedRows = table?.labels.length === 2 &&
    /^(departamento|categor[ií]a|tipo|turno|per[ií]odo|mes|año|area|área|secci[oó]n)$/i.test(firstColumn) &&
    /^(total|cantidad|empleados|personas|n[uú]mero|valor|importe|conteo|count|gasto|coste)$/i.test(secondColumn);
  const canFanChart = Boolean(isChartSource || aggregatedRows);
  const numericRows = canFanChart ? table?.rows.filter(row=>row.length===2 && numeric(row[1])!==null && numeric(row[1])>=0) : [];
  if (table && !metrics.length && (!fan || !numericRows || numericRows.length < 2)) {
    metrics.push({label:'Registros recibidos',value:fmt(table.count),unit:''});
  }
  const heading = type === 'person' ? 'Resumen de ficha' :
    type === 'document' ? 'Informe disponible' :
    type === 'comparison' ? 'Comparativa ejecutiva' : 'Información de tu consulta';
  const kpisHTML = metrics.length ? `<div class="hg-kpis">${metrics.map(m=>
    `<article class="hg-kpi"><span>${escapeHTML(m.label)}</span><strong>${escapeHTML(m.value)}</strong>${m.unit ? `<small>${escapeHTML(m.unit)}</small>` : ''}</article>`).join('')}</div>` : '';
  // Personal table is never displayed on the physical fan by default.
  const screenTable = table && !fan ? `<div class="hg-mini-table"><div class="hg-mini-head"><b>${escapeHTML(table.title)}</b><small>${table.count} filas recibidas</small></div><table><thead><tr>${table.labels.map(c=>`<th>${escapeHTML(c)}</th>`).join('')}</tr></thead><tbody>${table.rows.map(row=>`<tr>${row.map(v=>`<td>${escapeHTML(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '';
  // On fan mode, an internal numeric table is retained offscreen so the stage
  // can produce real bars without exposing personal details on the projection.
  const fanChart = fan && numericRows?.length>=2 ? `<div class="hg-mini-table hg-chart-source" aria-hidden="true"><table><tbody>${numericRows.map(row=>`<tr><td>${escapeHTML(row[0])}</td><td>${escapeHTML(row[1])}</td></tr>`).join('')}</tbody></table></div>` : '';
  const docsHTML = !fan ? docs.map(d=>{
    const href=safeHref(d.url);
    return href ? `<a href="${escapeHTML(href)}" rel="noopener noreferrer" target="_blank">${escapeHTML(d.label)} ↗</a>` : '';
  }).filter(Boolean).join('') : '';
  // El correo (cuerpo, hilo) es contenido personal: igual que la tabla, nunca en el fan físico.
  const mailHTML = mail && !fan ? renderMailSection(mail) : '';
  // Las noticias son públicas (no personales), pero un listado de artículos no cabe en la
  // proyección física del fan: igual que el correo, solo se muestran en pantalla.
  const newsHTML = news && !fan ? renderNewsSection(news) : '';
  const status = !metrics.length && !table && !mail && !news ?
    `<p class="hg-result-status">${docs.length ? 'Informe disponible' :
      (answer ? 'mIA está explicando el resultado por voz' : 'Respuesta recibida')}</p>` : '';
  // In fan mode, structured content without numeric visualizations still needs a
  // clear visible status; the user's answer is delivered by voice.
  const fanFallback = fan && !metrics.length && !numericRows?.length ?
    '<div class="hg-fan-feedback">RESULTADO DISPONIBLE</div>' : '';
  const html = mailHTML
    ? mailHTML + (docsHTML ? `<div class="hg-documents">${docsHTML}</div>` : '')
    : newsHTML
    ? newsHTML
    : `<section class="hg-brief" aria-label="${escapeHTML(heading)}"><header class="hg-brief-head"><span>mIA · INSIGHTS</span><h2>${escapeHTML(heading)}</h2></header>${kpisHTML}${screenTable}${fanChart}${status}${docsHTML ? `<div class="hg-documents">${docsHTML}</div>` : ''}${fanFallback}</section>`;
  return {html, visible:true, hasPayload:true, counts:{ metrics:metrics.length, rows:table?.count || 0, docs:docs.length }};
}
