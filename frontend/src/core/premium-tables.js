/**
 * Client-side progressive table presentation. NEVER truncates source rows.
 * Any table (including Employee360) is pageable at exactly 20 rows or fewer.
 * No content or business field is guessed or modified.
 */
export const PAGE_SIZE = 20;

function csvEscape(value) {
  let text = String(value ?? '').replace(/\r?\n/g, ' ');
  // Spreadsheet-formula injection protection when opening a CSV in Excel.
  if (/^\s*[=+@\-]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function toCsv(table, rows) {
  const headers = Array.from(table.tHead?.rows?.[0]?.cells ?? []).map((cell) => cell.textContent.trim());
  const body = rows.map((tr) => Array.from(tr.cells).map((cell) => cell.textContent.trim()));
  return '\uFEFF' + [headers, ...body].map((row) => row.map(csvEscape).join(';')).join('\r\n');
}

export function enhancePremiumTables(root, { pageSize = PAGE_SIZE, search = true, download = true } = {}) {
  if (!root) return 0;
  const tables = root.querySelectorAll('table');
  let upgraded = 0;
  for (const table of tables) {
    if (table.dataset.miaEnhanced === 'true') continue;
    const tbody = table.tBodies?.[0];
    if (!tbody || !tbody.rows.length) continue;
    const allRows = Array.from(tbody.rows);
    const limit = Math.min(PAGE_SIZE, Math.max(1, Number(pageSize) || PAGE_SIZE));
    if (allRows.length <= limit && !search) continue;
    table.dataset.miaEnhanced = 'true';
    table.classList.add('mia-premium-table');
    let rows = allRows;
    let page = 0;
    const toolbar = document.createElement('div');
    toolbar.className = 'mia-table-toolbar';
    const searchBox = document.createElement('input');
    searchBox.type = 'search';
    searchBox.className = 'mia-table-search';
    searchBox.placeholder = 'Buscar en todas las filas…';
    searchBox.setAttribute('aria-label', 'Filtrar tabla');
    const counter = document.createElement('span');
    counter.className = 'mia-table-count';
    const controls = document.createElement('div');
    controls.className = 'mia-table-controls';
    const back = document.createElement('button');
    const forward = document.createElement('button');
    back.type = forward.type = 'button';
    back.textContent = '← Anterior';
    forward.textContent = 'Siguiente →';
    back.setAttribute('aria-label', 'Página anterior');
    forward.setAttribute('aria-label', 'Página siguiente');
    const pageLabel = document.createElement('span');
    pageLabel.className = 'mia-table-page';
    controls.append(back, pageLabel, forward);
    if (search) toolbar.append(searchBox);
    toolbar.append(counter);
    if (download) {
      const exportButton = document.createElement('button');
      exportButton.type = 'button';
      exportButton.className = 'mia-table-export';
      exportButton.textContent = 'CSV ↓';
      exportButton.title = 'Exportar todas las filas filtradas';
      exportButton.addEventListener('click', () => {
        const blob = new Blob([toCsv(table, rows)], { type: 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'mIA_tabla.csv';
        anchor.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 2000);
      });
      toolbar.append(exportButton);
    }
    const holder = table.closest('.mia-table-wrap') || table.parentElement;
    holder.parentElement.insertBefore(toolbar, holder);
    holder.parentElement.insertBefore(controls, holder.nextSibling);
    function update() {
      page = Math.min(page, Math.max(0, Math.ceil(rows.length / limit) - 1));
      tbody.replaceChildren(...rows.slice(page * limit, (page + 1) * limit));
      const pages = Math.max(1, Math.ceil(rows.length / limit));
      const start = rows.length ? page * limit + 1 : 0;
      counter.textContent = `${start}–${Math.min(rows.length, (page + 1) * limit)} de ${rows.length}`;
      pageLabel.textContent = `${page + 1} / ${pages}`;
      back.disabled = page === 0;
      forward.disabled = page + 1 >= pages;
      controls.hidden = pages <= 1;
    }
    back.addEventListener('click', () => { page -= 1; update(); });
    forward.addEventListener('click', () => { page += 1; update(); });
    searchBox.addEventListener('input', () => {
      const term = searchBox.value.toLocaleLowerCase('es-ES').trim();
      rows = term ? allRows.filter((r) => r.textContent.toLocaleLowerCase('es-ES').includes(term)) : allRows;
      page = 0;
      update();
    });
    update();
    upgraded += 1;
  }
  return upgraded;
}

const ORDINARY_TEXT_KEYS = new Set([
  'answer', 'speech', 'text', 'message', 'description', 'summary', 'title', 'subtitle',
  'label', 'note', 'notes', 'status', 'intent', 'type', 'format', 'source', 'metadata',
]);

function meaningful(value, depth = 0) {
  if (value == null || depth >= 6) return false;
  if (Array.isArray(value)) return value.some((entry) => meaningful(entry, depth + 1));
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object') return Boolean(String(value).trim());
  const entries = Object.entries(value).filter(([k]) => !ORDINARY_TEXT_KEYS.has(k.toLowerCase()) && !k.startsWith('_'));
  return entries.some(([, v]) => meaningful(v, depth + 1));
}

export function hasPresentationData(presentations) {
  if (!Array.isArray(presentations)) return false;
  return presentations.some((p) => {
    if (!p || typeof p !== 'object') return false;
    const type = String(p.type || '').toLowerCase();
    if (['download', 'document'].includes(type)) return Boolean(p.url || p.documents?.length);
    if (type === 'table') return Array.isArray(p.rows) && p.rows.length > 0;
    if (type === 'dashboard') return meaningful(p.kpis) || meaningful(p.tables) || meaningful(p.cards);
    if (['text', 'conversation', 'markdown', 'message'].includes(type)) return false;
    return meaningful(p);
  });
}

export function presentationType(presentations = []) {
  const text = presentations.map((p) => `${p?.type || ''} ${p?.title || ''}`).join(' ').toLowerCase();
  if (/employee360|emplead|ficha|persona/.test(text)) return 'person';
  if (/informe|report|download|pdf|excel|document|archivo|n[oó]mina/.test(text)) return 'document';
  if (/compar|contraste|versus/.test(text)) return 'comparison';
  if (/dashboard|chart|gr[aá]f|estad|kpi|analytic|evoluc/.test(text)) return 'analytics';
  if (/table|list|lista|turno|shift/.test(text)) return 'data';
  return 'data';
}
