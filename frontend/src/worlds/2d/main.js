import { MiaClient } from "../../core/client.js";
import { avatarLabel, avatarSrc } from "../../core/avatar.js";
import { renderPresentation } from "../../core/present.js";

const conversation = document.getElementById("conversation");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const avatarImg = document.getElementById("avatarImg");
const avatarLabelEl = document.getElementById("avatarLabel");
const statusLabel = document.getElementById("statusLabel");
const voiceToggle = document.getElementById("voiceToggle");

const client = new MiaClient();
let voiceEnabled = true;
let busy = false;

function setAvatar(state) {
  avatarImg.src = avatarSrc(state);
  avatarLabelEl.textContent = avatarLabel(state);
}

function addBubble(role, html) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.innerHTML = html;
  conversation.appendChild(bubble);
  conversation.scrollTop = conversation.scrollHeight;
  return bubble;
}

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

client.addEventListener("avatar", (event) => setAvatar(event.detail.state));
client.addEventListener("progress", (event) => {
  statusLabel.textContent = event.detail.message || "Consultando…";
});
client.addEventListener("error", () => {
  statusLabel.textContent = "Sin conexión";
});

voiceToggle.addEventListener("click", () => {
  voiceEnabled = !voiceEnabled;
  voiceToggle.setAttribute("aria-pressed", String(voiceEnabled));
  voiceToggle.textContent = voiceEnabled ? "🔊" : "🔇";
  if (!voiceEnabled) client.stopSpeaking();
});

async function submit(text) {
  if (busy || !text.trim()) return;
  busy = true;
  sendButton.disabled = true;
  addBubble("user", escapeHtml(text));
  statusLabel.textContent = "Pensando…";
  setAvatar("pensando");
  try {
    const result = await client.send(text);
    const html = `<p>${escapeHtml(result.answer)}</p>${(result.presentations || []).map(renderPresentation).join("")}`;
    addBubble("mia", html);
    setAvatar(result.avatar_state);
    statusLabel.textContent = "Al día";
    if (voiceEnabled) {
      setAvatar("hablando");
      await client.speak(result.speech);
      setAvatar(result.avatar_state);
    }
  } catch (error) {
    console.error(error);
    addBubble("mia error", "No he podido completar la consulta. ¿Lo intentamos de nuevo?");
    statusLabel.textContent = "Error de conexión";
    setAvatar("confundida");
  } finally {
    busy = false;
    sendButton.disabled = false;
    input.focus();
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value;
  input.value = "";
  submit(text);
});

statusLabel.textContent = "Lista";
setAvatar("saludando");
addBubble("mia", "Hola, soy mIA. ¿En qué puedo ayudarte?");
