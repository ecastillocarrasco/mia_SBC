/** Vuelca una "presentation" del backend (tabla, KPIs, ficha…) a HTML genérico y legible.
 * Sin clasificación por tipo todavía (llegará en la fase de mejoras funcionales): aquí
 * basta con que cualquier resultado se pueda leer, sin perder datos. */

import { renderCalendar } from './calendar-view.js';

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

// /api/... exige Authorization: Bearer, que un <a href> normal no puede mandar (401 real en
// preprod 2026-10-26 al abrir el CV de un candidato) -- mismo patron de boton+data-download-url
// ya cableado para informes, con el listener de clic de cada mundo (ver 3d/main.js).
function isApiPath(url) {
  return typeof url === "string" && url.startsWith("/api/");
}

function renderLink(url, label) {
  url = safeDocumentUrl(url);
  if (!url) return "—";
  if (isApiPath(url)) {
    return `<button type="button" class="mia-doc-link" data-download-url="${escapeHtml(url)}" data-download-name="${escapeHtml(label)}">${escapeHtml(label)}</button>`;
  }
  return `<a class="mia-doc-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`;
}

// ── Document card ─────────────────────────────────────────────────────────────

function renderDocumentCard(doc) {
  const url = safeDocumentUrl(doc?.url);
  if (!url) return "";
  const meta = [doc.subtitle, doc.date].filter(Boolean).map(escapeHtml).join(" · ");
  const title = escapeHtml(doc.title || urlLabel(doc.url));
  const body = `<span class="mia-doc-body">
      <b>${title}</b>
      ${meta ? `<small>${meta}</small>` : ""}
    </span>
    <span class="mia-doc-arrow">↗</span>`;
  if (isApiPath(url)) {
    return `<button type="button" class="mia-doc-card" data-download-url="${escapeHtml(url)}" data-download-name="${title}">${body}</button>`;
  }
  return `<a class="mia-doc-card" href="${escapeHtml(url)}" target="_blank" rel="noopener">${body}</a>`;
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

// ── Charts (vista previa de informes) ───────────────────────────────────────────
// Paleta categórica validada (dataviz skill, scripts/validate_palette.js --mode dark): CVD Delta E
// >= 8 y normal-vision Delta E >= 15 en cada par adyacente. Solo los pasos oscuros -- este fichero
// nunca alterna claro/oscuro (ver present.css), así que no hace falta la variante clara.
const MIA_CHART_PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

function chartSeriesValues(chart) {
  const series = Array.isArray(chart.series) ? chart.series : [];
  return series.length ? (Array.isArray(series[0].values) ? series[0].values.map((v) => Number(v) || 0) : []) : [];
}

function fmtChartValue(value) {
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 }).format(Number(value) || 0);
}

function renderDonutChart(chart) {
  const labels = Array.isArray(chart.labels) ? chart.labels : [];
  const values = chartSeriesValues(chart);
  const total = values.reduce((a, b) => a + Math.abs(b), 0);
  if (!total) return "";
  let offset = 0;
  const slices = values
    .map((v, i) => {
      const start = (offset / total) * 100;
      offset += Math.abs(v);
      const end = (offset / total) * 100;
      return `${MIA_CHART_PALETTE[i % MIA_CHART_PALETTE.length]} ${start.toFixed(2)}% ${end.toFixed(2)}%`;
    })
    .join(",");
  const legend = values
    .map((v, i) => {
      const pct = total ? Math.round((Math.abs(v) / total) * 100) : 0;
      return `<div><i style="background:${MIA_CHART_PALETTE[i % MIA_CHART_PALETTE.length]}"></i>
        <span>${escapeHtml(labels[i] ?? "—")}</span>
        <b>${fmtChartValue(v)} <small>${pct}%</small></b></div>`;
    })
    .join("");
  return `<div class="mia-chart-donut-layout">
    <div class="mia-chart-donut" style="background:conic-gradient(${slices})"><span>${escapeHtml(fmtChartValue(total))}</span></div>
    <div class="mia-chart-legend">${legend}</div>
  </div>`;
}

function renderBarChart(chart) {
  const labels = Array.isArray(chart.labels) ? chart.labels : [];
  const values = chartSeriesValues(chart);
  if (!labels.length) return "";
  const max = Math.max(1, ...values.map((v) => Math.abs(v)));
  const rows = labels
    .map((label, i) => {
      const v = values[i] || 0;
      const width = Math.max(2, (Math.abs(v) / max) * 100);
      return `<div class="mia-chart-bar-row">
        <span>${escapeHtml(label)}</span>
        <div class="mia-chart-bar-track"><div class="mia-chart-bar-fill" style="width:${width}%;background:${MIA_CHART_PALETTE[0]}"></div></div>
        <strong>${fmtChartValue(v)}</strong>
      </div>`;
    })
    .join("");
  return `<div class="mia-chart-bars">${rows}</div>`;
}

