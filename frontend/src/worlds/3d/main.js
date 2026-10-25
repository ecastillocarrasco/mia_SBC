import './sbc-logo-assembly-v2.css';
import './sbc-logo-assembly-v3.css';
import { SbcIntroDirectorV2 } from './sbc-intro-director-v2.js';
import { sbcAssemblyMarkup } from '../../core/sbc-logo-assembly-v2.js';
import { installMiaAnimationLab } from "./animation-lab-v530.js";
import { MiaBootLoader } from "../../core/boot-loader-v43.js";
import { getWelcomeText } from "../../core/identity-v45.js";
import { MiaWelcomeVoiceV45 } from "../../core/welcome-voice-v45.js";
import { MiaWelcomeAutostartV47 } from "../../core/welcome-autostart-v47.js";
import { render2DTableExtras, summarizeCoverage, presentationCoverageLabel } from "../../core/presentation-parity-v45.js";
import { completePresentations } from "../../core/answer-structure-v45.js";
import { MiaClient } from "../../core/client.js";
import { MiaVoiceV4 } from "../../core/voice-v4.js";
import { MiaWaitingV4 } from "../../core/waiting-v4.js";
import { MiaNarrativeV42 } from "../../core/narrative-v42.js";
import { renderPresentation } from "../../core/present.js";
import { buildStatisticalPresentation } from "../../core/statistical-visuals.js";
import { MiaScene } from "../../core/scene.js";
import { PresentationStage } from "../../core/presentation-stage.js";
import { HolographicResults3D } from "./holographic-results-v1.js";
import { MiaBehaviorV4 } from "../../core/behavior-v4.js";
import { enhancePremiumTables, hasPresentationData, presentationType } from "../../core/premium-tables.js";
import {
  isEmployee360Payload,
  buildEmployee360Presentation,
  renderEmployee360PresentationHtml,
} from "../../core/employee360-presentation.js";
import { ensureAuthenticated, ensureAuthorized, getAccessToken } from "../../core/auth-gate.js";
import { isVoiceMuted, setVoiceMuted } from "../../core/voice-mute.js";
import { start as startMailWatch, ensureNotificationPermission, announceNewMail, mailPromptQuery, consumeMailPrompt } from "../../core/mail-watch.js";

// Si MIA_AUTH__MODE=entra exige login y ya hay sesión (p. ej. iniciada desde el portal), sigue
// sin tocar nada. Si no hay sesión, `interactive: false` NUNCA inicia aquí su propio login (cada
// página tendría su propia redirectUri que registrar en Entra ID aparte) — en vez de eso vuelve
// al portal, que es el único punto con login real: el mundo 3D nunca llega a montarse en ese
// caso, ni siquiera si alguien navega directo a esta página (o a mia-3d.html, que solo reenvía
// aquí) sin pasar antes por el portal.
await ensureAuthenticated({ interactive: false });
// Login correcto no es lo mismo que tener acceso: sin ningún permiso asignado, esto sustituye
// la página entera por el aviso correspondiente y tampoco resuelve nunca.
await ensureAuthorized();
// Aviso de correo nuevo (pedido del usuario, igual que mia-desktop y el mundo 2D): notificación
// del navegador con un clic que abre el cajón de texto y deja la pregunta de resumen ya escrita.
void ensureNotificationPermission();
startMailWatch((correos, { restored = false } = {}) => {
  if (busy) { deferredMailNotices.push({ correos, restored }); return; }
  announceNewMail(correos, {
    restored,
    speak: (text) => { if (voiceEnabled) void client.speak(text); },
    onSummary: (correo) => { openDock({ focus: true }); void submit(mailPromptQuery(correo, 'summary')); },
    onDetails: (correo) => { openDock({ focus: true }); void submit(mailPromptQuery(correo, 'details')); },
    onDismiss: () => { if (voiceEnabled) void client.speak('De acuerdo, seguimos con lo que estábamos.'); },
  });
});

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
const boot = new MiaBootLoader({ mode: "3d", variant: "sbc-assembly", markup: sbcAssemblyMarkup });
const scene = new MiaScene(document.getElementById("canvas-root"));
// Fuller, eye-level framing; the floor is uniform white and has no horizon.
scene.camera.position.set(0, 1.47, 3.88);
scene.target.set(0, 1.18, 0);
// V4.6: a modest, reversible face adjustment. For developer calibration use
// ?facePitch=7&faceYaw=2 (only honoured in npm run dev).
const faceQuery = new URLSearchParams(window.location.search);
const faceNumber = (param, fallback) => import.meta.env.DEV && faceQuery.has(param)
  && Number.isFinite(Number(faceQuery.get(param)))
  ? Number(faceQuery.get(param)) : fallback;
