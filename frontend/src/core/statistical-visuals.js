const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");

const humanize = (value) => String(value ?? "")
  .replaceAll("_", " ")
  .replace(/\b\w/g, (c) => c.toUpperCase());

function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const cleaned = value
    .trim()
    .replace(/\s/g, "")
    .replace(/%$/, "")
    .replace(/\.(?=\d{3}(?:\D|$))/g, "")
    .replace(",", ".")
    .replace(/[^\d+\-.]/g, "");
  if (!cleaned || cleaned === "-" || cleaned === ".") return null;
  const number = Number(cleaned);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value) {
  const abs = Math.abs(value);
  const maximumFractionDigits = Number.isInteger(value) || abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits }).format(value);
}

function flattenTables(presentation) {
  const tables = [];
  if (!presentation || typeof presentation !== "object") return tables;

  // Un listado de correos (mail_rows) nunca es "datos a comparar/graficar": tratarlo como
  // tabla estadística es lo que producía la vista de "categorías/comparativa/CSV" en vez de
  // un listado de correo legible. present.js ya lo renderiza aparte como lista de correo.
  if (
    presentation.type === "table" &&
    Array.isArray(presentation.columns) &&
    Array.isArray(presentation.rows) &&
    !Array.isArray(presentation.mail_rows)
  ) {
    tables.push({
      title: presentation.title || "Datos",
      columns: presentation.columns,
      rows: presentation.rows,
    });
  }

  if (presentation.type === "dashboard" && Array.isArray(presentation.tables)) {
    for (const table of presentation.tables) {
      if (Array.isArray(table?.columns) && Array.isArray(table?.rows)) {
        tables.push({
          title: table.title || presentation.title || "Datos",
          columns: table.columns,
          rows: table.rows,
        });
      }
    }
  }

  for (const [key, value] of Object.entries(presentation)) {
    if (key === "mail_rows") continue; // ver nota de arriba: nunca es una tabla de datos a graficar.
    if (!Array.isArray(value) || !value.length || typeof value[0] !== "object" || Array.isArray(value[0])) continue;
    const columns = Object.keys(value[0]);
    if (columns.length < 2) continue;
    tables.push({
      title: presentation.title ? `${presentation.title} · ${humanize(key)}` : humanize(key),
      columns,
      rows: value.map((row) => columns.map((column) => row?.[column])),
    });
  }

  return tables;
}

function detectTableSeries(table) {
  const { columns = [], rows = [] } = table;
  if (columns.length < 2 || rows.length < 2) return null;

  const columnStats = columns.map((column, index) => {
    let numeric = 0;
    let text = 0;
    for (const row of rows) {
      if (asNumber(row?.[index]) !== null) numeric += 1;
      else if (row?.[index] !== null && row?.[index] !== undefined && String(row[index]).trim()) text += 1;
    }
    return { column, index, numeric, text };
  });

  const category = columnStats.find((item) => item.text >= Math.max(1, Math.ceil(rows.length * 0.45))) || columnStats[0];
  const numericColumns = columnStats.filter((item) => item.index !== category.index && item.numeric >= Math.max(2, Math.ceil(rows.length * 0.55)));
  if (!numericColumns.length) return null;

  return {
    categoryIndex: category.index,
    categoryLabel: category.column,
    metrics: numericColumns,
    rows,
  };
}

