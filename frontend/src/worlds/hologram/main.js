import { MiaBootLoader } from "../../core/boot-loader-v43.js";
import { getWelcomeText } from "../../core/identity-v45.js";
import { MiaWelcomeVoiceV45 } from "../../core/welcome-voice-v45.js";
import * as THREE from "three";
import { MiaClient } from "../../core/client.js";
import { MiaVoiceV4 } from "../../core/voice-v4.js";
import { avatarLabel } from "../../core/avatar.js";
import { MiaScene } from "../../core/scene.js";
import { MiaHologramDirectorV52 } from "./hologram-director-v52.js";
import { MiaWaitingV4 } from "../../core/waiting-v4.js";
import { hasPresentationData, presentationType } from "../../core/premium-tables.js";
import { renderHologramBrief } from "../../core/hologram-brief.js";
import { createHologramStage, enhanceHologramAvatar } from "./hologram-premium-v5.js";
import { installHologramStyle } from "./hologram-material-v51.js";
import { adaptHologramResult } from "./hologram-results-v521.js";
import { sendHologramVia2D, createHologramApiContext } from "./hologram-api-v525.js";
import { createHologramReplyIntegrity } from "./hologram-integrity-v526.js";
import { hologramExecutiveCopy, isWorkingNowQuestion } from "./hologram-executive-v522.js";
import { HologramVoiceV522 } from "./hologram-voice-v522.js";
import { createHologramTurnGuard, sanitizeHologramTrace } from "./hologram-lifecycle-v523.js";
import { isReportGenerationIntent } from "./hologram-api-v525.js";
import { readHologramWorldContext, saveHologramWorldContext, bindHologramWorldNavigation } from "./hologram-session-v529.js";
import { extractHologramJob, pollHologramJob, reportDownloadHref, getJobStatusLabel, jobIsActive } from "./hologram-jobs-v529.js";
import { ensureAuthenticated, ensureAuthorized, getAccessToken } from "../../core/auth-gate.js";
import { start as startMailWatch, ensureNotificationPermission, announceNewMail, mailPromptQuery, consumeMailPrompt } from "../../core/mail-watch.js";

// Si MIA_AUTH__MODE=entra exige login y no hay sesión, `interactive: false` vuelve al portal (el
// único punto con login real — ver auth-gate.js) en vez de iniciar aquí su propio redirect a
// Microsoft: el mundo holograma nunca llega a montarse en ese caso.
await ensureAuthenticated({ interactive: false });
// Login correcto no es lo mismo que tener acceso: sin ningún permiso asignado, esto sustituye
// la página entera por el aviso correspondiente y tampoco resuelve nunca.
await ensureAuthorized();
// Aviso de correo nuevo (pedido del usuario, igual que mia-desktop y los mundos 2D/3D): notificación
// del navegador con un clic que deja la pregunta de resumen ya escrita en el composer.
void ensureNotificationPermission();
startMailWatch((correos, { restored = false } = {}) => {
  if (busy) { deferredMailNotices.push({ correos, restored }); return; }
  announceMailBatch(correos, { restored });
});

const caption = document.getElementById("caption");
const resultEl = document.getElementById("result");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const micButton = document.getElementById("mic");
const boot = new MiaBootLoader({ mode: "hologram" });
// Boton compartido con el mundo 3D: 'Comenzar experiencia →'.
const scene = new MiaScene(document.getElementById("canvas-root"), {
  background: 0x01090d, shadows: false, fov: 34,
});
// Encuadre y materiales se afinan exclusivamente para el holograma tras cargar el GLB.
const client = new MiaClient();
// El HG no lee nunca la antigua sesión compartida de localStorage.
// Un traspaso requiere navegación real desde otro mundo, es de un solo uso
// y caduca en dos minutos. En visitas directas se conserva solo la sesión HG.
const hgSessionOrigin = readHologramWorldContext();
const hgContext = createHologramApiContext(hgSessionOrigin.context);
bindHologramWorldNavigation(document, () => hgContext.value);
const hgIntegrity = createHologramReplyIntegrity();
const premiumStage = createHologramStage();
const hologramVoice = new HologramVoiceV522({
  apiBase: client.apiBase,
  getAuthHeaders: async () => {
    const token = await getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  },
});
// V5.3.1: manual recovery when remote voice is blocked or the service fails.
// The audio from /api/voice/stream remains cached; no browser TTS is used.
const voiceWidget = document.createElement('div');
voiceWidget.id = 'hgVoiceWidget';
voiceWidget.className = 'hg-voice-widget';
voiceWidget.innerHTML = `<button id="hgListenResponse" class="hg-voice-listen" type="button" aria-label="Probar voz de mIA">♫ Probar voz</button>
  <span id="hgVoiceState" class="hg-voice-state" role="status" aria-live="polite">Voz configurada en el servidor</span>`;
