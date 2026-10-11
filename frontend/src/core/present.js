/** Vuelca una "presentation" del backend (tabla, KPIs, ficha…) a HTML genérico y legible.
 * Sin clasificación por tipo todavía (llegará en la fase de mejoras funcionales): aquí
 * basta con que cualquier resultado se pueda leer, sin perder datos. */

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function humanize(key) {
  return String(key ?? "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── URL detection ─────────────────────────────────────────────────────────────

const URL_RX = /^(https?:\/\/|\/api\/)/;

function isUrl(value) {
  return typeof value === "string" && URL_RX.test(value.trim());
}

function urlLabel(url) {
  if (/\/api\/documents\/nomina\//.test(url)) return "Ver nómina";
  if (/\/api\/documents\/cv\//.test(url)) return "Ver CV";
  if (/\/api\/documents\//.test(url)) return "Abrir documento";
  if (/\/api\/reports\//.test(url)) return "Descargar informe";
  return "Ver";
}

function safeDocumentUrl(value) {
  const text = String(value ?? "").trim();
  if (/^\/api\/[\w/?=&%.-]+$/.test(text)) return text;
  try {
    const url = new URL(text);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function renderLink(url, label) {
  url = safeDocumentUrl(url);
  if (!url) return "—";
  return `<a class="mia-doc-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`;
}

// ── Document card ─────────────────────────────────────────────────────────────

function renderDocumentCard(doc) {
  if (!safeDocumentUrl(doc?.url)) return "";
  const meta = [doc.subtitle, doc.date].filter(Boolean).map(escapeHtml).join(" · ");
  return `<a class="mia-doc-card" href="${escapeHtml(safeDocumentUrl(doc.url))}" target="_blank" rel="noopener">
    <span class="mia-doc-body">
      <b>${escapeHtml(doc.title || urlLabel(doc.url))}</b>
      ${meta ? `<small>${meta}</small>` : ""}
    </span>
    <span class="mia-doc-arrow">↗</span>
  </a>`;
}

function renderDocumentList(docs) {
  const cards = docs.filter((d) => d?.url).map(renderDocumentCard).join("");
  if (!cards) return "";
  return `<div class="mia-doc-list">${cards}</div>`;
}

// ── Value renderer ────────────────────────────────────────────────────────────

function renderValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (typeof value === "string" && isUrl(value.trim())) {
    return renderLink(value.trim(), urlLabel(value.trim()));
  }
  if (Array.isArray(value)) return value.map(renderValue).join(", ");
  if (typeof value === "object") return Object.values(value).map(renderValue).join(" · ");
  return escapeHtml(String(value));
}

// ── Table ─────────────────────────────────────────────────────────────────────

function renderTable(presentation) {
  const columns = Array.isArray(presentation.columns) ? presentation.columns : [];
  const rows = Array.isArray(presentation.rows) ? presentation.rows : [];
  const keyFor = (c) => typeof c === "string" ? c : (c?.key || c?.field || c?.id || c?.name || c?.label || "");
  const labelFor = (c) => typeof c === "string" ? c : (c?.label || c?.title || keyFor(c));
  const cells = (row) => {
    if (Array.isArray(row)) return row;
    if (row && typeof row === "object") return columns.map((c) => row[keyFor(c)]);
    return [row];
  };
  return `
    <div class="mia-table-wrap">
      <table class="mia-table">
        <thead><tr>${columns.map((c) => `<th>${escapeHtml(labelFor(c))}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((row) => `<tr>${cells(row).map((cell) => `<td>${renderValue(cell)}</td>`).join("")}</tr>`).join("")}</tbody>
      </table>
    </div>`;
}

function renderKeyValues(entries) {
  return `<dl class="mia-kv">${entries
    .map(([k, v]) => `<div><dt>${escapeHtml(humanize(k))}</dt><dd>${renderValue(v)}</dd></div>`)
    .join("")}</dl>`;
}

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderPresentation(presentation) {
  if (!presentation || typeof presentation !== "object") return "";
  const { type, title, ...rest } = presentation;
  const heading = title ? `<h3 class="mia-presentation-title">${escapeHtml(title)}</h3>` : "";
  if ((type === "document" || type === "download") && rest.url && !safeDocumentUrl(rest.url)) return "";

  // Table — also render attached document cards when present
  if (type === "table" && Array.isArray(rest.columns)) {
    const docsHtml = Array.isArray(rest.documents) && rest.documents.length
      ? renderDocumentList(rest.documents)
      : "";
    return `<section class="mia-presentation">${heading}${renderTable(rest)}${docsHtml}</section>`;
  }

  // Dashboard with KPIs
  if (type === "dashboard" && rest.kpis) {
    const kpis = renderKeyValues(Object.entries(rest.kpis));
    const tables = (rest.tables || []).map((t) => renderTable(t)).join("");
    return `<section class="mia-presentation">${heading}${kpis}${tables}</section>`;
  }

  // Download button
  if (type === "download" && safeDocumentUrl(rest.url)) {
    return `<section class="mia-presentation">${heading}
      <a class="mia-download" href="${escapeHtml(safeDocumentUrl(rest.url))}" target="_blank" rel="noopener">
        Descargar ${escapeHtml(rest.file_name || rest.format || "archivo")}
      </a></section>`;
  }

  // Single document card
  if (type === "document" && rest.url) {
    return `<section class="mia-presentation">${heading}${renderDocumentCard(rest)}</section>`;
  }

  // Generic: separate primitive fields, nested objects, arrays
  const primitives = Object.entries(rest).filter(
    ([k, v]) => k !== "documents" && (v === null || typeof v !== "object"),
  );
  const nested = Object.entries(rest).filter(
    ([k, v]) => k !== "documents" && v && typeof v === "object" && !Array.isArray(v),
  );
  const arrays = Object.entries(rest).filter(
    ([k, v]) => k !== "documents" && Array.isArray(v) && v.length && typeof v[0] === "object",
  );

  let body = renderKeyValues(primitives);

  for (const [key, value] of nested) {
    body += `<h4 class="mia-section-label">${escapeHtml(humanize(key))}</h4>${renderKeyValues(Object.entries(value))}`;
  }

  for (const [key, value] of arrays) {
    // Arrays of document cards
    if (value[0]?.url && value[0]?.title !== undefined) {
      body += `<h4 class="mia-section-label">${escapeHtml(humanize(key))}</h4>${renderDocumentList(value)}`;
      continue;
    }
    const columns = Object.keys(value[0]);
    body += `<h4 class="mia-section-label">${escapeHtml(humanize(key))}</h4>${renderTable({
      columns: columns.map(humanize),
      rows: value.map((row) => columns.map((c) => row[c])),
    })}`;
  }

  // Explicit documents array (even when type is something else)
  if (Array.isArray(rest.documents) && rest.documents.length) {
    body += renderDocumentList(rest.documents);
  }

  return `<section class="mia-presentation">${heading}${body}</section>`;
}

/** Enlaces a las fuentes web consultadas ({url, title}); solo http(s). */
export function renderSources(sources) {
  const list = (sources || []).filter((s) => /^https?:\/\//i.test(s?.url || ""));
  if (!list.length) return "";
  const items = list
    .map((s, i) => {
      let host = "";
      try { host = new URL(s.url).hostname.replace(/^www\./, ""); } catch { /* noop */ }
      return `<a class="mia-source" href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer">
        <b>${i + 1}</b><span>${escapeHtml(s.title || host)}<small>${escapeHtml(host)}</small></span><i>↗</i></a>`;
    })
    .join("");
  return `<section class="mia-sources"><h4>Fuentes consultadas · ${list.length}</h4>${items}</section>`;
}
