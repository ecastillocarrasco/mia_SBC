/** Vuelca una "presentation" del backend (tabla, KPIs, ficha…) a HTML genérico y legible.
 * Sin clasificación por tipo todavía (llegará en la fase de mejoras funcionales): aquí
 * basta con que cualquier resultado se pueda leer, sin perder datos. */

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function humanize(key) {
  return String(key ?? "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (Array.isArray(value)) return value.map(renderValue).join(", ");
  if (typeof value === "object") return Object.values(value).map(renderValue).join(" · ");
  return escapeHtml(String(value));
}

function renderTable(presentation) {
  const columns = presentation.columns || [];
  const rows = presentation.rows || [];
  return `
    <div class="mia-table-wrap">
      <table class="mia-table">
        <thead><tr>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
        <tbody>${rows
          .slice(0, 100)
          .map((row) => `<tr>${row.map((cell) => `<td>${renderValue(cell)}</td>`).join("")}</tr>`)
          .join("")}</tbody>
      </table>
      ${rows.length > 100 ? `<p class="mia-table-note">Mostrando 100 de ${rows.length} filas.</p>` : ""}
    </div>`;
}

function renderKeyValues(entries) {
  return `<dl class="mia-kv">${entries
    .map(([k, v]) => `<div><dt>${escapeHtml(humanize(k))}</dt><dd>${renderValue(v)}</dd></div>`)
    .join("")}</dl>`;
}

export function renderPresentation(presentation) {
  if (!presentation || typeof presentation !== "object") return "";
  const { type, title, ...rest } = presentation;
  const heading = title ? `<h3 class="mia-presentation-title">${escapeHtml(title)}</h3>` : "";
  if (type === "table" && Array.isArray(rest.columns)) {
    return `<section class="mia-presentation">${heading}${renderTable(rest)}</section>`;
  }
  if (type === "dashboard" && rest.kpis) {
    const kpis = renderKeyValues(Object.entries(rest.kpis));
    const tables = (rest.tables || []).map((t) => renderTable(t)).join("");
    return `<section class="mia-presentation">${heading}${kpis}${tables}</section>`;
  }
  if (type === "download" && rest.url) {
    return `<section class="mia-presentation">${heading}
      <a class="mia-download" href="${escapeHtml(rest.url)}" target="_blank" rel="noopener">
        Descargar ${escapeHtml(rest.format || "archivo")}
      </a></section>`;
  }
  const primitives = Object.entries(rest).filter(([, v]) => v === null || typeof v !== "object");
  const nested = Object.entries(rest).filter(([, v]) => v && typeof v === "object" && !Array.isArray(v));
  const arrays = Object.entries(rest).filter(([, v]) => Array.isArray(v) && v.length && typeof v[0] === "object");
  let body = renderKeyValues(primitives);
  for (const [key, value] of nested) {
    body += `<h4 class="mia-section-label">${escapeHtml(humanize(key))}</h4>${renderKeyValues(Object.entries(value))}`;
  }
  for (const [key, value] of arrays) {
    const columns = Object.keys(value[0]);
    body += `<h4 class="mia-section-label">${escapeHtml(humanize(key))}</h4>${renderTable({
      columns: columns.map(humanize),
      rows: value.map((row) => columns.map((c) => row[c])),
    })}`;
  }
  return `<section class="mia-presentation">${heading}${body}</section>`;
}