scene.configureFacePose({
  enabled: true, pitchDeg: faceNumber('facePitch', 6),
  yawDeg: faceNumber('faceYaw', 4), strength: 0.7,
});
const client = new MiaClient();
const miaAnimationLab = installMiaAnimationLab(scene); // mIA V5.3.0, temporal
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
const introDirector = new SbcIntroDirectorV2(boot.node, { reducedMotion });
const stage = new PresentationStage({ root: document.body, reducedMotion, mode: "3d" });
const holographicResults = new HolographicResults3D({ scene, panel, reducedMotion });

// Silenciada/activada: persistida y compartida con los otros mundos (mismo
// navegador). Por defecto mIA NO está silenciada.
let voiceEnabled = !isVoiceMuted();
voiceToggle.setAttribute("aria-pressed", String(voiceEnabled));
voiceToggle.classList.toggle("is-muted", !voiceEnabled);
let busy = false;
const deferredMailNotices = [];
function flushMailNotices() {
  if (busy || !deferredMailNotices.length) return;
  const notices = deferredMailNotices.splice(0);
  const batch = notices.flatMap((notice) => notice.correos);
  announceNewMail(batch, {
    restored: notices.every((notice) => notice.restored),
    speak: (text) => { if (voiceEnabled) void client.speak(text); },
    onSummary: (correo) => { openDock({ focus: true }); void submit(mailPromptQuery(correo, 'summary')); },
    onDetails: (correo) => { openDock({ focus: true }); void submit(mailPromptQuery(correo, 'details')); },
    onDismiss: () => { if (voiceEnabled) void client.speak('De acuerdo, seguimos con lo que estábamos.'); },
  });
}
let behavior = null;
let dockHideTimer = null;
let greetingTimer = null;
let welcomeMessage = getWelcomeText();
let welcomeVoice = null;
let welcomeAutostart = null;

function scheduleGreetingEnd() {
  window.clearTimeout(greetingTimer);
  const duration = scene.clipDuration('mIA_SEQ_BIENVENIDA_SAFE') ||
    scene.clipDuration('mIA_SEQ_BIENVENIDA') || 6;
  // Start the crossfade BEFORE the end of the last safe frame.
  const delay = Math.max(1500, duration * 1000 - 650);
  greetingTimer = window.setTimeout(() => {
    greetingTimer = null;
    if (!busy && behavior?.state === 'greeting') {
      behavior.enter('idle');
      setStatus('Lista para ayudarte', 'idle');
    }
  }, delay);
}

welcomeVoice = new MiaWelcomeVoiceV45({
  apiBase: client.apiBase,
  getAuthHeaders: async () => {
    const token = await getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  },
  onBlocked: () => welcomeAutostart?.blocked(),
  onStart: () => {
    welcomeAutostart?.markPlaying();
    // Si la voz llega tras un bloqueo, reiniciar el gesto de bienvenida.
    if (!busy && behavior && behavior.state !== 'greeting') {
      behavior.enter('greeting');
      scheduleGreetingEnd();
    }
  },
});
welcomeAutostart = new MiaWelcomeAutostartV47({
  voice: welcomeVoice,
  canSpeak: () => !busy && voiceEnabled && !document.hidden,
  eventTarget: window,
});
// Preload ElevenLabs audio in parallel with the heavy 84-clip GLB.
// The actual play attempt waits until Mía is visible.
const initialWelcomeText = welcomeMessage;
const initialWelcomeAudio = welcomeVoice.prepare(initialWelcomeText);
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
  // Ocultar el editor NO revoca el modo continuo elegido explícitamente.
  // En modo de una pregunta, cerrar voluntariamente cancela esa escucha.
  if (force && voice?.mode === "once") voice.stop();
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
  if (welcomeAutostart?.pending) {
    welcomeAutostart.cancel();
    welcomeVoice.cancel();
  }
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

