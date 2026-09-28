import { MiaClient } from "../../core/client.js";
import { renderPresentation } from "../../core/present.js";
import { MiaScene } from "../../core/scene.js";

const conversation = document.getElementById("conversation");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const statusLabel = document.getElementById("statusLabel");
const voiceToggle = document.getElementById("voiceToggle");

const scene = new MiaScene(document.getElementById("canvas-root"));
const client = new MiaClient();
let voiceEnabled = true;
let busy = false;

const escapeHtml = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

function addBubble(role, html) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.innerHTML = html;
  conversation.appendChild(bubble);
  conversation.scrollTop = conversation.scrollHeight;
}

client.addEventListener("avatar", (e) => scene.playState(e.detail.state));
client.addEventListener("progress", (e) => {
  statusLabel.textContent = e.detail.message || "Consultando…";
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
  scene.playState("pensando");
  statusLabel.textContent = "Pensando…";
  try {
    const result = await client.send(text);
    addBubble("mia", `<p>${escapeHtml(result.answer)}</p>${(result.presentations || []).map(renderPresentation).join("")}`);
    statusLabel.textContent = "Lista";
    if (voiceEnabled) {
      await client.speak(result.speech, { onStart: () => scene.playState("hablando") });
    }
    scene.playState(result.avatar_state);
  } catch (error) {
    console.error(error);
    addBubble("mia error", "No he podido completar la consulta. ¿Lo intentamos de nuevo?");
    statusLabel.textContent = "Error de conexión";
    scene.playState("confundida");
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

scene
  .load((p) => {
    statusLabel.textContent = `Cargando el modelo… ${Math.round(p * 100)} %`;
  })
  .then(() => {
    statusLabel.textContent = "Lista";
    scene.playState("saludando");
    addBubble("mia", "Hola, soy mIA. ¿En qué puedo ayudarte?");
  })
  .catch((error) => {
    console.error(error);
    statusLabel.textContent = "No se ha podido cargar el modelo 3D";
  });