function isChronological(labels) {
  if (labels.length < 3) return false;
  const monthRx = /^(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b/i;
  const dateRx = /^\d{1,2}[\/-]\d{1,2}(?:[\/-]\d{2,4})?$|^\d{4}[\/-]\d{1,2}/;
  const yearRx = /^(19|20)\d{2}$/;
  const matches = labels.filter((label) => monthRx.test(label) || dateRx.test(label) || yearRx.test(label)).length;
  return matches >= Math.ceil(labels.length * 0.7);
}

function renderBars(title, categoryLabel, rows, metric) {
  const entries = rows
    .map((row) => ({ label: String(row?.[0] ?? "—"), value: asNumber(row?.[1]) }))
    .filter((entry) => entry.value !== null && entry.value !== 0);
  if (entries.length < 2) return "";

  const max = Math.max(...entries.map((entry) => Math.abs(entry.value)), 1);
  if (max < 0.5) return "";
  const visible = [...entries].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 12);
  const grandTotal = entries.reduce((s, e) => s + Math.abs(e.value), 0);
  const showPct = grandTotal > 0 && entries.length >= 2;
  const total = entries.length;

  return `
    <section class="stat-chart stat-bars" aria-label="${esc(title)}">
      <header class="stat-chart-head">
        <div><span>Comparativa</span><strong>${esc(title)}</strong></div>
        <small>${visible.length}${total > visible.length ? ` de ${total}` : ""} elementos · ${esc(formatNumber(grandTotal))} total</small>
      </header>
      <div class="stat-bars-list">
        ${visible.map((entry, idx) => {
          const width = Math.max(4, Math.min(100, (Math.abs(entry.value) / max) * 100));
          const pct = showPct ? Math.round((Math.abs(entry.value) / grandTotal) * 100) : null;
          return `<div class="stat-bar-row${idx === 0 ? " is-top" : ""}">
            <span class="stat-bar-label" title="${esc(entry.label)}">${esc(entry.label)}</span>
            <div class="stat-bar-track"><i style="--bar:${width}%"></i></div>
            <b>${esc(formatNumber(entry.value))}${pct !== null ? `<small>${pct}%</small>` : ""}</b>
          </div>`;
        }).join("")}
      </div>
      <footer>${esc(humanize(categoryLabel))} · ${esc(humanize(metric.column))}</footer>
    </section>`;
}

function renderLine(title, rows, metric) {
  const values = rows.map((row) => asNumber(row?.[1])).filter((value) => value !== null);
  if (values.length < 3) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max - min < 0.001 && max < 0.5) return "";
  const range = Math.max(max - min, 1);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100;
    const y = 88 - ((value - min) / range) * 72;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const firstLabel = String(rows[0]?.[0] ?? "");
  const lastLabel = String(rows[rows.length - 1]?.[0] ?? "");

  return `
    <section class="stat-chart stat-line" aria-label="${esc(title)}">
      <header class="stat-chart-head">
        <div><span>Evolución</span><strong>${esc(title)}</strong></div>
        <small>${values.length} puntos</small>
      </header>
      <div class="stat-line-stage">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path class="stat-line-grid" d="M0 16H100 M0 40H100 M0 64H100 M0 88H100" />
          <polyline class="stat-line-path" points="${points}" />
        </svg>
        <div class="stat-line-value top">${esc(formatNumber(max))}</div>
        <div class="stat-line-value bottom">${esc(formatNumber(min))}</div>
      </div>
      <footer><span>${esc(firstLabel)}</span><span>${esc(humanize(metric.column))}</span><span>${esc(lastLabel)}</span></footer>
    </section>`;
}

