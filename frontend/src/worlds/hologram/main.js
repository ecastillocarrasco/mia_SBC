import { MiaBootLoader } from "../../core/boot-loader-v43.js";
import { getWelcomeText } from "../../core/identity-v45.js";
import { MiaWelcomeVoiceV45 } from "../../core/welcome-voice-v45.js";
import * as THREE from "three";
import { MiaClient } from "../../core/client.js";
import { MiaVoiceV4 } from "../../core/voice-v4.js";
import { avatarLabel } from "../../core/avatar.js";
import { MiaScene } from "../../core/scene.js";
import { MiaBehaviorV4 } from "../../core/behavior-v4.js";
import { MiaWaitingV4 } from "../../core/waiting-v4.js";
import { hasPresentationData, presentationType } from "../../core/premium-tables.js";
import { renderHologramBrief } from "../../core/hologram-brief.js";

function hologramMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(0x71e9f1) } },
    vertexShader: `
      #include <skinning_pars_vertex>
      varying vec3 vNormal; varying vec3 vView; varying float vY;
      void main() {
        #include <skinbase_vertex>
        #include <begin_vertex>
        #include <beginnormal_vertex>
        #include <skinnormal_vertex>
        #include <skinning_vertex>
        vec4 world = modelMatrix * vec4(transformed, 1.0);
        vY = world.y;
        vNormal = normalize(normalMatrix * objectNormal);
        vec4 mv = viewMatrix * world;
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform float uTime; uniform vec3 uColor;
      varying vec3 vNormal; varying vec3 vView; varying float vY;
      void main() {
        float edge = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
        float scan = 0.75 + 0.25 * step(0.5, fract(vY * 18.0 - uTime * 1.35));
        float alpha = clamp(0.18 + edge * 0.83, 0.0, 0.92) * scan;
        gl_FragColor = vec4(uColor * (0.72 + edge * 0.95), alpha);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

const caption = document.getElementById("caption");
const resultEl = document.getElementById("result");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const micButton = document.getElementById("mic");
const welcomeReplay = document.getElementById("miaWelcomeReplay");
const boot = new MiaBootLoader({ mode: "hologram" });
const scene = new MiaScene(document.getElementById("canvas-root"), {
  background: 0x01090d, shadows: false, fov: 34,
});
scene.camera.position.set(0, 1.5, 5.2);
scene.target.set(0, 1.45, 0);
const client = new MiaClient();
const materials = [];
let behavior = null;
let busy = false;
let greetingTimer = null;
let welcomeMessage = "";
const welcomeVoice = new MiaWelcomeVoiceV45({
  apiBase: client.apiBase,
  onBlocked: () => {
    if (!busy && welcomeReplay) welcomeReplay.hidden = false;
  },
});
welcomeReplay?.addEventListener("click", () => {
  welcomeReplay.hidden = true;
  if (!busy && welcomeMessage) void welcomeVoice.start(welcomeMessage);
});
let captionEpoch = 0;
let voice = null;
function sayCaption(message, kind = "answer") {
  const epoch = ++captionEpoch;
  caption.textContent = String(message ?? "");
  caption.dataset.kind = kind;
  caption.classList.remove("is-revealed");
  requestAnimationFrame(() => {
    if (epoch === captionEpoch) caption.classList.add("is-revealed");
  });
}

const waiting = new MiaWaitingV4({
  onUpdate: (message) => sayCaption(message, "waiting"),
  onClear: () => {},
});

scene.onFrame = (time) => {
  for (const m of materials) m.uniforms.uTime.value = time;
  if (scene.model) scene.model.rotation.y = Math.sin(time * 0.19) * 0.07;
};

client.addEventListener("avatar", (event) => {
  if (busy) return;
  behavior?.enterBackendState(event.detail?.state);
  if (!busy) sayCaption(avatarLabel(event.detail?.state));
});
client.addEventListener("progress", (event) => {
  if (busy) waiting.progress(event.detail?.message ?? event.detail?.state ??
      event.detail?.tool ?? "Estamos tramitando tu solicitud.");
  behavior?.progress();
});

async function submit(text) {
  const question = String(text || "").trim();
  if (busy || !question) return;
  busy = true;
  welcomeVoice.cancel();
  if (welcomeReplay) welcomeReplay.hidden = true;
  sendButton.disabled = true;
  // En modo continuo: suspender mientras Mía responde, conservando el modo.
  voice?.pause();
  resultEl.replaceChildren();
  window.clearTimeout(greetingTimer);
  greetingTimer = null;
  waiting.start();
  behavior?.enter("thinking", { query: question });
  try {
    const response = await client.send(question);
    waiting.stop();
    const answer = String(response?.answer || response?.speech || "Ya tengo el resultado.");
    const presentations = Array.isArray(response?.presentations) ? response.presentations : [];
    const withData = hasPresentationData(presentations);
    const type = withData ? presentationType(presentations) : "conversation";
    sayCaption(answer, withData ? "presenting" : "answer");
    // Hologram is concise by contract. Never dump detailed employee data or full tables here.
    if (withData) {
      resultEl.innerHTML = renderHologramBrief(presentations, { type });
      behavior?.enter("presenting", { presentationType: type, query: question });
    } else {
      resultEl.replaceChildren();
    }
    await client.speak(response?.speech || answer, {
      onStart: () => {
        if (!withData) behavior?.enter("speaking", { answer, presentationType: type });
      },
    });
    behavior?.enter("idle");
  } catch (error) {
    waiting.stop();
    console.error("[mIA V4 HG] Consulta fallida", error);
    sayCaption("No he podido completar la consulta.", "error");
    resultEl.replaceChildren();
    behavior?.enter("error");
  } finally {
    waiting.stop();
    busy = false;
    sendButton.disabled = false;
    voice?.resume();  // se rearma solo si se eligió escucha continua
    if (voice?.mode !== "continuous") input.focus();
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value;
  input.value = "";
  void submit(question);
});

scene.load((value, detail) => {
  boot.progress(value, detail);
}).then(async (clips) => {
  const sourceClipCount = clips.filter((name) => name !== "mIA_IDLE_SAFE").length;
  if (sourceClipCount !== 84) console.warn(`[mIA V4 HG] Se esperaban 84 clips originales; cargados ${sourceClipCount}`);
  // Existing GLSL may not compile on every GPU: fallback to a skinned-compatible material.
  scene.renderer.debug.onShaderError = () => {
    console.warn("[mIA V4 HG] Shader no compatible: material de respaldo");
    materials.length = 0;
    scene.applyMaterial(() => new THREE.MeshBasicMaterial({
      color: 0x71e9f1, transparent: true, opacity: 0.52,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
  };
  scene.applyMaterial(() => {
    const mat = hologramMaterial();
    materials.push(mat);
    return mat;
  });
  behavior = new MiaBehaviorV4({ scene, mode: "hologram" });
  await boot.complete();
  behavior.enter("greeting");
  welcomeMessage = getWelcomeText();
  sayCaption(welcomeMessage, "welcome");
  void welcomeVoice.start(welcomeMessage);
  greetingTimer = window.setTimeout(() => {
    greetingTimer = null;
    if (!busy && behavior?.state === "greeting") behavior.enter("idle");
  }, Math.max(2000, scene.clipDuration("mIA_SEQ_BIENVENIDA") * 1000 + 250));
}).catch((error) => {
  boot.fail(error);
  console.error("[mIA V4 HG] Fallo al cargar el modelo", error);
  sayCaption("No se ha podido cargar la proyección de Mía.", "error");
});

// V4.4: micrófono apagado -> una consulta -> continuo -> apagado.
const hgMicAnnounce = document.getElementById("hgMicModeAnnounce");
function displayHgMicMode(mode, { paused = false } = {}) {
  const names = {
    off: ["Micrófono desactivado", "Una pregunta"],
    once: [paused ? "Una consulta finalizada; micrófono en pausa" : "Escucha para una pregunta", "Escucha continua"],
    continuous: [paused ? "Modo continuo pausado" : "Modo continuo activo", "Apagar micrófono"],
  };
  const [state, next] = names[mode] || names.off;
  micButton.dataset.micMode = mode;
  micButton.classList.toggle("is-once", mode === "once");
  micButton.classList.toggle("is-continuous", mode === "continuous");
  micButton.classList.toggle("is-suspended", mode !== "off" && paused);
  micButton.setAttribute("aria-pressed", String(mode !== "off"));
  micButton.setAttribute("aria-label", `${state}. Siguiente pulsación: ${next}`);
  micButton.title = `${state} · ${next}`;
  if (hgMicAnnounce) hgMicAnnounce.textContent = state;
}
voice = new MiaVoiceV4({
  onInterim: (text) => { input.value = text; },
  onFinal: (text) => {
    input.value = "";
    if (text.trim()) void submit(text);
  },
  onModeChange: (mode, info) => { displayHgMicMode(mode, info); },
  onError: () => {
    if (!busy) sayCaption("No he podido activar el micrófono. Puedes escribir tu consulta.", "error");
  },
});
displayHgMicMode("off");
if (!voice.available) {
  micButton.disabled = true;
  micButton.title = "Dictado no disponible en este navegador";
}
micButton.addEventListener("click", () => {
  if (busy) {
    if (voice?.mode === "continuous") voice.stop();
    return;
  }
  voice?.cycle();
});
window.addEventListener("pagehide", () => {
  boot.dispose();
  window.clearTimeout(greetingTimer);
  waiting.stop();
  client.stopSpeaking();
  welcomeVoice.dispose();
  voice?.destroy();
  behavior?.destroy();
});
