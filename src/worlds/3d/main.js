import { MiaBootLoader } from "../../core/boot-loader-v43.js";
import { MiaClient } from "../../core/client.js";
import { MiaVoiceV4 } from "../../core/voice-v4.js";
import { MiaWaitingV4 } from "../../core/waiting-v4.js";
import { MiaNarrativeV42 } from "../../core/narrative-v42.js";
import { renderPresentation } from "../../core/present.js";
import { buildStatisticalPresentation } from "../../core/statistical-visuals.js";
import { MiaScene } from "../../core/scene.js";
import { PresentationStage } from "../../core/presentation-stage.js";
import { MiaBehaviorV4 } from "../../core/behavior-v4.js";
import { enhancePremiumTables, hasPresentationData, presentationType } from "../../core/premium-tables.js";
import {
  isEmployee360Payload,
  buildEmployee360Presentation,
  renderEmployee360PresentationHtml,
} from "../../core/employee360-presentation.js";

const conversation = document.getElementById("conversation");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const statusLabel = document.getElementById("statusLabel");
const voiceToggle = document.getElementById("voiceToggle");
const panel = document.getElementById("panel");
const caption = document.getElementById("miaSpokenCaption");
const closePanel = document.getElementById("closeResults");
const dock = document.getElementById("miaInteractionDock");
const dockClose = document.getElementById("miaDockClose");
const textLauncher = document.getElementById("miaTextLauncher");
const micLauncher = document.getElementById("miaMicLauncher");
const micButton = document.getElementById("mic");
const waitHud = document.getElementById("miaWaitProgress");
const waitText = document.getElementById("miaWaitText");
const boot = new MiaBootLoader({ mode: "3d" });
const scene = new MiaScene(document.getElementById("canvas-root"));
// Fuller, eye-level framing; the floor is uniform white and has no horizon.
scene.camera.position.set(0, 1.47, 3.88);
scene.target.set(0, 1.18, 0);
const client = new MiaClient();
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
const stage = new PresentationStage({ root: document.body, reducedMotion, mode: "3d" });

let voiceEnabled = true;
let busy = false;
let behavior = null;
let dockHideTimer = null;
let greetingTimer = null;
let voice = null;
let voiceIsListening = false;
const narrative = new MiaNarrativeV42(caption);

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 0 : milliseconds));
}

function setStatus(message, state = "idle") {
  statusLabel.textContent = message;
  document.body.dataset.miaState = state;
}

function showCaption(text, { kind = "answer" } = {}) {
  narrative.show(text, { kind });
}

// No physically drifting avatar: skeletal idle clips supply the natural motion.
function scheduleIdleMotion() { /* the behavior director handles idle cycles */ }

function openDock({ focus = false } = {}) {
  window.clearTimeout(dockHideTimer);
  dock.hidden = false;
  document.body.classList.add("mia-dock-open");
  textLauncher.setAttribute("aria-expanded", "true");
  if (focus) input.focus({ preventScroll: true });
  scheduleDockAutoHide();
}

function closeDock({ force = false } = {}) {
  if (!force && (voiceIsListening || document.activeElement === input)) return;
  // Nunca dejar el micro abierto si se oculta la interfaz.
  if (voiceIsListening) voice?.stop();
  window.clearTimeout(dockHideTimer);
  dock.hidden = true;
  document.body.classList.remove("mia-dock-open");
  textLauncher.setAttribute("aria-expanded", "false");
  if (document.activeElement && dock.contains(document.activeElement)) document.activeElement.blur();
}

function scheduleDockAutoHide() {
  window.clearTimeout(dockHideTimer);
  dockHideTimer = window.setTimeout(() => {
    if (!busy && !voiceIsListening && !input.value.trim() && document.activeElement !== input) closeDock();
  }, 10000);
}

// An independent, small progress HUD is never treated as a data presentation.
const waiting = new MiaWaitingV4({
  onUpdate: (message) => {
    waitHud.hidden = false;
    waitText.textContent = "Consulta en curso";
    showCaption(message, { kind: "waiting" });
    setStatus(message, "thinking");
  },
  onClear: () => { waitHud.hidden = true; waitText.textContent = ""; },
});