function renderTableDonut(title, categoryLabel, rows, metric) {
  const palette = ["#d1a85c", "#83d0ca", "#e87959", "#90a7d4", "#b99bd6", "#7c9295", "#d6b88e"];
  const positive = rows.filter((row) => (asNumber(row?.[1]) ?? 0) > 0);
  if (positive.length < 2) return "";
  const total = positive.reduce((sum, row) => sum + (asNumber(row?.[1]) ?? 0), 0);
  if (!total) return "";

  let offset = 0;
  const slices = positive.map((row, index) => {
    const value = asNumber(row?.[1]) ?? 0;
    const start = (offset / total) * 100;
    offset += value;
    const end = (offset / total) * 100;
    return `${palette[index % palette.length]} ${start.toFixed(2)}% ${end.toFixed(2)}%`;
  }).join(",");

  return `<section class="stat-chart stat-donut-card">
    <header class="stat-chart-head">
      <div><span>Distribución</span><strong>${esc(title)}</strong></div>
      <small>${esc(humanize(metric.column))}</small>
    </header>
    <div class="stat-donut-layout">
      <div class="stat-donut" style="background:conic-gradient(${slices})">
        <span><b>${formatNumber(total)}</b><small>Total</small></span>
      </div>
      <div class="stat-donut-legend">
        ${positive.map((row, index) => {
          const v = asNumber(row?.[1]) ?? 0;
          const pct = total > 0 ? Math.round((v / total) * 100) : 0;
          return `<div>
            <i style="--legend:${palette[index % palette.length]}"></i>
            <span title="${esc(String(row?.[0] ?? ""))}">${esc(String(row?.[0] ?? ""))}</span>
            <b>${esc(formatNumber(v))} <small>${pct}%</small></b>
          </div>`;
        }).join("")}
      </div>
    </div>
  </section>`;
}

function tryAggregateMonthly(rows) {
  const dateRx = /^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$/;
  const buckets = new Map();
  for (const [label, value] of rows) {
    const m = dateRx.exec(String(label ?? "").trim());
    if (!m) return null;
    const [, , mm, yy] = m;
    const yyyy = yy.length === 2 ? `20${yy}` : yy;
    const key = `${mm.padStart(2, "0")}/${yyyy}`;
    buckets.set(key, (buckets.get(key) ?? 0) + (asNumber(value) ?? 0));
  }
  if (buckets.size < 2) return null;
  return [...buckets.entries()].map(([k, v]) => [k, v]);
}

function renderKpiSummary(table, detected) {
  const metric = detected.metrics[0];
  const values = detected.rows.map((row) => asNumber(row?.[metric.index])).filter((value) => value !== null);
  if (values.length < 2) return "";

  const total = values.reduce((sum, value) => sum + value, 0);
  const average = total / values.length;
  let peakIndex = 0;
  for (let index = 1; index < values.length; index += 1) {
    if (values[index] > values[peakIndex]) peakIndex = index;
  }
  const numericRows = detected.rows.filter((row) => asNumber(row?.[metric.index]) !== null);
  const peakRow = numericRows[peakIndex];
  const peakLabel = String(peakRow?.[detected.categoryIndex] ?? "—");
  const peakValue = asNumber(peakRow?.[metric.index]) ?? 0;

  return `<div class="stat-kpis">
    <article><span>Categorías</span><strong>${values.length}</strong><small>${esc(humanize(detected.categoryLabel))}</small></article>
    <article><span>Media</span><strong>${esc(formatNumber(average))}</strong><small>${esc(humanize(metric.column))}</small></article>
    <article><span>Mayor valor</span><strong>${esc(formatNumber(peakValue))}</strong><small title="${esc(peakLabel)}">${esc(peakLabel)}</small></article>
  </div>`;
}

function normalizeRows(detected, metric) {
  return detected.rows.map((row) => [row?.[detected.categoryIndex], row?.[metric.index]]);
}

function analyticsIntent(presentations, query = "") {
  const presentationText = presentations
    .map((item) => `${item?.type || ""} ${item?.title || ""}`)
    .join(" ")
    .toLowerCase();
  const text = `${query} ${presentationText}`.toLowerCase();
  return /compar|an[aá]li|estad|evolu|distribu|departament|kpi|dashboard|gr[aá]f/.test(text);
}