document.querySelector('.hud .composer')?.insertAdjacentElement('beforebegin',voiceWidget);
const voiceReplayButton = voiceWidget.querySelector('#hgListenResponse');
const voiceState = voiceWidget.querySelector('#hgVoiceState');
let lastSpokenText = '';
const testVoiceText = 'Hola, soy mIA. Esta es mi voz configurada en el servidor.';
function describeVoiceStatus(result) {
  switch(result?.status) {
    case 'completed': return 'Audio del servidor reproducido';
    case 'already-playing': return 'mIA está hablando';
    case 'playback-blocked': return 'El navegador bloqueó el audio. Pulsa escuchar.';
    case 'playback-error': return 'El navegador no pudo reproducir el formato de audio.';
    case 'voice-http-error': return `Servicio de voz: error HTTP ${result.http || 'desconocido'}`;
    case 'voice-invalid-content-type': return `La ruta TTS no devuelve audio (${result.mime || 'sin formato'})`;
    case 'voice-fetch-timeout': return 'El servicio de voz tardó demasiado.';
    case 'voice-timeout': return 'La reproducción de voz agotó el plazo.';
    case 'voice-network-error': return 'No se pudo contactar con el servicio de voz.';
    case 'voice-empty-audio': return 'El servicio de voz devolvió audio vacío.';
    case 'cancelled': return 'Voz detenida';
    default: return 'Voz no disponible: consulta el diagnóstico.';
  }
}
function voiceResultUi(result) {
  const status = result?.status || 'unknown';
  voiceReplayButton.disabled = false;
  voiceReplayButton.textContent = hologramVoice.hasCachedAudio ? '♫ Volver a escuchar' : '♫ Reintentar voz';
  voiceState.textContent = describeVoiceStatus(result);
  voiceWidget.dataset.status = status;
  if (!['completed','cancelled','empty','already-playing'].includes(status)) {
    traceEvent({uiWarning:'remote-tts-'+status});
    console.warn('[mIA HG VOZ] Reproducción remota:',
      {status,http:result?.http,mime:result?.mime,bytes:result?.bytes});
  }
}
async function speakHologram(text, {maxMs} = {}) {
  const message = String(text || '').trim();
  if (!message) return {status:'empty'};
  lastSpokenText = message;
  voiceReplayButton.disabled = true;
  voiceState.textContent = 'Preparando voz de mIA desde el servidor…';
  let result;
  try {
    result = await hologramVoice.speak(message,{
      maxMs:maxMs ?? 90000,
      onStart:()=>{ premiumStage.speaking(true); voiceState.textContent = 'mIA está hablando…'; },
    });
  } catch(error) {
    result = {status:'voice-network-error',errorName:error?.name};
  } finally {
    premiumStage.speaking(false);
  }
  voiceResultUi(result);
  return result;
}
voiceReplayButton.addEventListener('click', async () => {
  // Cached audio: play() runs synchronously in the click's user activation.
  // Otherwise retry the same provider from .env. Never use speechSynthesis.
  if (voiceReplayButton.disabled) return;
  voiceReplayButton.disabled = true;
  voiceState.textContent = 'Reproduciendo voz de mIA…';
  let result;
  try {
    if (hologramVoice.hasCachedAudio) {
      result = await hologramVoice.replay({onStart:()=>premiumStage.speaking(true)});
    } else {
      const sample = lastSpokenText || testVoiceText;
      lastSpokenText = sample;
      result = await hologramVoice.speak(sample,{
        onStart:()=>premiumStage.speaking(true),
      });
    }
  } catch(error) {
    result = {status:'voice-network-error',errorName:error?.name};
  } finally {
    premiumStage.speaking(false);
  }
  voiceResultUi(result);
});
// Con un ventilador holográfico físico no se muestran botones.
// Tecla V en el teclado del operador: probar o volver a escuchar la voz.
if (new URLSearchParams(location.search).get('fan') === '1') {
  voiceWidget.style.display = 'none';
  window.addEventListener('keydown', event => {
    if (event.repeat || event.ctrlKey || event.altKey || event.metaKey) return;
    const key = event.key?.toLowerCase();
    if (key !== 'v' && key !== 'f8') return;
    const target = event.target;
    // F8 funciona incluso con el foco en el cuadro de escritura.
    if (key !== 'f8' && (target?.isContentEditable ||
        /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName || ''))) return;
    event.preventDefault();
    voiceReplayButton.click();
  });
}
// El 2D usa /api/mia/v4/chat (hasta 120s), no el antiguo SSE /api/chat/stream.
// Las consultas de RRHH pueden tardar más de 25s sin emitir nuevos bytes.
// Límite global absoluto: evita esperas infinitas, permitiendo tres rutas.
const QUERY_TIMEOUT_MS = 190000; // 120s gateway + 40s stream + 20s JSON + margen
let activeTurnController = null;
let pageLeaving = false;
const queryStatusEl = document.getElementById('hgQueryStatus');
const cancelQueryEl = document.getElementById('hgCancelQuery');
const diagView = document.getElementById('hgDiagView');
const diagCopyButton = document.getElementById('hgDiagCopy');
const diagnosticsOn = new URLSearchParams(location.search).get('diag') === '1';
const trace = {phase:'ready',event:'-',events:0,http:null,elapsedMs:0,lastError:'-',result:false,requestStarted:false,uiWarning:'-',route:'-',validation:'-',turn:0};
let turnSequence = 0;
if (diagnosticsOn) document.body.classList.add('hg-diagnostics-on');
function traceEvent(update = {}) {
  Object.assign(trace, update);
  if (diagnosticsOn && diagView) {
    diagView.textContent = JSON.stringify(sanitizeHologramTrace(trace),null,2);
  }
}
/** No UI enhancement is permitted to block the actual question. */
function safely(step, operation) {
  try { return operation(); }
  catch (error) {
    // Preserve the real console stack. The on-screen diagnostic only exposes
    // a safe, finite stage identifier; no employee data or message contents.
    console.error('[mIA HG V5.2.9] UI step failed:', step, error);
    traceEvent({uiWarning:step});
    return undefined;
  }
}

