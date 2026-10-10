import { MiaClient } from "../../core/client.js";
import { bindMicButton } from "../../core/dictation.js";
import { renderPresentation } from "../../core/present.js";
import { buildStatisticalPresentation } from "../../core/statistical-visuals.js";
import { MiaScene } from "../../core/scene.js";
import { PresentationStage } from "../../core/presentation-stage.js";
import { AvatarController } from "../../core/avatar-controller.js";
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

const scene = new MiaScene(document.getElementById("canvas-root"));
// Camera framing: face-level shot so the character looks frontal, not upward.
// The head-tracking in scene._loop() will converge ~3° upward from here — natural.
scene.camera.position.set(0, 1.62, 5.2);
scene.target.set(0, 1.55, 0);
const client = new MiaClient();
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
let voiceEnabled = true;
let busy = false;
let avatarController = null;
let _wanderTimer = null;
const stage = new PresentationStage({ root: document.body, reducedMotion, mode: "3d" });

const escapeHtml = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 0 : ms));

const SIMPLE_CONVERSATION_RE = /^(?:hola(?:\s+m[ií]a)?|buen(?:os\s+d[ií]as|as\s+tardes|as\s+noches)|hey|buenas|gracias(?:\s+m[ií]a)?|muchas\s+gracias|adi[oó]s|hasta\s+luego|hasta\s+pronto|qu[eé]\s+tal(?:\s+m[ií]a)?|c[oó]mo\s+est[aá]s(?:\s+m[ií]a)?|qui[eé]n\s+eres|qu[eé]\s+puedes\s+hacer)[.!?¡¿,\s]*$/i;

function isSimpleConversationQuery(value) {
  const text = String(value ?? "").trim().replace(/\s+/g, " ");
  return text.length > 0 && text.length <= 80 && SIMPLE_CONVERSATION_RE.test(text);
}

function setStatus(text, state = "idle") {
  statusLabel.textContent = text;
  document.body.dataset.miaState = state;
}

// ── Idle wandering ────────────────────────────────────────────────────────────

function scheduleIdleWander() {
  clearTimeout(_wanderTimer);
  if (reducedMotion) return;
  const delay = 7000 + Math.random() * 6000; // 7–13 s — more frequent movement
  _wanderTimer = window.setTimeout(() => {
    if (document.body.dataset.miaState === "idle") {
      const x = (Math.random() - 0.5) * 0.60; // ±0.30 units — visible cross-screen travel
      const duration = 1600 + Math.random() * 1800; // 1.6 – 3.4 s — sometimes quick, sometimes slow
      scene.wanderTo(x, duration);
    }
    scheduleIdleWander();
  }, delay);
}

// ── Counter animation ─────────────────────────────────────────────────────────

function animateCounters(root) {
  for (const el of root.querySelectorAll(
    ".stat-kpis strong, .stat-metric-tile strong, .stat-kpi-cluster strong, .e360-kpi strong",
  )) {
    const raw = el.textContent.trim();
    // Capture leading number (integer or decimal) and trailing suffix
    const m = raw.match(/^([\d]+(?:[.,]\d+)?)(.*)$/);
    if (!m) continue;
    const num = parseFloat(m[1].replace(",", "."));
    if (isNaN(num) || num <= 0 || num > 99999) continue;
    const suffix = m[2];
    const isInt = Number.isInteger(num);
    const dp = isInt ? 0 : (m[1].includes(".") ? m[1].split(".")[1].length : 1);
    const dur = Math.min(1100, 500 + num * 1.5);
    const t0 = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - t, 3); // ease-out cubic
      el.textContent = (num * e).toFixed(dp) + suffix;
      if (t < 1) requestAnimationFrame(tick);
      else el.textContent = raw; // restore exact original string on finish
    };
    requestAnimationFrame(tick);
  }
}

// ── Bubble helpers ────────────────────────────────────────────────────────────