export function renderStatisticalVisuals(presentations = [], { query = "", compact = false } = {}) {
  if (!Array.isArray(presentations) || !presentations.length) return "";

  const tables = presentations.flatMap(flattenTables);
  const candidates = tables
    .map((table) => ({ table, detected: detectTableSeries(table) }))
    .filter((item) => item.detected && item.detected.rows.length >= 2);

  if (!candidates.length) return "";

  // Sort: prefer tables with multiple metrics and more rows (richer data first)
  candidates.sort((a, b) => {
    const score = (c) => c.detected.metrics.length * 10 + Math.min(c.detected.rows.length, 20);
    return score(b) - score(a);
  });

  const blocks = [];
  const maxTables = compact ? 1 : 3;
  const maxMetrics = compact ? 1 : 3;

  for (const { table, detected } of candidates.slice(0, maxTables)) {
    const metrics = detected.metrics.slice(0, maxMetrics);
    const labels = detected.rows.map((row) => String(row?.[detected.categoryIndex] ?? ""));
    const chronological = isChronological(labels);
    const isSmallDistribution = !chronological && detected.rows.length >= 2 && detected.rows.length <= 8;
    const charts = metrics.map((metric) => {
      let rows = normalizeRows(detected, metric);
      const title = metrics.length > 1 ? `${table.title} · ${humanize(metric.column)}` : table.title;
      if (chronological && rows.length > 21) {
        const agg = tryAggregateMonthly(rows);
        if (agg && agg.length >= 2) rows = agg;
      }
      if (chronological) return renderLine(title, rows, metric);
      if (isSmallDistribution) return renderTableDonut(title, detected.categoryLabel, rows, metric) || renderBars(title, detected.categoryLabel, rows, metric);
      return renderBars(title, detected.categoryLabel, rows, metric);
    }).filter(Boolean).join("");

    if (!charts) continue;

    blocks.push(`<section class="statistical-visuals">
      ${renderKpiSummary(table, detected)}
      <div class="stat-chart-grid">${charts}</div>
    </section>`);
  }

  return blocks.join("");
}

/* V16.2 - Data-first statistical presentation helpers. */
function cleanAnswerMarkdown(value) {
  return String(value ?? "")
    .replace(/\*\*/g, "")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/^\s*[\u2726*+-]\s*/gm, "")
    .replace(/\r/g, "")
    .trim();
}

function parseAnswerPairs(value) {
  const text = String(value ?? "").replace(/\n+/g, " ").trim();
  if (!text) return [];
  return text
    .split(/\s*[\u00b7;|]\s*/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const match = part.match(/^(.*?)(?:\s+|:)\s*(-?\d+(?:[.,]\d+)?)\s*(%|d[i\u00ed]as?)?$/i);
      if (!match) return null;
      const numeric = asNumber(match[2]);
      if (numeric === null) return null;
      return {
        label: humanize(match[1].trim()),
        value: numeric,
        unit: match[3] || "",
      };
    })
    .filter(Boolean);
}

function parseAnswerStatSections(answer) {
  const text = cleanAnswerMarkdown(answer);
  if (!text) return { context: "", sections: [] };

  const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const sections = [];
  const contextLines = [];
  let current = null;

  for (const line of lines) {
    if (/^(CLAVES|Lo m[a\u00e1]s relevante)$/i.test(line)) continue;

    const match = line.match(/^([^:]{2,42}):\s*(.+)$/);
    if (match) {
      const pairs = parseAnswerPairs(match[2]);
      if (pairs.length) {
        current = { title: match[1].trim(), pairs };
        sections.push(current);
        continue;
      }
    }

    if (current) {
      const extra = parseAnswerPairs(line);
      if (extra.length) {
        current.pairs.push(...extra);
        continue;
      }
      current = null;
    }

    if (line.length > 24 && line.length < 260) contextLines.push(line);
  }

  return { context: contextLines[0] || "", sections };
}

function answerSectionKind(section) {
  const text = String(section?.title || "").toLowerCase();
  const count = section?.pairs?.length || 0;
  if (/hoy|situaci[o\u00f3]n|estado/.test(text) && count <= 8) return "donut";
  if (/vacacion|saldo|kpi|indicador/.test(text) && count <= 5) return "kpis";
  return "bars";
}