// Any unmodified printable key opens the composer without losing its first character.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!dock.hidden) { event.preventDefault(); input.blur(); closeDock({ force: true }); }
    return;
  }
  if (event.ctrlKey || event.altKey || event.metaKey || event.repeat) return;
  if (event.target instanceof HTMLElement && event.target.closest("input,textarea,select,[contenteditable],button,a")) return;
  if (!dock.hidden) return;
  if (["Shift", "Control", "Alt", "Meta", "Tab", "CapsLock", "NumLock"].includes(event.key)
      || /^F\d{1,2}$/.test(event.key)) return;
  event.preventDefault();
  openDock({ focus: true });
  if (event.key.length === 1) input.value += event.key;
});

// Un clic en el escenario abre texto; NO enciende ni solicita micrófono.
// Los controles de resultados, enlaces y formularios se respetan.
document.addEventListener("pointerdown", (event) => {
  const element = event.target instanceof Element ? event.target : null;
  if (element?.closest("#miaInteractionDock,#miaTextLauncher,#miaMicLauncher,#panel,a,button,input,textarea,select,[contenteditable]")) return;
  if (dock.hidden) openDock();
}, { capture: true });

textLauncher.addEventListener("click", () => openDock({ focus: true }));
function micClick() {
  if (busy) return;
  openDock();
  voice?.toggle();  // ÚNICO punto de activación: clic explícito.
}
micLauncher.addEventListener("click", micClick);
micButton.addEventListener("click", micClick);
dockClose.addEventListener("click", () => { input.blur(); closeDock({ force: true }); });
input.addEventListener("input", scheduleDockAutoHide);
input.addEventListener("blur", scheduleDockAutoHide);

function renderPresentationItem(item, result, answer) {
  if (isEmployee360Payload(result, item?.data ?? {})) {
    try {
      const pres = buildEmployee360Presentation(item?.data ?? {});
      return renderEmployee360PresentationHtml(pres, item?.data ?? {}, answer);
    } catch (error) {
      console.warn("[mIA V4] Ficha Employee360: renderer alternativo", error);
    }
  }
  return renderPresentation(item);
}

function clearPresentation() {
  panel.dataset.presentation = "conversation";
  document.body.dataset.presentation = "conversation";
  stage.reset();
  conversation.replaceChildren();
  scene.setPresentationLayout(false);
  narrative.clear();
}

function animateCounters(root) {
  if (reducedMotion) return;
  for (const el of root.querySelectorAll(".stat-kpis strong, .stat-metric-tile strong, .e360-kpi strong")) {
    const raw = el.textContent.trim();
    const matched = raw.match(/^(\d+(?:[.,]\d+)?)(.*)$/);
    if (!matched) continue;
    const number = Number(matched[1].replace(",", "."));
    if (!Number.isFinite(number) || number <= 0 || number > 99999) continue;
    const start = performance.now();
    const decimals = matched[1].includes(".") ? matched[1].split(".")[1].length : 0;
    const tick = (now) => {
      const p = Math.min(1, (now - start) / 750);
      const ease = 1 - (1 - p) ** 3;
      el.textContent = (number * ease).toFixed(decimals) + matched[2];
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = raw;
    };
    requestAnimationFrame(tick);
  }
}

