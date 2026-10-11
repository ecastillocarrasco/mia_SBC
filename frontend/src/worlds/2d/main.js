import { MiaClient } from "../../core/client.js";
import { bindMicButton } from "../../core/dictation.js";
import { avatarLabel, avatarSrc } from "../../core/avatar.js";
import { renderPresentation } from "../../core/present.js";
import { renderMarkdown, enhanceTables } from "./richtext.js";

const $ = (id) => document.getElementById(id);
const conversation = $("conversation");
const composer = $("composer");
const input = $("input");
const sendButton = $("send");
const avatarImg = $("avatarImg");
const avatarLabelEl = $("avatarLabel");
const statusLabel = $("statusLabel");
const voiceToggle = $("voiceToggle");
const toastLayer = $("toasts");
const attachBtn = $("attachBtn");
const fileInput = $("fileInput");
const attachmentPreviews = $("attachmentPreviews");

const client = new MiaClient();
let voiceEnabled = true;
let busy = false;

const SUGGESTIONS = [
  { title: "Listado de personal", text: "Dame el listado de empleados activos por departamento" },
  { title: "Turnos de hoy", text: "¿Quién trabaja hoy y en qué turno?" },
  { title: "Vacaciones", text: "¿Quién está de vacaciones esta semana?" },
];

const toast = (text) => {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = text;
  toastLayer.appendChild(t);
  setTimeout(() => t.remove(), 2600);
};

const setStatus = (text, tone = "ok") => {
  statusLabel.textContent = text;
  statusLabel.parentElement.dataset.tone = tone;
};

function setAvatar(state) {
  avatarImg.src = avatarSrc(state);
  avatarLabelEl.textContent = avatarLabel(state);
  document.body.dataset.state = state || "reposo";
}

const time = () => new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
const scrollDown = () => conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });

function addBubble(role, html, { raw = false } = {}) {
  const row = document.createElement("div");
  row.className = `row ${role.split(" ")[0]}`;
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.innerHTML = html;
  if (!raw) {
    const stamp = document.createElement("time");
    stamp.textContent = time();
    bubble.appendChild(stamp);
  }
  row.appendChild(bubble);
  conversation.appendChild(row);
  enhanceTables(bubble, toast);
  scrollDown();
  return row;
}

const escapeHtml = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- KPIs y gráficos (adjuntos a las presentaciones de tipo "table") ----------
const CHART_PALETTE = ["#d6b067", "#7cc6c3", "#8a6bb0", "#d9776b", "#5b8def", "#7fa37a", "#c9b8a3", "#e0806a"];
const fmtNum = (v) => Number(v).toLocaleString("es-ES", { maximumFractionDigits: 1 });

function renderKpis(kpis) {
  if (!Array.isArray(kpis) || !kpis.length) return "";
  const items = kpis
    .map(
      (k) =>
        `<div class="mia-kpi${k?.highlight ? " highlight" : ""}"><span class="mia-kpi-label">${escapeHtml(k?.label)}</span><span class="mia-kpi-value">${escapeHtml(k?.value ?? "—")}</span></div>`,
    )
    .join("");
  return `<div class="mia-kpis">${items}</div>`;
}

function renderBarChart(spec) {
  const values = spec.series?.[0]?.values || [];
  const max = Math.max(...values, 1);
  const rows = spec.labels
    .map((label, i) => {
      const pct = Math.max(2, (Math.abs(values[i] || 0) / max) * 100);
      return `<div class="mia-bar-row"><span class="mia-bar-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span><span class="mia-bar-track"><span class="mia-bar-fill" style="width:${pct}%"></span></span><span class="mia-bar-value">${fmtNum(values[i])}</span></div>`;
    })
    .join("");
  return `<div class="mia-bars">${rows}</div>`;
}