diagCopyButton?.addEventListener('click', () => {
  const safe = JSON.stringify(sanitizeHologramTrace(trace),null,2);
  void navigator.clipboard?.writeText(safe);
});
let statusClock = null;
function clearStatusClock() {
  if (statusClock !== null) window.clearInterval(statusClock);
  statusClock = null;
  document.body.classList.remove('hg-query-running');
  if (queryStatusEl) queryStatusEl.textContent = '';
  if (cancelQueryEl) cancelQueryEl.hidden = true;
}
function startStatusClock() {
  const startedAt = performance.now();
  document.body.classList.add('hg-query-running');
  if (cancelQueryEl) cancelQueryEl.hidden = true;
  const redraw = () => {
    const sec = Math.max(0,Math.floor((performance.now()-startedAt)/1000));
    traceEvent({elapsedMs:sec*1000});
    if (queryStatusEl) queryStatusEl.textContent = sec < 12
      ? `Consultando datos · ${sec} s`
      : `Esperando confirmación del servidor · ${sec} s`;
    if (cancelQueryEl && sec >= 12) cancelQueryEl.hidden = false;
  };
  redraw();
  statusClock = window.setInterval(redraw,1000);
}
cancelQueryEl?.addEventListener('click', () => activeTurnController?.abort());
// La salida de ventilador oculta los controles; Esc permite cancelar desde el operador.
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || !activeTurnController) return;
  activeTurnController.abort();
});

let hologramEffect = null;
let director = null;
let busy = false;
const deferredMailNotices = [];
function announceMailBatch(correos, { restored = false } = {}) {
  announceNewMail(correos, {
    restored,
    speak: (text) => { void speakHologram(text); },
    onSummary: (correo) => { void submit(mailPromptQuery(correo, 'summary'), { source: 'typed' }); },
    onDetails: (correo) => { void submit(mailPromptQuery(correo, 'details'), { source: 'typed' }); },
    onDismiss: () => { void speakHologram('De acuerdo, seguimos con lo que estábamos.'); },
  });
}
function flushMailNotices() {
  if (busy || !deferredMailNotices.length) return;
  const notices = deferredMailNotices.splice(0);
  announceMailBatch(notices.flatMap((notice) => notice.correos), {
    restored: notices.every((notice) => notice.restored),
  });
}
let queuedQuestion = null;
let runningQuestion = '';
let reportWatcher = null;
let reportLock = null;
let lastReportRequest = null;
let reportViewNonce = 0;
const normalizedPrompt = (q) => String(q||'').toLowerCase().normalize('NFD')
  .replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').trim();