function addBubble(role, html, { kind = "" } = {}) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}${kind ? ` kind-${kind}` : ""}`;
  bubble.innerHTML = html;
  conversation.appendChild(bubble);
  conversation.scrollTop = conversation.scrollHeight;
  return bubble;
}

// ── Presentation kind detection ───────────────────────────────────────────────

function presentationKind(items = []) {
  const text = items.map((item) => `${item?.type || ""} ${item?.title || ""}`).join(" ").toLowerCase();
  if (/employee|emplead|ficha|persona/.test(text)) return "person";
  if (/download|document|pdf|excel|archivo|nomina|nómina/.test(text)) return "document";
  if (/dashboard|chart|graf|estad|kpi|analytic/.test(text)) return "analytics";
  if (/table|list|lista|turno|shift/.test(text)) return "data";
  return "data";
}

function statusForKind(kind) {
  if (kind === "analytics") return "He cruzado los datos. Te muestro lo más relevante.";
  if (kind === "person") return "Tengo la ficha preparada. Te la muestro.";
  if (kind === "document") return "He preparado el resultado. Te lo presento.";
  return "Ya lo tengo. Te lo muestro.";
}

// ── Render helpers ────────────────────────────────────────────────────────────

function renderPresentationItem(item, result, answer) {
  if (isEmployee360Payload(result, item?.data ?? {})) {
    try {
      const pres = buildEmployee360Presentation(item?.data ?? {});
      return renderEmployee360PresentationHtml(pres, item?.data ?? {}, answer);
    } catch {
      // fall through to generic renderer
    }
  }
  return renderPresentation(item);
}

// ── Presentation reveal ───────────────────────────────────────────────────────

async function revealPresentation(result, answer, query = "", statistical = null) {
  const presentations = Array.isArray(result?.presentations) ? result.presentations : [];
  const explicitKind = presentationKind(presentations);
  const stat = statistical || { html: "", dataFirst: false, summary: "", sourceMode: "full" };
  const kind = stat.dataFirst ? "analytics" : explicitKind;

  panel.dataset.presentation = kind;
  document.body.dataset.presentation = kind;
  stage.prepare(kind);
  setStatus(statusForKind(kind), "presenting");

  // Avatar thinks → moves slightly toward panel
  if (avatarController) {
    avatarController.enter("thinking");
  } else {
    scene.playState(kind === "analytics" ? "concentrada" : "pensando");
  }
  scene.wanderTo(-0.16, 1600);
  await sleep(280);

  const sourceHtml = presentations
    .map((item) => renderPresentationItem(item, result, answer))
    .join("");
  const summary = stat.dataFirst ? stat.summary : answer;
  const detailHtml = sourceHtml
    ? stat.dataFirst
      ? `<details class="presentation-detail"><summary>Ver datos completos</summary><div class="presentation-stack">${sourceHtml}</div></details>`
      : `<div class="presentation-stack">${sourceHtml}</div>`
    : "";

  const bubble = addBubble(
    "mia presentation-bubble",
    `<p class="answer-summary${stat.dataFirst ? " is-visual-summary" : ""}">${escapeHtml(summary)}</p>${stat.html}${detailHtml}`,
    { kind },
  );

  requestAnimationFrame(() => {
    bubble.classList.add("is-visible");
    stage.reveal();
    // Trigger counter animations after reveal frame.
    window.setTimeout(() => animateCounters(bubble), 80);
  });

  await sleep(220);
  if (avatarController) {
    avatarController.enter("presenting", { presentationType: kind });
  } else {
    scene.playState(kind === "person" ? "saludando" : "aprobando");
  }
  return { bubble, summary };
}

function showConversationAnswer() {
  panel.dataset.presentation = "conversation";
  document.body.dataset.presentation = "conversation";
  stage.reset();
  // Conversación sin datos: mIA responde por voz, sin card/burbuja visual.
  return null;
}

// ── Avatar state routing ──────────────────────────────────────────────────────

client.addEventListener("avatar", (e) => {
  if (avatarController) {
    avatarController.enterBackendState(e.detail.state);
  } else {
    scene.playState(e.detail.state);
  }
});

client.addEventListener("progress", (e) => {
  setStatus(e.detail.message || "Estoy consultando…", "thinking");
});

voiceToggle.addEventListener("click", () => {
  voiceEnabled = !voiceEnabled;
  voiceToggle.setAttribute("aria-pressed", String(voiceEnabled));
  voiceToggle.classList.toggle("is-muted", !voiceEnabled);
  if (!voiceEnabled) client.stopSpeaking();
});

// ── Submit ────────────────────────────────────────────────────────────────────

async function submit(text) {
  if (busy || !text.trim()) return;
  busy = true;
  sendButton.disabled = true;
  clearTimeout(_wanderTimer);

  // Animate the most recent presentation bubble out before the new query
  const prevBubbles = conversation.querySelectorAll(".presentation-bubble.is-visible");
  const prevBubble = prevBubbles[prevBubbles.length - 1] ?? null;
  if (prevBubble) {
    prevBubble.classList.remove("is-visible");
    prevBubble.classList.add("is-leaving");
  }

  stage.reset();
  addBubble("user", escapeHtml(text));

  if (avatarController) {
    avatarController.enter("thinking");
  } else {
    scene.playState("pensando");
  }
  scene.wanderTo(0, 1000);
  setStatus("Estoy consultando…", "thinking");

  try {
    const result = await client.send(text);
    const answer = result?.answer || result?.speech || "Ya tengo el resultado.";
    const presentations = Array.isArray(result?.presentations) ? result.presentations : [];
    const conversationOnly = isSimpleConversationQuery(text);
    const explicitKind = presentationKind(presentations);
    const statistical =
      conversationOnly || ["person", "document"].includes(explicitKind)
        ? { html: "", dataFirst: false, summary: "", sourceMode: "full" }
        : buildStatisticalPresentation(presentations, { query: text, answer });
    const hasPresentation = !conversationOnly && (presentations.length > 0 || statistical.dataFirst);

    if (hasPresentation) {
      await revealPresentation(result, answer, text, statistical);
    } else {
      showConversationAnswer();
      setStatus("Lista para ayudarte", "idle");
    }

    if (voiceEnabled) {
      await client.speak(result?.speech || answer, {
        onStart: () => {
          setStatus("Te lo explico", "speaking");
          stage.speaking();
          if (avatarController) {
            avatarController.enter("speaking", { answer, presentationType: explicitKind });
          } else {
            scene.playState("hablando");
          }
          // Lean slightly toward panel while speaking
          scene.wanderTo(-0.10, 1200);
        },
      });
    }

    const finalState = result?.avatar_state || "reposo";
    if (avatarController) {
      avatarController.enterBackendState(finalState);
    } else {
      scene.playState(finalState);
    }
    if (hasPresentation) stage.settle();
    setStatus("Lista para ayudarte", "idle");
    document.body.dataset.miaState = "idle";
    scene.wanderTo(0, 2500);
    scheduleIdleWander();
  } catch (error) {
    console.error(error);
    addBubble("mia error", "<p>No he podido completar la consulta. ¿Lo intentamos de nuevo?</p>");
    setStatus("No he podido completarlo", "error");
    if (avatarController) {
      avatarController.enter("error");
    } else {
      scene.playState("confundida");
    }
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

// ── Scene load ────────────────────────────────────────────────────────────────

scene
  .load((p) => {
    setStatus(`Cargando el modelo… ${Math.round(p * 100)} %`, "loading");
  })
  .then(() => {
    // Wire AvatarController now that we know which animations exist.
    avatarController = new AvatarController({
      hasAnimation: (name) => scene.actions.has(name),
      playAnimation: (name, opts) => scene.play(name, opts?.fade ?? 0.35),
      playGesture: (name, opts) => scene.playGesture(name, opts),
      stopGesture: (fade) => scene.stopGesture(fade),
      enableIdleMicroGestures: true,
      enableSpeakingGestures: true,
    });
    setStatus("Lista para ayudarte", "idle");
    avatarController.enter("greeting");
    scheduleIdleWander();
  })
  .catch((error) => {
    console.error(error);
    setStatus("No se ha podido cargar el modelo 3D", "error");
  });

bindMicButton(document.getElementById("mic"), {
  onInterim: (text) => {
    input.value = text;
    setStatus("Te escucho", "listening");
    if (avatarController) {
      avatarController.enter("listening");
    } else {
      scene.playState("escuchando");
    }
    scene.wanderTo(0.05, 800);
  },
  onFinal: (text) => {
    input.value = "";
    submit(text);
  },
});