async function revealData(result, answer, query, presentations, kind) {
  const introductions = {
    person: "Ya tengo la ficha. Voy a presentarte la información disponible.",
    analytics: "He preparado los indicadores para que puedas analizarlos.",
    comparison: "Aquí tienes la comparativa que has solicitado.",
    document: "El resultado está preparado. Vamos a revisar el informe.",
    data: "Ya tengo los datos. Te muestro el detalle.",
  };
  behavior?.enter("presenting", { presentationType: kind, query });
  showCaption(introductions[kind] || "Ya tengo los resultados.", { kind: "presenting" });
  setStatus("Presentando resultados", "presenting");
  await sleep(400);
  narrative.clear();
  panel.dataset.presentation = kind;
  document.body.dataset.presentation = kind;
  stage.prepare(kind);
  scene.setPresentationLayout(true);

  const statistical = ["analytics", "comparison", "data"].includes(kind)
    ? buildStatisticalPresentation(presentations, { query, answer })
    : { html: "", dataFirst: false, summary: "" };
  const html = presentations.map((item) => renderPresentationItem(item, result, answer)).join("");
  const summary = statistical.dataFirst ? statistical.summary || answer : answer;
  const details = statistical.dataFirst && html
    ? `<details class="presentation-detail" open><summary>Consultar información detallada</summary><div class="presentation-stack">${html}</div></details>`
    : `<div class="presentation-stack">${html}</div>`;

  const humanKind = {
    person: "FICHA", document: "INFORME", analytics: "ANÁLISIS",
    comparison: "COMPARATIVA", data: "DATOS",
  }[kind] || "RESULTADO";
  conversation.innerHTML = `<article class="mia-results-full" aria-label="Resultado de mIA">
    <div class="mia-results-kicker">SUNSET BEACH CLUB <span>·</span> mIA INTELLIGENCE</div>
    <header class="mia-results-head"><h2>${escapeHtml(kind === "person" ? "Ficha completa" : kind === "document" ? "Informes y documentos" : kind === "analytics" ? "Inteligencia y análisis" : kind === "comparison" ? "Comparativa" : "Resultados")}</h2>
    <span class="mia-results-chip">${escapeHtml(humanKind)}</span></header>
    <p class="mia-results-summary">${escapeHtml(summary)}</p>
    ${statistical.html || ""}${details}</article>`;

  enhancePremiumTables(conversation, { pageSize: 20, search: true, download: true });
  stage.reveal();
  animateCounters(conversation);
  await sleep(180);
  conversation.scrollTop = 0;
}

// The backend can announce intermediate states while still working.
// Keep the waiting cycle alive instead of restarting its timer on every event.
client.addEventListener("avatar", (event) => {
  if (!behavior || busy) return;
  behavior.enterBackendState(event.detail?.state);
});
client.addEventListener("progress", (event) => {
  if (!busy) return;
  waiting.progress(event.detail?.message ?? event.detail?.state ??
    event.detail?.tool ?? "Estamos tramitando tu solicitud.");
  behavior?.progress();
});

voiceToggle.addEventListener("click", () => {
  voiceEnabled = !voiceEnabled;
  voiceToggle.setAttribute("aria-pressed", String(voiceEnabled));
  voiceToggle.classList.toggle("is-muted", !voiceEnabled);
  if (!voiceEnabled) client.stopSpeaking();
});
// Employee360 quick actions remain functional after an HTML render.
conversation.addEventListener("click", (event) => {
  const action = event.target.closest("[data-mia-prompt]");
  if (action && conversation.contains(action)) {
    event.preventDefault();
    const prompt = action.getAttribute("data-mia-prompt");
    if (prompt) void submit(prompt);
    return;
  }
  if (event.target.closest(".e360x-close")) {
    clearPresentation();
    behavior?.enter("idle");
  }
});

closePanel?.addEventListener("click", () => {
  clearPresentation();
  setStatus("Lista para ayudarte", "idle");
  behavior?.enter("idle");
});

async function submit(text) {
  const question = String(text || "").trim();
  if (busy || !question) return;
  busy = true;
  sendButton.disabled = true;
  voice?.stop();  // una frase por clic; nunca se rearma tras el resultado.
  window.clearTimeout(greetingTimer);
  greetingTimer = null;
  input.blur();
  closeDock({ force: true });
  clearPresentation();
  waiting.start();
  behavior?.enter("thinking", { query: question });
  try {
    const result = await client.send(question);
    waiting.stop(); // progress ends when the backend supplies a result
    const answer = String(result?.answer || result?.speech || "Ya tengo el resultado.");
    const presentations = Array.isArray(result?.presentations) ? result.presentations : [];
    const data = hasPresentationData(presentations);
    const kind = data ? presentationType(presentations) : "conversation";
    if (data) {
      await revealData(result, answer, question, presentations, kind);
    } else {
      // No data => no window/card/panel. mIA comments in place by voice or subtitle.
      clearPresentation();
      showCaption(answer);
    }

    if (voiceEnabled) {
      await client.speak(result?.speech || answer, {
        onStart: () => {
          setStatus("Te lo explico", "speaking");
          if (data) stage.speaking();
          // Keep report/KPI-specific gestures active instead of overwriting
          // them with a generic speaking animation.
          if (data) {
            if (behavior?.state !== "presenting") behavior?.enter("presenting", { answer, presentationType: kind });
          } else {
            behavior?.enter("speaking", { answer, presentationType: kind });
          }
        },
      });
    } else if (!data) {
      await sleep(1000);
    }

    if (data) stage.settle();
    behavior?.enter("idle");
    setStatus("Lista para ayudarte", "idle");
    scheduleIdleMotion();
  } catch (error) {
    waiting.stop();
    console.error("[mIA V4] Error consulta", error);
    clearPresentation();
    showCaption("No he podido completar la consulta. ¿Lo intentamos de nuevo?");
    setStatus("No he podido completarlo", "error");
    behavior?.enter("error");
  } finally {
    waiting.stop();
    busy = false;
    sendButton.disabled = false;
    scheduleDockAutoHide();
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value;
  input.value = "";
  void submit(text);
});