function abandonReportView() {
  ++reportViewNonce;
  reportWatcher?.abort();
  reportWatcher = null;
}
function renderReportJob(job, question, currentView) {
  if (currentView !== reportViewNonce || pageLeaving) return;
  resultEl.replaceChildren();
  const root = document.createElement('section');
  root.className = 'hg-report-job';
  const title = document.createElement('strong');
  title.textContent = 'Informe solicitado · generación en servidor';
  const state = document.createElement('div');
  state.className = 'hg-report-state';
  state.textContent = getJobStatusLabel(job.status);
  const progress = document.createElement('progress');
  progress.max = 100;
  progress.value = Math.max(0,Math.min(100,Number(job.progress||0)*100));
  const description = document.createElement('p');
  description.textContent = String(job.progress_message || (jobIsActive(job) ?
    'El servidor sigue preparando el documento.' : '')).slice(0,400);
  root.append(title,state,progress,description);
  const download = reportDownloadHref(job);
  if (download) {
    const link = document.createElement('a');
    link.className = 'hg-report-download';
    link.href = download;
    link.download = '';
    link.textContent = '↓ Descargar informe generado';
    root.appendChild(link);
  } else if (job.status === 'failed') {
    const error = document.createElement('p');
    error.textContent = String(job.error_message || 'Consulta el historial de trabajos en 2D.').slice(0,300);
    root.appendChild(error);
  }
  const view2d = document.createElement('a');
  view2d.href = '../../../mia-2d.html';
  view2d.textContent = 'Ver trabajos e historial en 2D ↗';
  root.appendChild(view2d);
  resultEl.appendChild(root);
  safely('job-visible',()=>premiumStage.dataVisible(true,resultEl));
  if (job.status === 'completed') sayCaption('El informe está preparado. Puedes descargarlo desde el panel.', 'answer');
  else if (job.status === 'failed') sayCaption('El servidor no ha podido completar el informe. Consulta su estado en 2D.', 'error');
  else if (job.status === 'cancelled') sayCaption('La generación del informe ha sido cancelada.', 'answer');
  else sayCaption('Informe en preparación. Te mostraré el estado real del servidor.', 'waiting');
}
function startReportTracking(job, question) {
  abandonReportView();
  reportLock = {key:normalizedPrompt(question),jobId:job.job_id,status:job.status,at:Date.now()};
  const currentView = reportViewNonce;
  renderReportJob(job,question,currentView);
  if (!jobIsActive(job)) return;
  const controller = new AbortController();
  reportWatcher = controller;
  void pollHologramJob(job.job_id,{
    signal:controller.signal,
    onUpdate:(nextJob,error)=>{
      if (currentView!==reportViewNonce || controller.signal.aborted) return;
      if (nextJob) {
        reportLock = {...reportLock,status:nextJob.status};
        renderReportJob(nextJob,question,currentView);
      } else if (error?.retry) traceEvent({phase:'job',event:'poll-retry'});
    },
  }).catch((error)=>{
    if (controller.signal.aborted || currentView !== reportViewNonce) return;
    traceEvent({phase:'job',event:'poll-stopped',lastError:String(error?.code||'unknown')});
    if (reportLock) reportLock.status = 'unknown';
    sayCaption('No he podido recuperar el estado del informe. Consúltalo en Trabajos del mundo 2D; no lo crearé otra vez.', 'error');
  }).finally(()=>{
    if (reportWatcher===controller) reportWatcher=null;
  });
}
function appendDirectReportLinks(response) {
  const links = [];
  for (const action of [...(Array.isArray(response?.actions)?response.actions:[]),
    ...(Array.isArray(response?.data?.actions)?response.data.actions:[]),
    ...(Array.isArray(response?.data?.documents)?response.data.documents:[])]) {
    if (!action || typeof action!=='object') continue;
    const url = String(action.url||'');
    if (!/^\/api\/[A-Za-z0-9_/?=&%.\-]+$/.test(url)) continue;
    if (!links.some(x=>x.url===url)) links.push({url,label:String(action.label||action.title||'Descargar informe').slice(0,70)});
  }
  for (const item of links.slice(0,3)) {
    const link = document.createElement('a');
    link.href = item.url; link.download=''; link.className = 'hg-report-download';
    link.textContent = '↓ ' + item.label;
    resultEl.appendChild(link);
  }
  return links.length;
}

let queryPhase = 'ready'; // No permitir que progreso tardío sobrescriba respuestas
let greetingTimer = null;
let welcomeMessage = getWelcomeText();
function scheduleGreetingEnd() {
  window.clearTimeout(greetingTimer);
  const duration = scene.clipDuration('mIA_SEQ_OFRECER_AYUDA') ||
    scene.clipDuration('mIA_WAVE_ALT') || 6;
  greetingTimer = window.setTimeout(() => {
    greetingTimer = null;
    if (!busy && director?.state === 'greeting') director.enter('idle');
    // La onda de voz se apaga con el onEnd REAL, no por duración del clip.
  }, Math.max(1500, duration * 1000 - 650));
}
// El holograma no usa reproducción automática. Una pulsación real al 100 %
// inicia la proyección, la voz pre-descargada y SU animación exclusiva.
const welcomeVoice = new MiaWelcomeVoiceV45({
  apiBase: client.apiBase,
  getAuthHeaders: async () => {
    const token = await getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  },
  onStart: () => premiumStage.speaking(true),
  onEnd: () => {
    premiumStage.speaking(false);
    if (!busy && director?.state === 'greeting') director.enter('idle');
  },
});
const initialWelcomeAudio = welcomeVoice.prepare(welcomeMessage);
let captionEpoch = 0;
let voice = null;
function sayCaption(message, kind = "answer") {
  const epoch = ++captionEpoch;
  caption.textContent = String(message ?? "");
  caption.dataset.kind = kind;
  premiumStage.caption(message, kind);
  caption.classList.remove("is-revealed");
  requestAnimationFrame(() => {
    if (epoch === captionEpoch) caption.classList.add("is-revealed");
  });
}

const waiting = new MiaWaitingV4({
  onUpdate: (message) => sayCaption(message, "waiting"),
  onClear: () => {},
});