function renderAnswerBars(section, compact) {
  const entries = [...section.pairs].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  const visible = entries.slice(0, compact ? 7 : 12);
  const max = Math.max(...visible.map((entry) => Math.abs(entry.value)), 1);

  return `<section class="stat-chart stat-bars stat-answer-bars">
    <header class="stat-chart-head"><div><span>Distribuci\u00f3n</span><strong>${esc(section.title)}</strong></div><small>${visible.length}${entries.length > visible.length ? ` de ${entries.length}` : ""}</small></header>
    <div class="stat-bars-list">${visible.map((entry) => {
      const width = Math.max(4, Math.min(100, (Math.abs(entry.value) / max) * 100));
      return `<div class="stat-bar-row"><span class="stat-bar-label" title="${esc(entry.label)}">${esc(entry.label)}</span><div class="stat-bar-track"><i style="--bar:${width}%"></i></div><b>${esc(formatNumber(entry.value))}${entry.unit === "%" ? "%" : ""}</b></div>`;
    }).join("")}</div>
  </section>`;
}

function renderAnswerDonut(section) {
  const palette = ["#d1a85c", "#83d0ca", "#e87959", "#90a7d4", "#b99bd6", "#7c9295", "#d6b88e", "#7dc6ad"];
  const positive = section.pairs.filter((entry) => entry.value > 0);
  const total = positive.reduce((sum, entry) => sum + entry.value, 0);
  if (!total) return renderAnswerBars(section, false);

  let offset = 0;
  const slices = positive.map((entry, index) => {
    const start = (offset / total) * 100;
    offset += entry.value;
    const end = (offset / total) * 100;
    return `${palette[index % palette.length]} ${start.toFixed(2)}% ${end.toFixed(2)}%`;
  }).join(",");

  return `<section class="stat-chart stat-donut-card">
    <header class="stat-chart-head"><div><span>Situaci\u00f3n actual</span><strong>${esc(section.title)}</strong></div><small>${formatNumber(total)} personas</small></header>
    <div class="stat-donut-layout">
      <div class="stat-donut" style="background:conic-gradient(${slices})"><span><b>${formatNumber(total)}</b><small>Total</small></span></div>
      <div class="stat-donut-legend">${section.pairs.map((entry, index) => `<div><i style="--legend:${palette[index % palette.length]}"></i><span>${esc(entry.label)}</span><b>${esc(formatNumber(entry.value))}</b></div>`).join("")}</div>
    </div>
  </section>`;
}

function renderAnswerKpis(section) {
  return `<section class="stat-chart stat-answer-kpis">
    <header class="stat-chart-head"><div><span>Indicadores</span><strong>${esc(section.title)}</strong></div></header>
    <div class="stat-kpi-cluster">${section.pairs.map((entry) => `<article><span>${esc(entry.label)}</span><strong>${esc(formatNumber(entry.value))}${entry.unit === "%" ? "%" : ""}</strong></article>`).join("")}</div>
  </section>`;
}