textLauncher.addEventListener("click", () => {
  // No saludar de forma sorpresiva cuando el usuario ya esta iniciando
  // una consulta. La bienvenida pertenece a la entrada a la experiencia.
  if (welcomeAutostart?.pending) {
    welcomeAutostart.cancel();
    welcomeVoice.cancel();
  }
  openDock({ focus: true });
});
function micClick() {
  // Durante la respuesta permitimos apagar el modo continuo, pero nunca
  // activar una nueva escucha mientras suena el TTS de Mía.
  if (busy) {
    if (voice?.mode === "continuous") voice.stop();
    return;
  }
  // El botón flotante permanece en el mismo sitio para las tres pulsaciones.
  // No abrir la barra de texto automáticamente al tocar el micro.
  voice?.cycle(); // apagado -> una consulta -> continuo -> apagado.
}
micLauncher.addEventListener("click", micClick);
micButton.addEventListener("click", micClick);
dockClose.addEventListener("click", () => { input.blur(); closeDock({ force: true }); });
input.addEventListener("input", scheduleDockAutoHide);
input.addEventListener("blur", scheduleDockAutoHide);

// Paridad con 2D: abrir un correo o proponer respuesta desde el listado, sin escribirlo a mano.
// Delegado sobre `conversation` (su innerHTML se reemplaza en cada respuesta, el listener no).
conversation.addEventListener("click", (event) => {
  const button = event.target.closest?.("[data-mail-action]");
  if (!button || button.disabled) return;
  const ref = button.dataset.mailRef;
  if (!ref) return;
  openDock({ focus: true });
  if (button.dataset.mailAction === "open") void submit(`Abre el correo ${ref}`);
  else if (button.dataset.mailAction === "reply") void submit(`Propón una respuesta al correo ${ref}`);
});

// Adjuntos de correo: /api/mail/attachment/... exige token (Authorization Bearer), que un <a href>
// normal no puede mandar (daría 401, bug ya corregido en 2D con el mismo patrón: fetch + blob).
conversation.addEventListener("click", async (event) => {
  const button = event.target.closest?.("[data-attachment-url]");
  if (!button || button.disabled) return;
  const url = button.dataset.attachmentUrl;
  const name = button.dataset.attachmentName || "adjunto";
  const actionLabel = button.querySelector(".mia-mail-attachment-action");
  button.disabled = true;
  if (actionLabel) actionLabel.textContent = "Descargando…";
  try {
    const token = await getAccessToken();
    const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl; link.download = name; link.rel = "noopener noreferrer";
    document.body.appendChild(link); link.click(); document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    if (actionLabel) actionLabel.textContent = "Descargar ↓";
  } catch (error) {
    console.warn("[mIA V4] No se pudo descargar el adjunto:", error);
    if (actionLabel) actionLabel.textContent = "Error al descargar";
  } finally {
    button.disabled = false;
  }
});

// Botones de descarga de informes (/api/reports/...): mismo motivo que los adjuntos de correo
// arriba -- exige Authorization: Bearer, que un <a href> normal no puede mandar.
conversation.addEventListener("click", async (event) => {
  const button = event.target.closest?.("[data-download-url]");
  if (!button || button.disabled) return;
  const url = button.dataset.downloadUrl;
  const name = button.dataset.downloadName || "archivo";
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Descargando…";
  try {
    const token = await getAccessToken();
    const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl; link.download = name; link.rel = "noopener noreferrer";
    document.body.appendChild(link); link.click(); document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    button.textContent = originalText;
  } catch (error) {
    console.warn("[mIA V4] No se pudo descargar el informe:", error);
    button.textContent = "Error al descargar";
  } finally {
    button.disabled = false;
  }
});

