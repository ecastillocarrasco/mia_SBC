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

  let result;
  try {
    result = await client.send(text);
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
  const present = (result.presentations || []).map(renderPresentation).join("");
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