function buildAnswerSummary(parsed) {
  const parts = [];
  const bars = parsed.sections.find((section) => answerSectionKind(section) === "bars");
  if (bars?.pairs?.length) {
    const top = [...bars.pairs].sort((a, b) => b.value - a.value).slice(0, 2);
    if (top.length >= 2) parts.push(`Predominan ${top[0].label} (${formatNumber(top[0].value)}) y ${top[1].label} (${formatNumber(top[1].value)}).`);
    else if (top.length === 1) parts.push(`El mayor volumen corresponde a ${top[0].label} (${formatNumber(top[0].value)}).`);
  }

  const today = parsed.sections.find((section) => /hoy|situaci[o\u00f3]n|estado/i.test(section.title));
  if (today) {
    const working = today.pairs.find((entry) => /trabaj/.test(entry.label.toLowerCase()));
    const noShift = today.pairs.find((entry) => /sin turno/.test(entry.label.toLowerCase()));
    if (working && noShift) parts.push(`Hoy trabajan ${formatNumber(working.value)} personas y ${formatNumber(noShift.value)} est\u00e1n sin turno publicado.`);
    else if (working) parts.push(`Hoy trabajan ${formatNumber(working.value)} personas.`);
  }

  const vacation = parsed.sections.find((section) => /vacacion/i.test(section.title));
  if (vacation) {
    const average = vacation.pairs.find((entry) => /saldo medio/.test(entry.label.toLowerCase()));
    const negative = vacation.pairs.find((entry) => /negativ/.test(entry.label.toLowerCase()));
    if (average) parts.push(`El saldo medio de vacaciones es ${formatNumber(average.value)} d\u00edas.`);
    if (negative?.value > 0) parts.push(`${formatNumber(negative.value)} personas tienen saldo negativo.`);
  }

  return parts.slice(0, 3).join(" ") || "Te muestro el an\u00e1lisis en formato visual.";
}

function renderAnswerStatisticalVisuals(answer, compact) {
  const parsed = parseAnswerStatSections(answer);
  if (parsed.sections.length < 2) return { html: "", summary: "", context: "", dataFirst: false };

  const charts = parsed.sections.map((section) => {
    const kind = answerSectionKind(section);
    if (kind === "donut") return renderAnswerDonut(section);
    if (kind === "kpis") return renderAnswerKpis(section);
    return renderAnswerBars(section, compact);
  }).join("");

  const context = parsed.context
    ? `<div class="stat-context"><span>Contexto</span><p>${esc(parsed.context)}</p></div>`
    : "";

  return {
    html: `<section class="statistical-visuals statistical-answer-visuals">${context}<div class="stat-chart-grid">${charts}</div></section>`,
    summary: buildAnswerSummary(parsed),
    context: parsed.context,
    dataFirst: true,
  };
}



/* V16.3 - KPI/indicator presentation normalizer.
 * Converts backend metric cards such as {title:"Turno", Indicador:"Plantilla activa", Valor:64}
 * into one coherent data-first overview. It intentionally leaves the original presentation available
 * in the collapsed detail block handled by the caller, so no source data is lost. */
function firstDefined(object, keys) {
  for (const key of keys) {
    if (object && object[key] !== undefined && object[key] !== null && object[key] !== "") return object[key];
  }
  return undefined;
}

function canonicalMetricLabel(value) {
  const original = String(value ?? "").replaceAll("_", " ").replace(/\s+/g, " ").trim();
  const normalized = original.toLowerCase();
  const rules = [
    [/personas? con n[oó]minas? sin leer|n[oó]minas? sin leer/, "Nóminas sin leer"],
    [/plantilla activa/, "Plantilla activa"],
    [/trabajando hoy|trabajan hoy/, "Trabajando hoy"],
    [/de baja hoy|bajas? hoy/, "De baja hoy"],
    [/de vacaciones hoy|vacaciones hoy/, "De vacaciones hoy"],
    [/ausencias?.*(?:7|siete).*d[ií]as|ausencias pr[oó]ximos? 7 d[ií]as/, "Ausencias próximos 7 días"],
    [/saldo medio.*vacaciones|vacaciones.*saldo medio/, "Saldo medio de vacaciones"],
    [/saldos? negativos?/, "Saldos negativos"],
    [/ett hoy|personas? ett hoy/, "ETT hoy"],
  ];
  for (const [rx, label] of rules) if (rx.test(normalized)) return label;
  return humanize(original);
}