function renderPresentationItem(item, result, answer) {
  if (isEmployee360Payload(result, item?.data ?? {})) {
    try {
      const pres = buildEmployee360Presentation(item?.data ?? {});
      return renderEmployee360PresentationHtml(pres, item?.data ?? {}, answer);
    } catch (error) {
      console.warn("[mIA V4] Ficha Employee360: renderer alternativo", error);
    }
  }
  // Paridad con el mundo 2D: una tabla puede traer KPIs, charts y stats
  // independientes. El renderer básico del 3D los ignoraba por completo.
  return renderPresentation(item) + render2DTableExtras(item);
}

function clearPresentation() {
  panel.dataset.presentation = "conversation";
  document.body.dataset.presentation = "conversation";
  stage.reset();
  holographicResults.reset();
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
  holographicResults.prepare();

  const statistical = ["analytics", "comparison", "data"].includes(kind)
    ? buildStatisticalPresentation(presentations, { query, answer })
    : { html: "", dataFirst: false, summary: "" };
  const html = presentations.map((item) => renderPresentationItem(item, result, answer)).join("");
  const coverage = summarizeCoverage(presentations);
  // Recuentos derivados exclusivamente del payload recibido. Nunca inferir
  // que todos los departamentos están incluidos si el backend filtró datos.
  if (import.meta.env.DEV) console.info('[mIA V4.5] Estructura recibida del backend', coverage);
  const coverageHtml = `<div class="mia45-coverage">${escapeHtml(presentationCoverageLabel(coverage))}</div>`;
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
    ${coverageHtml}${statistical.html || ""}${details}</article>`;

  enhancePremiumTables(conversation, { pageSize: 20, search: true, download: true });
  stage.reveal();
  holographicResults.reveal();
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
  setVoiceMuted(!voiceEnabled);
  voiceToggle.setAttribute("aria-pressed", String(voiceEnabled));
  voiceToggle.classList.toggle("is-muted", !voiceEnabled);
  if (!voiceEnabled) {
    client.stopSpeaking();
    welcomeAutostart.cancel();
    welcomeVoice.cancel();
  }
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
  let question = String(text || "").trim();
  if (busy || !question) return;
  const mailReply = consumeMailPrompt(question);
  if (mailReply?.action === 'dismiss') { if (voiceEnabled) await client.speak('De acuerdo, seguimos con lo que estábamos.'); return; }
  if (mailReply?.action === 'summary' || mailReply?.action === 'details') question = mailPromptQuery(mailReply.correo, mailReply.action);
  busy = true;
  welcomeAutostart.cancel(); // Impide el saludo tardio si ya hay una consulta.
  welcomeVoice.cancel();
  sendButton.disabled = true;
  // Una consulta: se apaga tras hablar. Continuo: pausa mientras responde,
  // sin perder la elección explícita del usuario.
  voice?.pause();
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
    // In 2D the response Markdown is rendered as tables. Reconstruct only
    // explicit Markdown tables also in 3D, without inventing staff or areas.
    const presentations = completePresentations(answer, result?.presentations);
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
    voice?.resume();  // solo reactiva el modo continuo elegido por el usuario
    scheduleDockAutoHide();
    flushMailNotices();
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
  const sourceClipCount = names.filter((name) =>
    !['mIA_IDLE_SAFE', 'mIA_SEQ_BIENVENIDA_SAFE'].includes(name)).length;
  if (sourceClipCount !== 84) console.warn(`[mIA V4] Se esperaban 84 clips originales; cargados ${sourceClipCount}`);
  behavior = new MiaBehaviorV4({ scene, mode: "3d" });
  clearPresentation();
  // The audio is downloaded while the GLB loads. At 100%, wait for the sound
  // to be prepared BEFORE offering the one-click entrance. Avoid waiting
  // forever if the voice service is unavailable: browser TTS remains possible.
  const greeting = getWelcomeText();
  welcomeMessage = greeting;
  const audioPromise = greeting === initialWelcomeText
    ? initialWelcomeAudio : welcomeVoice.prepare(greeting);
  let voiceTimeout = null;
  const audioReady = await Promise.race([
    audioPromise,
    new Promise((resolve) => {
      voiceTimeout = window.setTimeout(() => resolve({ status: 'timeout' }), 8000);
    }),
  ]);
  window.clearTimeout(voiceTimeout);
  if (audioReady?.status === 'timeout') welcomeVoice.cancel();
  setStatus("mIA está preparada", "ready");
  await boot.revealAvatar(scene);
  // V4.9: the REAL click on the loading screen starts cached audio.play()
  // immediately. No async preparation, setTimeout, or simulated button click
  // is allowed before the playback invocation.
  await boot.complete({ onContinue: () => {
    welcomeAutostart?.cancel();
    showCaption(greeting, { kind: "welcome" });
    setStatus("Bienvenida a Sunset Beach Club", "greeting");
    behavior.enter("greeting");
    scheduleGreetingEnd();
    if (!voiceEnabled) return { status: 'skipped-audio' };
    return welcomeVoice.replay(greeting);
  }});
  introDirector.dispose();
  scheduleIdleMotion();
}).catch((error) => {
  introDirector.dispose();
  boot.fail(error);
  console.error("[mIA V4] No se pudo cargar el GLB", error);
  setStatus("No se ha podido cargar el modelo 3D", "error");
  showCaption("No se ha podido cargar el modelo de mIA.");
});

// V4.4: los estados del micro pertenecen al usuario y no se restauran solos.
const micAnnounce = document.getElementById("miaMicModeAnnounce");
function displayMicMode(mode, { paused = false } = {}) {
  const info = {
    off: { text: "Micrófono desactivado", next: "Activar para una pregunta" },
    once: { text: paused ? "Una consulta completada. Micrófono en pausa" : "Micrófono: una pregunta",
      next: "Dejar escuchando continuamente" },
    continuous: {
      text: paused ? "Escucha continua: en pausa durante la respuesta" : "Micrófono en escucha continua",
      next: "Desactivar micrófono",
    },
  }[mode] || { text: "Micrófono desactivado", next: "Activar para una pregunta" };
  for (const button of [micLauncher, micButton]) {
    button.dataset.micMode = mode;
    button.classList.toggle("is-once", mode === "once");
    button.classList.toggle("is-continuous", mode === "continuous");
    button.classList.toggle("is-suspended", mode !== "off" && paused);
    button.setAttribute("aria-pressed", String(mode !== "off"));
    button.setAttribute("aria-label", `${info.text}. Siguiente pulsación: ${info.next}`);
    button.title = `${info.text} · ${info.next}`;
  }
  if (micAnnounce) micAnnounce.textContent = info.text;
  if (!busy && mode !== "off") setStatus(info.text, "listening");
  else if (!busy && document.body.dataset.miaState === "listening") {
    setStatus("Lista para ayudarte", "idle");
  }
}

voice = new MiaVoiceV4({
  onInterim: (text) => {
    input.value = text;
    if (!busy) setStatus("Te escucho", "listening");
  },
  onFinal: (text) => {
    input.value = "";
    if (text.trim()) void submit(text);
  },
  onListening: (active) => { voiceIsListening = active; },
  onModeChange: (mode, info) => { displayMicMode(mode, info); },
  onError: (error) => {
    const message = error === "unsupported"
      ? "Este navegador no permite dictar. Puedes escribir tu consulta."
      : error === "not-allowed" || error === "service-not-allowed"
        ? "No se ha concedido permiso al micrófono. Puedes escribir tu consulta."
        : "No he podido activar el micrófono. Puedes escribir tu consulta.";
    if (!busy) setStatus(message, "idle");
  },
});
displayMicMode("off");
if (!voice.available) {
  micLauncher.disabled = true;
  micButton.disabled = true;
  micLauncher.title = micButton.title = "El navegador no permite dictado";
}
window.addEventListener("pagehide", () => {
  introDirector.dispose();
  boot.dispose();
  window.clearTimeout(greetingTimer);
  waiting.stop();
  client.stopSpeaking();
  welcomeAutostart.dispose();
  welcomeVoice.dispose();
  voice?.destroy();
  behavior?.destroy();
  narrative.clear();
});