function renderLineChart(chart) {
  const labels = Array.isArray(chart.labels) ? chart.labels : [];
  const series = Array.isArray(chart.series) ? chart.series : [];
  if (!series.length) return "";
  const allValues = series.flatMap((s) => (Array.isArray(s.values) ? s.values.map((v) => Number(v) || 0) : []));
  if (!allValues.length) return "";
  const max = Math.max(...allValues), min = Math.min(0, ...allValues);
  const w = 320, h = 100, pad = 10;
  const polylines = series
    .map((s, si) => {
      const vals = Array.isArray(s.values) ? s.values : [];
      if (!vals.length) return "";
      const step = (w - 2 * pad) / Math.max(1, vals.length - 1);
      const pts = vals
        .map((v, i) => {
          const x = pad + i * step;
          const y = h - pad - (((Number(v) || 0) - min) / ((max - min) || 1)) * (h - 2 * pad);
          return `${x},${y}`;
        })
        .join(" ");
      return `<polyline points="${pts}" fill="none" stroke="${MIA_CHART_PALETTE[si % MIA_CHART_PALETTE.length]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
    })
    .join("");
  const axis = labels.length
    ? `<div class="mia-chart-line-axis">${labels.map((l) => `<span>${escapeHtml(l)}</span>`).join("")}</div>`
    : "";
  const legend = series.length > 1
    ? `<div class="mia-chart-legend">${series
        .map((s, i) => `<div><i style="background:${MIA_CHART_PALETTE[i % MIA_CHART_PALETTE.length]}"></i><span>${escapeHtml(s.name ?? "Serie " + (i + 1))}</span></div>`)
        .join("")}</div>`
    : "";
  return `<svg class="mia-chart-line-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${polylines}</svg>${axis}${legend}`;
}

function renderCharts(charts) {
  const list = Array.isArray(charts) ? charts.filter((c) => c && typeof c === "object") : [];
  if (!list.length) return "";
  const boxes = list
    .map((chart) => {
      const type = String(chart.type || "");
      const body = type === "donut" ? renderDonutChart(chart) : type === "line" ? renderLineChart(chart) : renderBarChart(chart);
      if (!body) return "";
      return `<div class="mia-chart-box">
        <div class="mia-chart-box-title">${escapeHtml(chart.title || "Gráfico")}</div>
        ${body}
      </div>`;
    })
    .join("");
  return boxes ? `<div class="mia-charts-panel">${boxes}</div>` : "";
}

// Vista previa de un informe (ver persist_document_report -> preview en el backend): un adelanto
// ampliado -- tabla(s) comparativa(s) recortadas + gráficos de primera clase que el documento ya
// traía -- nunca el informe completo, que solo se entrega como fichero descargable. Pensado para
// 2D/3D; Holograma sigue con sus tarjetas KPI compactas (ver legacy_view._absorb_report_preview
// para la ruta equivalente del mundo 2D, que reutiliza data.table/data.charts ya existentes en vez
// de este renderizador).
function renderReportPreview(preview) {
  if (!preview || typeof preview !== "object") return "";
  const tables = Array.isArray(preview.tables) ? preview.tables : [];
  const charts = Array.isArray(preview.charts) ? preview.charts : [];
  const tablesHtml = tables
    .map((t) => {
      if (!t || !Array.isArray(t.columns) || !t.columns.length) return "";
      const note = t.truncated
        ? `<p class="mia-report-preview-note">Mostrando ${t.rows.length} de ${t.total_rows} filas -- el detalle completo está en el informe descargable.</p>`
        : "";
      const title = t.title ? `<h4 class="mia-section-label">${escapeHtml(t.title)}</h4>` : "";
      return `${title}${renderTable(t)}${note}`;
    })
    .join("");
  const chartsHtml = renderCharts(charts);
  return tablesHtml || chartsHtml ? `<div class="mia-report-preview">${tablesHtml}${chartsHtml}</div>` : "";
}

// ── Mail ───────────────────────────────────────────────────────────────────────

function renderAttachmentCard(att) {
  const url = safeDocumentUrl(att?.url);
  if (!url) return `<span class="mia-mail-attachment mia-mail-attachment--unavailable">${escapeHtml(att?.nombre || "Adjunto")}</span>`;
  // Nunca un <a href> directo: /api/mail/attachment/... exige token (Authorization Bearer), que
  // un enlace normal no puede mandar y daría 401. Botón + fetch autenticado + blob, delegado por
  // el mundo que lo monta (mismo patrón que attachmentCard() en mia-enhance.js, 2D).
  return `<button type="button" class="mia-mail-attachment" data-attachment-url="${escapeHtml(url)}" data-attachment-name="${escapeHtml(att?.nombre || "Adjunto")}">
    <span class="mia-mail-attachment-name">${escapeHtml(att?.nombre || "Adjunto")}</span>
    <span class="mia-mail-attachment-action">Descargar ↓</span>
  </button>`;
}

function renderMailBody(text) {
  const blocks = String(text ?? "").split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  if (!blocks.length) return "";
  return `<div class="mia-mail-body">${blocks
    .map((b) => `<p>${escapeHtml(b).replaceAll("\n", "<br>")}</p>`)
    .join("")}</div>`;
}

function renderMailActions(ref, noReply) {
  return `<div class="mia-mail-actions">
    <button type="button" class="mia-mail-action" data-mail-action="open" data-mail-ref="${escapeHtml(ref)}">Abrir correo</button>
    <button type="button" class="mia-mail-action mia-mail-action--primary" data-mail-action="reply" data-mail-ref="${escapeHtml(ref)}"${noReply ? " disabled title=\"Correo automático: no admite respuesta\"" : ""}>Proponer respuesta</button>
  </div>`;
}

function renderMailList(rows) {
  const items = rows.map((row) => `<li class="mia-mail-list-item${row.is_read ? "" : " mia-mail-list-item--unread"}">
    <div class="mia-mail-list-top"><b>${escapeHtml(row.from || "")}</b><span>${escapeHtml(row.received_at || "")}</span></div>
    <div class="mia-mail-list-subject">${escapeHtml(row.subject || "")}</div>
    ${row.preview ? `<div class="mia-mail-list-preview">${escapeHtml(row.preview)}</div>` : ""}
    ${row.has_attachments ? '<span class="mia-mail-thread-flag">📎 Con adjuntos</span>' : ""}
    ${row.ref ? renderMailActions(row.ref, row.no_reply) : ""}
  </li>`).join("");
  return `<ul class="mia-mail-list">${items}</ul>`;
}

function renderMailDraft(rest) {
  const status = rest.envio_habilitado === false ? "El envío de correos está desactivado en este entorno." : "Borrador guardado. Confírmalo para enviarlo.";
  return `<article class="mia-mail-card mia-mail-draft">
    ${renderMailBody(rest.texto)}
    <p class="mia-mail-draft-status">${escapeHtml(status)}</p>
  </article>`;
}

function renderMailMessage(rest) {
  const recipients = Array.isArray(rest.para) ? rest.para.join(", ") : rest.para;
  const meta = [
    rest.de ? `<span><b>De:</b> ${escapeHtml(rest.de)}</span>` : "",
    recipients ? `<span><b>Para:</b> ${escapeHtml(recipients)}</span>` : "",
    rest.recibido ? `<span>${escapeHtml(rest.recibido)}</span>` : "",
  ].filter(Boolean).join("");
  const attachments = Array.isArray(rest.adjuntos) && rest.adjuntos.length
    ? `<div class="mia-mail-attachments">${rest.adjuntos.map(renderAttachmentCard).join("")}</div>`
    : "";
  return `<article class="mia-mail-card">
    ${rest.asunto ? `<h3 class="mia-mail-subject">${escapeHtml(rest.asunto)}</h3>` : ""}
    <div class="mia-mail-meta">${meta}</div>
    ${renderMailBody(rest.texto)}
    ${attachments}
  </article>`;
}

function renderMailThread(rest) {
  const rows = Array.isArray(rest.mail_rows) ? rest.mail_rows : [];
  const items = rows.map((row) => `<li class="mia-mail-thread-item${row.is_read ? "" : " mia-mail-thread-item--unread"}">
    <div class="mia-mail-thread-top"><b>${escapeHtml(row.from || "")}</b><span>${escapeHtml(row.received_at || "")}</span></div>
    <div class="mia-mail-thread-subject">${escapeHtml(row.subject || "")}</div>
    <div class="mia-mail-thread-preview">${escapeHtml(row.preview || "")}</div>
    ${row.has_attachments ? '<span class="mia-mail-thread-flag">📎 Con adjuntos</span>' : ""}
  </li>`).join("");
  return `<ol class="mia-mail-thread">${items}</ol>`;
}

// ── Noticias ───────────────────────────────────────────────────────────────────

function newsExternalLink(url) {
  const text = String(url ?? "").trim();
  try {
    const parsed = new URL(text);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch { return ""; }
}

function renderNewsCard(item) {
  const link = newsExternalLink(item?.url);
  const title = escapeHtml(item?.titulo || "Noticia");
  const titleHtml = link
    ? `<a class="mia-news-title" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${title}</a>`
    : `<span class="mia-news-title">${title}</span>`;
  const meta = [item?.fuente, item?.fecha].filter(Boolean).map(escapeHtml).join(" · ");
  return `<li class="mia-news-card">
    <div class="mia-news-badges">
      ${item?.empresa ? `<span class="mia-news-badge mia-news-badge--empresa">${escapeHtml(item.empresa)}</span>` : ""}
      ${item?.categoria ? `<span class="mia-news-badge mia-news-badge--categoria">${escapeHtml(item.categoria)}</span>` : ""}
    </div>
    ${titleHtml}
    ${item?.resumen ? `<p class="mia-news-summary">${escapeHtml(item.resumen)}</p>` : ""}
    ${meta ? `<div class="mia-news-meta">${meta}</div>` : ""}
  </li>`;
}

function renderNewsList(rows) {
  if (!Array.isArray(rows) || !rows.length) return "";
  return `<ul class="mia-news-list">${rows.map(renderNewsCard).join("")}</ul>`;
}

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderPresentation(presentation) {
  if (!presentation || typeof presentation !== "object") return "";
    if (presentation.type === 'calendar') return renderCalendar(presentation);
  const { type, title, ...rest } = presentation;
  const heading = title ? `<h3 class="mia-presentation-title">${escapeHtml(title)}</h3>` : "";
  if ((type === "document" || type === "download") && rest.url && !safeDocumentUrl(rest.url)) return "";

  // Mail: an opened message (with real attachment download links) or a full thread
  if (type === "mail") {
    return `<section class="mia-presentation">${heading}${renderMailMessage(rest)}</section>`;
  }
  if (type === "mail_thread") {
    const count = rest.mensajes_en_el_hilo || (Array.isArray(rest.mail_rows) ? rest.mail_rows.length : 0);
    return `<section class="mia-presentation">${heading}
      <p class="mia-mail-thread-count">${count} mensaje${count === 1 ? "" : "s"} en esta conversación</p>
      ${renderMailThread(rest)}</section>`;
  }
  if (type === "mail_draft") {
    return `<section class="mia-presentation">${heading}${renderMailDraft(rest)}</section>`;
  }

  // Listado de correos (correos_recientes, correos_sin_leer, buscar_correos): lista de correo
  // con acciones de abrir/responder, nunca la tabla genérica (que acababa tratándose como datos
  // estadísticos a comparar — ver la exclusión en statistical-visuals.js).
  if (type === "table" && Array.isArray(rest.mail_rows) && rest.mail_rows.length) {
    return `<section class="mia-presentation">${heading}${renderMailList(rest.mail_rows)}</section>`;
  }

  // Noticias corporativas y de grupo: tarjetas (título enlazado, empresa/categoría, fuente/fecha)
  if (type === "news_list") {
    const list = renderNewsList(rest.news_rows) || renderTable(rest);
    return `<section class="mia-presentation">${heading}${list}</section>`;
  }

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

  // Download button. Nunca un <a href> directo: /api/reports/... exige token (Authorization
  // Bearer), que un <a> normal no puede mandar (daría 401 -- incidencia real en preprod
  // 2026-10-25). Botón con los datos en data-*; el fetch+blob real se cablea en el listener de
  // clic de cada mundo (mismo patrón ya usado para adjuntos de correo, ver 3d/main.js).
  if (type === "download" && safeDocumentUrl(rest.url)) {
    const name = escapeHtml(rest.file_name || rest.format || "archivo");
    const preview = renderReportPreview(rest.preview);
    return `<section class="mia-presentation">${heading}${preview}
      <button type="button" class="mia-download" data-download-url="${escapeHtml(safeDocumentUrl(rest.url))}" data-download-name="${name}">
        Descargar ${name}
      </button></section>`;
  }

  // Several formats generated in the same request (p. ej. PDF + Excel a la vez): un botón por
  // formato, mismo contrato de seguridad de URL que el botón de descarga individual.
  if (type === "downloads" && Array.isArray(rest.items) && rest.items.length) {
    const links = rest.items
      .filter((item) => item && safeDocumentUrl(item.url))
      .map((item) => {
        const name = escapeHtml(item.file_name || item.format || "archivo");
        return `<button type="button" class="mia-download" data-download-url="${escapeHtml(safeDocumentUrl(item.url))}" data-download-name="${name}">
        Descargar ${name}
      </button>`;
      })
      .join("");
    if (!links) return "";
    const preview = renderReportPreview(rest.preview);
    return `<section class="mia-presentation">${heading}${preview}<div class="mia-download-group">${links}</div></section>`;
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