function metricMeta(label) {
  const text = String(label || "").toLowerCase();
  if (/plantilla activa/.test(text)) return { group: "plantilla", eyebrow: "Plantilla", tone: "primary", unit: "personas" };
  if (/trabajando hoy/.test(text)) return { group: "today", eyebrow: "Hoy", tone: "success", unit: "personas" };
  if (/baja hoy/.test(text)) return { group: "today", eyebrow: "Hoy", tone: "danger", unit: "personas" };
  if (/vacaciones hoy/.test(text)) return { group: "today", eyebrow: "Hoy", tone: "warm", unit: "personas" };
  if (/ausencias.*7 d[ií]as/.test(text)) return { group: "forecast", eyebrow: "Próximos 7 días", tone: "warning", unit: "" };
  if (/saldo medio.*vacaciones/.test(text)) return { group: "vacation", eyebrow: "Vacaciones", tone: "gold", unit: "días" };
  if (/saldos? negativos?/.test(text)) return { group: "vacation", eyebrow: "Vacaciones", tone: "neutral", unit: "" };
  if (/n[oó]minas? sin leer/.test(text)) return { group: "documents", eyebrow: "Nóminas", tone: "info", unit: "nóminas" };
  if (/ett hoy/.test(text)) return { group: "ett", eyebrow: "ETT", tone: "neutral", unit: "" };
  return { group: "other", eyebrow: "Indicador", tone: "neutral", unit: "" };
}

function extractMetricCards(presentations) {
  if (!Array.isArray(presentations)) return [];
  const metrics = [];
  for (const item of presentations) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;

    const indicator = firstDefined(item, ["Indicador", "indicador", "indicator", "label", "nombre", "name", "metric", "metrica", "métrica"]);
    const rawValue = firstDefined(item, ["Valor", "valor", "value", "Value", "dato", "data"]);
    const number = asNumber(rawValue);
    if (indicator !== undefined && number !== null) {
      const label = canonicalMetricLabel(indicator);
      metrics.push({
        label,
        value: number,
        rawValue,
        title: String(item.title || item.titulo || ""),
        ...metricMeta(label),
      });
      continue;
    }

    // Also accept a compact KPI dictionary, but only when every value is scalar numeric.
    const kpis = item.kpis && typeof item.kpis === "object" && !Array.isArray(item.kpis) ? item.kpis : null;
    if (kpis) {
      for (const [key, value] of Object.entries(kpis)) {
        const numeric = asNumber(value);
        if (numeric === null) continue;
        const label = canonicalMetricLabel(key);
        metrics.push({ label, value: numeric, rawValue: value, title: String(item.title || ""), ...metricMeta(label) });
      }
    }
  }

  // Deduplicate by semantic label, keeping the last backend value.
  const unique = new Map();
  for (const metric of metrics) unique.set(metric.label.toLowerCase(), metric);
  return [...unique.values()];
}

function renderMetricTile(metric, { hero = false } = {}) {
  const unit = metric.unit ? `<small>${esc(metric.unit)}</small>` : "";
  return `<article class="stat-metric-tile tone-${esc(metric.tone)}${hero ? " is-hero" : ""}">
    <span class="stat-metric-eyebrow">${esc(metric.eyebrow)}</span>
    <strong>${esc(formatNumber(metric.value))}${unit}</strong>
    <p>${esc(metric.label)}</p>
  </article>`;
}

function renderTodayComparison(metrics, plantilla) {
  if (!metrics.length) return "";
  const max = Math.max(...metrics.map((metric) => Math.abs(metric.value)), 1);
  const working = metrics.find((metric) => /trabajando hoy/i.test(metric.label));
  const ratio = working && plantilla?.value > 0 ? Math.max(0, Math.min(100, (working.value / plantilla.value) * 100)) : null;
  return `<section class="stat-chart stat-today-overview">
    <header class="stat-chart-head"><div><span>Situación</span><strong>Hoy</strong></div>${ratio !== null ? `<small>${esc(formatNumber(ratio))} % de la plantilla trabajando</small>` : ""}</header>
    <div class="stat-today-bars">${metrics.map((metric) => {
      const width = Math.max(metric.value === 0 ? 0 : 5, Math.min(100, (Math.abs(metric.value) / max) * 100));
      return `<div class="stat-today-row tone-${esc(metric.tone)}"><div><span>${esc(metric.label)}</span><b>${esc(formatNumber(metric.value))}</b></div><div class="stat-today-track"><i style="--bar:${width}%"></i></div></div>`;
    }).join("")}</div>
  </section>`;
}