scene.load((progress, detail) => {
  boot.progress(progress, detail);
  setStatus("Preparando a mIA…", "loading");
}).then(async (names) => {
  const sourceClipCount = names.filter((name) => name !== "mIA_IDLE_SAFE").length;
  if (sourceClipCount !== 84) console.warn(`[mIA V4] Se esperaban 84 clips originales; cargados ${sourceClipCount}`);
  behavior = new MiaBehaviorV4({ scene, mode: "3d" });
  clearPresentation();
  await boot.complete();
  const greeting = "¡Hola! Soy mIA, tu asistente virtual. Estoy aquí para ayudarte con cualquier consulta. ¿Qué te gustaría saber?";
  showCaption(greeting, { kind: "welcome" });
  setStatus("Bienvenida a Sunset Beach Club", "greeting");
  behavior.enter("greeting");
  // Ejecutado una sola vez tras el load. Pasar a reposo sin reiniciar saludo.
  greetingTimer = window.setTimeout(() => {
    greetingTimer = null;
    if (!busy && behavior?.state === "greeting") {
      behavior.enter("idle");
      setStatus("Lista para ayudarte", "idle");
    }
  }, Math.max(2000, scene.clipDuration("mIA_SEQ_BIENVENIDA") * 1000 + 250));
  scheduleIdleMotion();
}).catch((error) => {
  boot.fail(error);
  console.error("[mIA V4] No se pudo cargar el GLB", error);
  setStatus("No se ha podido cargar el modelo 3D", "error");
  showCaption("No se ha podido cargar el modelo de mIA.");
});

// Dictado solo por pulsación; V4.2.1 no intenta activación automática.
voice = new MiaVoiceV4({
  onInterim: (text) => {
    input.value = text;
    if (!busy) setStatus("Te escucho", "listening");
  },
  onFinal: (text) => {
    input.value = "";
    if (text.trim()) void submit(text);
  },
  onListening: (active) => {
    voiceIsListening = active;
    for (const button of [micLauncher, micButton]) {
      button.classList.toggle("is-listening", active);
      button.setAttribute("aria-pressed", String(active));
      button.setAttribute("aria-label", active ? "Detener micrófono" : "Activar micrófono");
    }
    if (!busy) setStatus(active ? "Te escucho" : "Lista para ayudarte", active ? "listening" : "idle");
  },
  onError: (error) => {
    const message = error === "unsupported"
      ? "Este navegador no permite dictar. Puedes escribir tu consulta."
      : error === "not-allowed" || error === "service-not-allowed"
        ? "No se ha concedido permiso al micrófono. Puedes escribir tu consulta."
        : "No he podido activar el micrófono. Puedes escribir tu consulta.";
    if (!busy) setStatus(message, "idle");
  },
});
if (!voice.available) {
  micLauncher.disabled = true;
  micButton.disabled = true;
  micLauncher.title = micButton.title = "El navegador no permite dictado";
}
window.addEventListener("pagehide", () => {
  boot.dispose();
  window.clearTimeout(greetingTimer);
  waiting.stop();
  client.stopSpeaking();
  voice?.destroy();
  behavior?.destroy();
  narrative.clear();
});
