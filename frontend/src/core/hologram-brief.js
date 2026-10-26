/** Compact, evidence-based summaries for the hologram world. */
function esc(v) {
  return String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}
function label(key) {
  return String(key).replace(/[_-]/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2');
}
function fmt(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 }).format(value);
  }
  return String(value ?? '—');
}
function safeUrl(value) {
  if (typeof value !== 'string') return '';
  if (/^\/api\/[\w/?=&%.-]+$/.test(value)) return value;
  try {
    const url = new URL(value, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
}
function extractMetrics(presentations) {
  const metrics = [];
  const seen = new Set();
  const add = (name, value, unit) => {
    if (value == null || typeof value === 'object' || value === '') return;
    const key = String(name).toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    metrics.push({ name: String(name), value: fmt(value), unit: String(unit || '') });
  };
  for (const p of presentations) {
    if (!p || typeof p !== 'object') continue;
    if (p.kpis && !Array.isArray(p.kpis) && typeof p.kpis === 'object') {
      for (const [k, v] of Object.entries(p.kpis)) {
        if (typeof v === 'object') add(v.label || k, v.value, v.unit);
        else add(label(k), v);
      }
    }
    if (Array.isArray(p.kpis)) {
      for (const v of p.kpis) add(v.label || v.title || 'Indicador', v.value, v.unit);
    }
    if (Array.isArray(p.cards)) {
      for (const c of p.cards) add(c.label || c.title || 'Indicador', c.value, c.unit);
    }
    if (p.type === 'metric' && 'value' in p) add(p.label || p.title || 'Indicador', p.value, p.unit);
  }
  return metrics.slice(0, 4);
}
function extractTable(presentations) {
  for (const p of presentations) {
    const candidates = [p, ...(Array.isArray(p?.tables) ? p.tables : [])];
    for (const table of candidates) {
      if (!Array.isArray(table?.columns) || !Array.isArray(table?.rows) || !table.rows.length) continue;
      return {
        title: table.title || p.title || 'Indicadores principales',
        count: table.rows.length,
        columns: table.columns.slice(0, 3),
        rows: table.rows.slice(0, 5).map((row) => Array.isArray(row) ? row.slice(0, 3) : []),
      };
    }
  }
  return null;
}
function extractDocuments(presentations) {
  const docs = [];
  for (const p of presentations) {
    if (p?.url) docs.push({ name: p.title || p.file_name || 'Abrir informe', url: p.url });
    if (Array.isArray(p?.documents)) docs.push(...p.documents.map((d) => ({ name: d.title || 'Documento', url: d.url })));
  }
  return docs.filter((d) => safeUrl(d.url)).slice(0, 2);
}
export function renderHologramBrief(presentations = [], { type = 'analytics' } = {}) {
  const kpis = extractMetrics(presentations);
  const table = extractTable(presentations);
  const docs = extractDocuments(presentations);
  if (!kpis.length && !table && !docs.length) return '';
  const title = type === 'document' ? 'Informe preparado'
    : type === 'comparison' ? 'Comparativa ejecutiva'
    : type === 'person' ? 'Resumen de ficha'
    : 'Resumen ejecutivo';
  return `<section class="hg-brief" aria-label="${esc(title)}">
    <header class="hg-brief-head"><span>mIA · INSIGHTS</span><h2>${esc(title)}</h2></header>
    ${kpis.length ? `<div class="hg-kpis">${kpis.map((k) => `<article class="hg-kpi"><span>${esc(k.name)}</span><strong>${esc(k.value)}</strong>${k.unit ? `<small>${esc(k.unit)}</small>` : ''}</article>`).join('')}</div>` : ''}
    ${table ? `<div class="hg-mini-table"><div class="hg-mini-head"><b>${esc(table.title)}</b><small>${table.count} registros en el informe completo</small></div><table><thead><tr>${table.columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${table.rows.map((r) => `<tr>${r.map((cell) => `<td>${esc(fmt(cell))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
    ${docs.length ? `<div class="hg-documents">${docs.map((d) => {
      const url = safeUrl(d.url);
      // /api/... exige Authorization: Bearer, que un <a href> normal no puede mandar (401 real
      // en preprod 2026-10-26) -- boton con data-download-url, recogido por el listener
      // delegado de #result en main.js. Una URL externa genuina sigue como enlace normal.
      return /^\/api\//.test(url)
        ? `<button type="button" class="hg-doc-link" data-download-url="${esc(url)}" data-download-name="${esc(d.name)}">${esc(d.name)} ↓</button>`
        : `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(d.name)} ↗</a>`;
    }).join('')}</div>` : ''}
  </section>`;
}