function buildMetricSummary(metrics) {
  const get = (rx) => metrics.find((metric) => rx.test(metric.label));
  const plantilla = get(/plantilla activa/i);
  const working = get(/trabajando hoy/i);
  const sick = get(/baja hoy/i);
  const vacation = get(/vacaciones hoy/i);
  const payroll = get(/n[oó]minas sin leer/i);
  const pieces = [];
  if (plantilla && working) pieces.push(`La plantilla activa es de ${formatNumber(plantilla.value)} personas y hoy trabajan ${formatNumber(working.value)}.`);
  else if (plantilla) pieces.push(`La plantilla activa es de ${formatNumber(plantilla.value)} personas.`);
  if (sick || vacation) {
    const states = [];
    if (sick) states.push(`${formatNumber(sick.value)} de baja`);
    if (vacation) states.push(`${formatNumber(vacation.value)} de vacaciones`);
    pieces.push(`Hoy hay ${states.join(" y ")}.`);
  }
  if (payroll) pieces.push(`Hay ${formatNumber(payroll.value)} nóminas sin leer.`);
  return pieces.slice(0, 3).join(" ") || "Te muestro los indicadores principales en formato visual.";
}

function renderMetricOverview(presentations, compact = false) {
  const metrics = extractMetricCards(presentations);
  if (metrics.length < 3) return { html: "", summary: "", dataFirst: false };

  const plantilla = metrics.find((metric) => metric.group === "plantilla");
  const today = metrics.filter((metric) => metric.group === "today");
  const priorityLabels = [/plantilla activa/i, /trabajando hoy/i, /baja hoy/i, /vacaciones hoy/i];
  const hero = [];
  for (const rx of priorityLabels) {
    const found = metrics.find((metric) => rx.test(metric.label));
    if (found && !hero.includes(found)) hero.push(found);
  }
  if (!hero.length) hero.push(...metrics.slice(0, compact ? 3 : 4));

  const heroSet = new Set(hero);
  const secondary = metrics.filter((metric) => !heroSet.has(metric));
  const maxSecondary = compact ? 4 : 8;

  return {
    dataFirst: true,
    summary: buildMetricSummary(metrics),
    sourceMode: "details",
    html: `<section class="statistical-visuals stat-metric-overview">
      <div class="stat-metric-hero">${hero.map((metric) => renderMetricTile(metric, { hero: true })).join("")}</div>
      ${today.length >= 2 ? renderTodayComparison(today, plantilla) : ""}
      ${secondary.length ? `<div class="stat-metric-secondary">${secondary.slice(0, maxSecondary).map((metric) => renderMetricTile(metric)).join("")}</div>` : ""}
    </section>`,
  };
}

export function buildStatisticalPresentation(presentations = [], { query = "", answer = "", compact = false } = {}) {
  if (presentations.some(p => p?.type === 'calendar')) return {html:'',dataFirst:false,summary:''};
  const metricOverview = renderMetricOverview(presentations, compact);
  if (metricOverview.dataFirst) return metricOverview;

  const answerVisuals = renderAnswerStatisticalVisuals(answer, compact);
  if (answerVisuals.dataFirst) {
    return {
      ...answerVisuals,
      sourceMode: "details",
    };
  }

  const html = renderStatisticalVisuals(presentations, { query, compact });
  if (html) {
    return {
      html,
      dataFirst: true,
      summary: "Te muestro el análisis en formato visual. El detalle completo está disponible abajo.",
      context: "",
      sourceMode: "details",
    };
  }

  return { html: "", dataFirst: false, summary: "", context: "", sourceMode: "full" };
}