function renderDonutChart(spec) {
  const values = spec.series?.[0]?.values || [];
  const total = values.reduce((a, b) => a + (b || 0), 0) || 1;
  const r = 54;
  const c = 2 * Math.PI * r;
  let offset = 0;
  const arcs = values
    .map((v, i) => {
      const len = (v / total) * c;
      const arc = `<circle class="mia-donut-arc" cx="75" cy="75" r="${r}" transform="rotate(-90 75 75)" stroke="${CHART_PALETTE[i % CHART_PALETTE.length]}" stroke-dasharray="${Math.max(0, len - 1.5)} ${c - len + 1.5}" stroke-dashoffset="${-offset}"></circle>`;
      offset += len;
      return arc;
    })
    .join("");
  const legend = spec.labels
    .map(
      (label, i) =>
        `<div><i style="background:${CHART_PALETTE[i % CHART_PALETTE.length]}"></i>${escapeHtml(label)}<b>${fmtNum(values[i])} · ${Math.round(((values[i] || 0) / total) * 100)}%</b></div>`,
    )
    .join("");
  return `<div class="mia-donut"><svg viewBox="0 0 150 150" role="img" aria-label="${escapeHtml(spec.title || "Gráfico")}">
    <circle cx="75" cy="75" r="${r}" fill="none" stroke="var(--line2)" stroke-width="22"></circle>
    ${arcs}
    <text class="mia-donut-total" x="75" y="78">${fmtNum(total)}</text>
    <text class="mia-donut-caption" x="75" y="94">TOTAL</text>
  </svg><div class="mia-legend">${legend}</div></div>`;
}

function renderLineChart(spec) {
  const values = spec.series?.[0]?.values || [];
  const w = 560;
  const h = 170;
  const pad = 28;
  const max = Math.max(...values);
  const min = Math.min(0, Math.min(...values));
  const span = max - min || 1;
  const step = values.length > 1 ? (w - 2 * pad) / (values.length - 1) : 0;
  const pts = values.map((v, i) => [pad + i * step, h - 30 - ((v - min) / span) * (h - 60)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const area = `${d} L${pts[pts.length - 1][0]} ${h - 30} L${pts[0][0]} ${h - 30} Z`;
  const dots = pts
    .map(
      (p, i) =>
        `<circle class="mia-line-dot" cx="${p[0]}" cy="${p[1]}" r="4"></circle><text class="mia-line-val" x="${p[0]}" y="${p[1] - 10}">${fmtNum(values[i])}</text><text class="mia-line-axis" x="${p[0]}" y="${h - 10}">${escapeHtml(spec.labels[i])}</text>`,
    )
    .join("");
  return `<div class="mia-line"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${escapeHtml(spec.title || "Gráfico")}">
    <path class="mia-line-area" d="${area}"></path>
    <path class="mia-line-path" d="${d}"></path>
    ${dots}
  </svg></div>`;
}

function renderChart(spec) {
  if (!spec || !Array.isArray(spec.labels) || !spec.series?.[0]) return "";
  const body =
    spec.type === "donut" ? renderDonutChart(spec) : spec.type === "line" ? renderLineChart(spec) : renderBarChart(spec);
  return `<section class="mia-chart" data-chart="${escapeHtml(spec.type)}"><div class="mia-chart-head"><strong>${escapeHtml(spec.title || "Gráfico")}</strong><span>${escapeHtml(spec.series[0].name || "")}</span></div>${body}</section>`;
}

function renderCharts(charts) {
  if (!Array.isArray(charts) || !charts.length) return "";
  return charts.map(renderChart).join("");
}

/** Para presentaciones de tipo "table": KPIs antes, gráficos y tabla de estadísticas después. */
function renderExtras(presentation) {
  if (!presentation || typeof presentation !== "object") return "";
  let html = renderKpis(presentation.kpis);
  html += renderCharts(presentation.charts);
  if (presentation.stats) html += renderPresentation(presentation.stats);
  return html;
}
// ---------- fin KPIs y gráficos ----------

// ---------- adjuntos ----------
const _attachments = new Map(); // chipId → { id, status, name }

function _attIcon(name) {
  if (/\.pdf$/i.test(name)) return "📄";
  if (/\.(xlsx?|csv)$/i.test(name)) return "📊";
  if (/\.(docx?)$/i.test(name)) return "📝";
  if (/\.(png|jpe?g|webp)$/i.test(name)) return "🖼️";
  return "📎";
}

function _renderPreviews() {
  attachmentPreviews.innerHTML = "";
  if (!_attachments.size) { attachmentPreviews.style.display = "none"; return; }
  attachmentPreviews.style.display = "flex";
  for (const [cid, att] of _attachments) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip" + (att.status === "uploading" ? " uploading" : att.status === "error" ? " error" : "");
    const statusText = att.status === "uploading" ? "Subiendo…" : att.status === "error" ? "Error" : "Listo";
    const statusCls = att.status === "error" ? " err" : "";
    chip.innerHTML = `<span class="att-icon">${_attIcon(att.name)}</span><span class="att-name">${escapeHtml(att.name)}</span><span class="att-status${statusCls}">${statusText}</span><button type="button" class="att-remove" data-cid="${cid}" title="Quitar">×</button>`;
    attachmentPreviews.appendChild(chip);
  }
}

async function _uploadFile(file) {
  const cid = Math.random().toString(36).slice(2);
  _attachments.set(cid, { id: null, status: "uploading", name: file.name });
  _renderPreviews();
  try {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/adjuntos/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _attachments.set(cid, { id: data.attachment_id, status: "ok", name: file.name });
  } catch {
    _attachments.set(cid, { id: null, status: "error", name: file.name });
  }
  _renderPreviews();
}

attachBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  for (const f of fileInput.files) _uploadFile(f);
  fileInput.value = "";
});
attachmentPreviews.addEventListener("click", (e) => {
  const btn = e.target.closest(".att-remove");
  if (btn) { _attachments.delete(btn.dataset.cid); _renderPreviews(); }
});
composer.addEventListener("dragover", (e) => { e.preventDefault(); composer.classList.add("drag-over"); });
composer.addEventListener("dragleave", () => composer.classList.remove("drag-over"));
composer.addEventListener("drop", (e) => {
  e.preventDefault();
  composer.classList.remove("drag-over");
  for (const f of e.dataTransfer.files) _uploadFile(f);
});
// ---------- fin adjuntos ----------