// Sin rotación procedural: Mía vuelve a su frontal natural al terminar los gestos.
scene.onFrame = (time) => {
  // Solo el holograma: anima las líneas y el brillo según tiempo real.
  // No añade rotación del personaje (conserva frontalidad de la V5).
  if (scene.model) scene.model.rotation.y = 0;
  hologramEffect?.tick(time);
};

client.addEventListener("avatar", (event) => {
  if (busy) return;
  director?.enterBackendState(event.detail?.state);
  if (!busy) sayCaption(avatarLabel(event.detail?.state));
});
client.addEventListener("progress", (event) => {
  // Durante TTS, presentación o error, NO volver a entrar en thinking.
  if (!busy || queryPhase !== 'querying') return;
  safely('progress-caption', () => waiting.progress(event.detail?.message ?? event.detail?.state ??
      event.detail?.tool ?? "Estamos tramitando tu solicitud."));
  safely('progress-animation', () => director?.progress());
});

/** Cualquier pregunta termina en respuesta visual o error recuperable. */
async function submit(text, {source = 'typed'} = {}) {
  let question = String(text || "").trim();
  if (!question || pageLeaving) return;
  const mailReply = consumeMailPrompt(question);
  if (mailReply?.action === 'dismiss') { await speakHologram('De acuerdo, seguimos con lo que estábamos.'); return; }
  if (mailReply?.action === 'summary' || mailReply?.action === 'details') question = mailPromptQuery(mailReply.correo, mailReply.action);
  if (busy) {
    // Repetición por reconocimiento continuo o segundo clic: no generar DOS PDFs.
    if (normalizedPrompt(question) === normalizedPrompt(runningQuestion)) return;
    // La barra de chat debe aceptar interrupciones durante consulta y voz.
    // Nunca descartar silenciosamente la pregunta recién escrita.
    queuedQuestion = question; // gana la última pregunta, no respuestas antiguas
    safely('supersede-stop-audio', () => hologramVoice.stop());
    safely('supersede-abort-request', () => activeTurnController?.abort());
    safely('supersede-caption', () =>
      sayCaption('He recibido tu nueva pregunta. Actualizando la consulta…', 'waiting'));
    return;
  }
  // El micrófono no puede reenviar por eco una orden que crea documentos.
  if (source === 'voice' && isReportGenerationIntent(question) &&
      lastReportRequest?.key === normalizedPrompt(question) &&
      Date.now() - lastReportRequest.at < 120000) return;
  if (reportLock?.key === normalizedPrompt(question) &&
      (jobIsActive(reportLock) ||
       (source === 'voice' && Date.now()-reportLock.at < 120000))) {
    sayCaption('Ya existe un trabajo para ese informe. Consulta su estado o el historial en 2D.', 'answer');
    return;
  }
  abandonReportView();
  // Un turno nuevo invalida la voz anterior, no la sesión ni las consultas.
  hologramVoice.stop();
  lastSpokenText = '';
  voiceReplayButton.textContent = '♫ Probar voz';
  voiceReplayButton.disabled = false;
  voiceState.textContent = 'La voz se preparará con la respuesta';
  if (isReportGenerationIntent(question)) {
    lastReportRequest = {key:normalizedPrompt(question),at:Date.now()};
  }
  busy = true;
  runningQuestion = question;
  queryPhase = 'querying';
  const requestController = new AbortController();
  activeTurnController = requestController;
  const currentTurn = ++turnSequence;
  traceEvent({phase:'query',event:'starting',events:0,http:null,elapsedMs:0,
    lastError:'-',result:false,requestStarted:false,uiWarning:'-',route:'-',
    validation:'-',turn:currentTurn});
  try {
    // The deadline MUST exist BEFORE any animation/audio/UI setup.
    // V5.2.3 set up the UI outside try; any synchronous exception there
    // left the spinner running forever without calling fetch at all.
    const guarded = createHologramTurnGuard({
      work: () => sendHologramVia2D({
        message: question,
        contextState: hgContext,
        replyIntegrity: hgIntegrity,
        signal: requestController.signal,
        // Sin esto, MIA_AUTH__MODE=entra rechaza con 401 toda consulta del
        // holograma (nunca llegaba a responder nada) — ver auth-gate.js.
        getAuthHeaders: async () => {
          const token = await getAccessToken();
          return token ? { Authorization: `Bearer ${token}` } : {};
        },
        // Mismo flujo que el 2D: LLM -> NDJSON -> JSON.
        // No se realiza ningún corte de 25s por silencio del backend.
        llmTimeoutMs: 120000,
        streamTimeoutMs: 40000,
        fallbackTimeoutMs: 20000,
        onProgress: (progress) => {
          if (currentTurn !== turnSequence || requestController.signal.aborted) return;
          const detail = {
            message: progress?.message || progress?.detail ||
              'Estoy consultando los datos disponibles.',
            state: progress?.state || 'concentrada',
          };
          safely('backend-progress', () => client._handle?.({type:'progress',data:detail}));
        },
        onTrace: (detail) => {
          if (currentTurn !== turnSequence || requestController.signal.aborted) return;
          const streamEvent = detail.phase === 'stream' &&
            !['invalid-ndjson', 'invalid-result'].includes(detail.event);
          traceEvent({
            phase: detail.phase,
            event: detail.event,
            ...(detail.http != null ? {http:detail.http} : {}),
            ...(detail.requestStarted ? {requestStarted:true} : {}),
            ...(detail.result ? {result:true} : {}),
            ...(detail.route ? {route:detail.route} : {}),
            ...(detail.validation ? {validation:detail.validation} : {}),
            events: trace.events + (streamEvent ? 1 : 0),
          });
        },
      }),
      signal: requestController.signal,
      deadlineMs: QUERY_TIMEOUT_MS,
      onDeadline: (reason) => {
        traceEvent({phase:'timeout',event:reason,lastError:reason});
        requestController.abort();
      },
    });
    traceEvent({phase:'query',event:'guard-armed'});

    // Every one of these enhancements is optional. If any throws, the
    // backend still receives the user's request, and the error is logged.
    safely('clock-start', startStatusClock);
    safely('welcome-cancel', () => welcomeVoice.cancel());
    safely('audio-stop', () => hologramVoice.stop());
    // Permitir otra pregunta mientras Mía está hablando; interrumpe el turno viejo.
    safely('button-available', () => { sendButton.disabled = false; });
    safely('microphone-pause', () => voice?.pause());
    safely('result-clear', () => resultEl.replaceChildren());
    safely('result-hidden', () => premiumStage.dataVisible(false, resultEl));
    safely('speaking-off', () => premiumStage.speaking(false));
    safely('waiting-on', () => premiumStage.waiting(true));
    safely('greeting-end', () => {
      window.clearTimeout(greetingTimer);
      greetingTimer = null;
    });
    safely('waiting-start', () => waiting.start());
    safely('thinking-animation', () => director?.enter('thinking', {query:question}));
    safely('waiting-caption', () =>
      sayCaption('Estoy consultando la información. Te daré un resumen en cuanto esté disponible.', 'waiting'));

    const response = await guarded.result;
    safely('world-context-save', () => saveHologramWorldContext(hgContext.value));
    queryPhase = 'presenting'; // Cerrar progreso ANTES de pintar contenido
    traceEvent({phase:'result',event:'result',result:true});
    safely('clock-stop', clearStatusClock);
    safely('waiting-stop', () => waiting.stop());
    safely('waiting-off', () => premiumStage.waiting(false));
    const job = extractHologramJob(response);
    if (job) {
      traceEvent({phase:'job',event:'accepted',result:true,route:trace.route});
      safely('job-start',()=>startReportTracking(job,question));
      safely('job-animation',()=>director?.enter('presenting', {query:question}));
      if (!requestController.signal.aborted) {
        try { await speakHologram('He iniciado el informe. Puedes consultar su progreso y descargarlo cuando esté preparado.'); }
        catch { /* tarjeta visible aunque la locución falle */ }
      }
      return; // el polling sigue por GET y NUNCA vuelve a llamar al LLM
    }
    const rawAnswer = String(response?.answer || response?.speech || '').trim();
    const presentations = Array.isArray(response?.presentations)
      ? response.presentations
      : response?.presentation && typeof response.presentation === 'object'
        ? [response.presentation]
        : Array.isArray(response?.visualizations) ? response.visualizations
        : response && typeof response === 'object' &&
          (response.kpis || response.metrics || response.tables || response.rows || response.charts)
          ? [response] : [];
    const type = presentationType(presentations);
    const withStructuredData = hasPresentationData(presentations);

    let display = {html:'',visible:false,counts:{}};
    try {
      display = adaptHologramResult(response,presentations,{type,fan:premiumStage.fan});
    } catch (renderError) {
      console.warn('[mIA HG V5.2.2] Formato visual no compatible',renderError);
    }
    if (!display.visible && withStructuredData) {
      try {
        const backup = renderHologramBrief(presentations,{type});
        if (backup?.trim()) display = {html:backup,visible:true,counts:{}};
      } catch (renderError) {
        console.warn('[mIA HG V5.2.2] Vista de respaldo no compatible',renderError);
      }
    }

    const executive = hologramExecutiveCopy({
      question,response,presentations,counts:display.counts,
    });
    // Voz resumida, no se leen tablas ni nombres completos en el ventilador.
    const speech = executive.speech;
    const captionText = executive.caption;
    const showData = Boolean(display.visible && display.html?.trim());

    // A rendering failure must not erase the confirmed reply.
    safely('answer-caption', () => sayCaption(captionText, showData ? 'presenting':'answer'));
    safely('answer-html', () => { resultEl.innerHTML = showData ? display.html : ''; });

    // Si el backend devuelve solo una respuesta textual larga, mantenemos
    // texto sustantivo en el escenario y no dejamos un panel vacío.
    if (!showData && premiumStage.fan && rawAnswer) {
      // El título nunca introduce cifras que el backend no haya comunicado.
      const label = document.createElement('div');
      label.className = 'hg-fan-feedback hg-fallback-answer';
      label.textContent = executive.working && !executive.confirmed
        ? 'RESUMEN POR VOZ' : 'RESPUESTA DISPONIBLE';
      resultEl.appendChild(label);
    }
    safely('report-links',()=>appendDirectReportLinks(response));
    safely('answer-data-visible', () =>
      premiumStage.dataVisible(Boolean(resultEl.textContent?.trim()),resultEl));
    safely('answer-animation', () => director?.enter(showData ? 'presenting' : 'speaking',{
      presentationType:type, query:question, answer:captionText,
    }));
    if (import.meta.env.DEV) {
      console.info('[mIA HG V5.2.2] Respuesta presentada',{
        type, metrics:display.counts?.metrics||0,
        rows:display.counts?.rows||0,
        hasDisplay:showData,
        isWorkforceQuery:isWorkingNowQuestion(question),
        hasConfirmedTotal:executive.confirmed,
      });
    }

    // Voz exclusiva del backend y recuperación manual con audio cacheado.
    if (speech && !requestController.signal.aborted) {
      await speakHologram(speech);
    }
    safely('speaking-stop', () => premiumStage.speaking(false));
    safely('idle-animation', () => director?.enter('idle'));
  } catch (error) {
    // Un turno sustituido no debe mostrar errores/cifras anteriores.
    if (pageLeaving || queuedQuestion !== null) return;
    queryPhase = 'terminal';
    safely('clock-error-stop', clearStatusClock);
    safely('waiting-error-stop', () => waiting.stop());
    safely('waiting-error-off', () => premiumStage.waiting(false));
    const code = String(error?.code || 'unknown');
    traceEvent({phase:'error',event:'terminal',lastError:code});
    const cancelled = code === 'cancelled';
    const reportUncertain = code === 'report-state-uncertain';
    const timeout = ['timeout','inactivity','deadline'].includes(code);
    const backendError = code === 'backend-error';
    const missingResult = code === 'missing-result';
    const staleReply = code === 'stale-reply' ||
      code === 'mismatched-echo' || code === 'repeated-previous-answer';
    const message = reportUncertain
      ? 'No puedo confirmar si la generación del informe se ha iniciado. No repetiré la solicitud automáticamente. Revisa Trabajos en el mundo 2D.'
      : cancelled
      ? 'Consulta cancelada. Puedes volver a preguntar cuando quieras.'
      : timeout
        ? 'No he recibido una respuesta confirmada a tiempo. Puedes volver a intentarlo.'
        : staleReply
          ? 'El servidor no ha confirmado una respuesta correspondiente a esta pregunta. No mostraré datos de una consulta anterior.'
        : backendError
          ? 'El servidor ha notificado un error al consultar los datos. Inténtalo de nuevo.'
          : missingResult
            ? 'El servidor ha terminado sin entregar resultados. Inténtalo de nuevo.'
            : 'No he podido obtener los datos ahora mismo. Puedes volver a intentarlo.';
    safely('error-caption', () => sayCaption(message,'error'));
    safely('error-clear', () => resultEl.replaceChildren());
    // Aviso visible: un error no es un KPI ni una respuesta inventada.
    const notice = document.createElement('div');
    notice.className = 'hg-error-visible';
    notice.textContent = reportUncertain ? 'ESTADO DE INFORME SIN CONFIRMAR'
      : cancelled ? 'CONSULTA CANCELADA'
      : timeout ? 'SIN RESPUESTA CONFIRMADA'
      : staleReply ? 'RESPUESTA NO VERIFICADA'
      : backendError ? 'ERROR DEL SERVIDOR'
      : missingResult ? 'SIN DATOS FINALES' : 'CONSULTA NO DISPONIBLE';
    safely('error-append', () => resultEl.append(notice));
    if (reportUncertain) safely('report-history-link',()=>{
      const link=document.createElement('a');link.href='../../../mia-2d.html';
      link.textContent='Ver historial de trabajos en 2D';resultEl.append(link);
    });
    safely('error-visible', () => premiumStage.dataVisible(true,resultEl));
    safely('error-animation', () => director?.enter('error'));
    console.warn('[mIA HG V5.2.9] Consulta finalizada sin resultados',{
      reason:code, timeout, version:'5.2.9',
      // Más información sin datos personales en ?diag=1
    });
    // Error visible primero y locución de fallo con plazo reducido.
    // No rearmar el micrófono continuo mientras Mía sigue hablando.
    if (!cancelled) {
      try {
        await speakHologram(reportUncertain
          ? 'No puedo confirmar el estado del informe. Revisa los trabajos en el mundo dos D.'
          : timeout
          ? 'No he recibido los resultados a tiempo. Puedes volver a intentarlo.'
          : 'No puedo acceder a esa información ahora mismo. Inténtalo de nuevo.');
      } catch { /* La respuesta de error sigue visible */ }
    }
  } finally {
    // Release query ownership FIRST: nobody can retain a permanent busy flag.
    busy = false;
    runningQuestion = '';
    queryPhase = 'ready';
    if (activeTurnController === requestController) activeTurnController = null;
    safely('clock-final', clearStatusClock);
    safely('waiting-final', () => waiting.stop());
    safely('waiting-final-off', () => premiumStage.waiting(false));
    safely('speaking-final-off', () => premiumStage.speaking(false));
    if (queryPhase !== 'presenting' && trace.phase === 'error') {
      safely('terminal-idle', () => director?.enter('idle'));
    }
    safely('button-unlock', () => { sendButton.disabled = false; });
    safely('microphone-resume', () => voice?.resume());
    safely('input-focus', () => { if (voice?.mode !== 'continuous') input.focus(); });
    flushMailNotices();
    if (!pageLeaving && queuedQuestion !== null) {
      const next = queuedQuestion;
      queuedQuestion = null;
      // La petición anterior ya terminó su finally y no puede pintar luego.
      void Promise.resolve().then(() => submit(next));
    }
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
  const sourceClipCount = clips.filter((name) =>
    !['mIA_IDLE_SAFE', 'mIA_SEQ_BIENVENIDA_SAFE'].includes(name)).length;
  if (sourceClipCount !== 84) console.warn(`[mIA HG V5.2] Se esperaban 84 clips originales; cargados ${sourceClipCount}`);
  // V5.2: conservar textura facial (evitar radiografía difusa).
  // No volver a llamar a scene.applyMaterial(hologramMaterial):
  // ese shader eliminaba ojos, boca y sombras naturales de la cara.
  const visualReport = enhanceHologramAvatar(scene, THREE);
  if (!visualReport.textures) {
    console.warn("[mIA HG V5.2] No se detectaron texturas originales del rostro");
  }
  // V5.2: `?fan=1` activa negro absoluto + rostro opaco por defecto.
  // `?avatar=hybrid/classic/natural` permite comparar sin alterar el GLB.
  hologramEffect = installHologramStyle(scene, THREE, window.location.search);
  // Personalidad NUEVA, no se comparte el director del mundo 3D.
  director = new MiaHologramDirectorV52({
    scene,
    onStateChange: (state) => { document.body.dataset.hgMotion = state; },
  });
  // Descargamos audio mientras llegaban los 39 MB del GLB; esperamos un
  // máximo razonable antes de ofrecer la pulsación humana. Si la voz remota
  // falla, la interfaz permite continuar sin sonido (nunca usa voz del navegador).
  let audioTimeoutId;
  const audioStatus = await Promise.race([
    initialWelcomeAudio,
    new Promise((resolve) => {
      audioTimeoutId = window.setTimeout(() => resolve({ status: 'timeout' }), 9000);
    }),
  ]);
  window.clearTimeout(audioTimeoutId);
  if (audioStatus?.status === 'timeout') welcomeVoice.cancel();
  welcomeMessage = getWelcomeText();
  const outcome = await boot.complete({
    onContinue: () => {
      // SIN await, .then ni temporizador antes de replay(): audio.play() se
      // ejecuta en el evento click real y puede obtener autorización de Chrome.
      sayCaption(welcomeMessage, 'welcome');
      director.enter('greeting');
      scheduleGreetingEnd();
      return welcomeVoice.replay(welcomeMessage);
    },
  });
  if (outcome?.status === 'skipped-audio') {
    // El usuario quiere continuar sin sonido, pero sí con bienvenida visual.
    welcomeVoice.cancel();
    sayCaption(welcomeMessage, 'welcome');
    director.enter('greeting');
    scheduleGreetingEnd();
  }
}).catch((error) => {
  boot.fail(error);
  console.error("[mIA V4 HG] Fallo al cargar el modelo", error);
  sayCaption("No se ha podido cargar la proyección de mIA.", "error");
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
    if (text.trim()) void submit(text,{source:'voice'});
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
// La salida LED física oculta los controles visuales. El operador puede
// manejar el micrófono desde el teclado conectado a la máquina mediante M:
// apagado -> una pregunta -> continuo -> apagado. NUNCA se activa solo.
if (new URLSearchParams(location.search).get('fan') === '1') {
  window.addEventListener('keydown', (event) => {
    if (event.key?.toLowerCase() !== 'm' || event.repeat || busy ||
        event.ctrlKey || event.altKey || event.metaKey) return;
    const target = event.target;
    if (target?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName || '')) return;
    event.preventDefault();
    voice?.cycle();
  });
}
window.addEventListener("pagehide", () => {
  pageLeaving = true;
  activeTurnController?.abort();
  abandonReportView();
  saveHologramWorldContext(hgContext.value);
  clearStatusClock();
  hologramVoice.stop();
  boot.dispose();
  window.clearTimeout(greetingTimer);
  waiting.stop();
  client.stopSpeaking();
  welcomeVoice.dispose();
  voice?.destroy();
  director?.destroy();
  premiumStage.speaking(false);
  hologramEffect?.dispose();
});