client.addEventListener("avatar", (e) => setAvatar(e.detail.state));
client.addEventListener("progress", (e) => setStatus(e.detail.message || "Consultando…", "busy"));
client.addEventListener("error", () => setStatus("Sin conexión", "error"));

voiceToggle.addEventListener("click", () => {
  voiceEnabled = !voiceEnabled;
  voiceToggle.setAttribute("aria-pressed", String(voiceEnabled));
  voiceToggle.textContent = voiceEnabled ? "🔊" : "🔇";
  if (!voiceEnabled) client.stopSpeaking();
});

async function submit(text) {
  text = String(text || "").trim();
  if (busy || !text) return;
  busy = true;
  sendButton.disabled = true;
  conversation.querySelector(".suggestions")?.remove();
  addBubble("user", escapeHtml(text));
  setStatus("Pensando…", "busy");
  setAvatar("pensando");
  const typing = addBubble("mia typing", "<i></i><i></i><i></i>", { raw: true });
  const attachmentIds = [..._attachments.values()].filter((a) => a.status === "ok" && a.id).map((a) => a.id);
  _attachments.clear();
  _renderPreviews();

  let result;
  try {
    result = await client.send(text, { attachmentIds });
  } catch (error) {
    console.error(error);
    typing.remove();
    addBubble("mia error", "No he podido completar la consulta. Comprueba la conexión e inténtalo de nuevo.");
    setStatus("Error de conexión", "error");
    setAvatar("confundida");
    busy = false;
    sendButton.disabled = false;
    input.focus();
    return;
  }

  typing.remove();
  const present = (result.presentations || [])
    .map((p) => renderPresentation(p) + renderExtras(p))
    .join("");
  addBubble("mia", `${renderMarkdown(result.answer)}${present ? `<div class="present">${present}</div>` : ""}`);
  setAvatar(result.avatar_state);
  setStatus("Lista");

  try {
    if (voiceEnabled && result.speech) {
      setAvatar("hablando");
      await client.speak(result.speech);
      setAvatar(result.avatar_state);
    }
  } catch (error) {
    console.warn("Voz no disponible", error);
    setAvatar(result.avatar_state);
  } finally {
    busy = false;
    sendButton.disabled = false;
    input.focus();
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  submit(text);
});

setStatus("Lista");
setAvatar("saludando");
addBubble("mia", "<p>Hola, soy mIA. Puedo consultar personal, turnos, vacaciones y documentos, y descargarte cualquier listado.</p>");

const chips = document.createElement("div");
chips.className = "suggestions";
SUGGESTIONS.forEach((s) => {
  const b = document.createElement("button");
  b.type = "button";
  b.innerHTML = `<strong>${s.title}</strong><span>${s.text}</span>`;
  b.addEventListener("click", () => submit(s.text));
  chips.appendChild(b);
});
conversation.appendChild(chips);

bindMicButton($("mic"), {
  onInterim: (text) => { input.value = text; },
  onFinal: (text) => { input.value = ""; submit(text); },
});
