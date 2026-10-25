/**
 * mIA — aviso de correo nuevo en el navegador (2D/3D). Mismo diseño que
 * mia-desktop/src/mail-watch.cjs: sondea GET /api/mail/notifications/poll cada pocos minutos; el
 * cursor parte del arranque y nunca notifica de golpe toda la bandeja al cargar la página. Usa la
 * API de notificaciones del navegador (pide permiso una vez) — funciona mientras
 * la pestaña esté abierta, aunque no tenga el foco; a diferencia de mia-desktop, no hay forma de
 * que siga sondeando con la pestaña cerrada, eso es exclusivo de una app que corre en segundo
 * plano de verdad.
 */
import { getAccessToken } from './auth-gate.js';

export const POLL_MS = 60 * 1000; // vuelve a comprobar al menos una vez por minuto

let timer = null;
let startedAt = 0;
let primed = false;
let checking = false;
let seenMail = new Set();
// Huellas ya anunciadas POR VOZ en esta página. Independiente de `seenMail` (que solo evita
// volver a tratar un correo como "nuevo" en el sondeo): este conjunto es la única fuente de verdad
// de si ya se ha hablado un aviso, y lo comprueba `announceNewMail` antes de llamar a `speak`. Así
// da igual cuántas veces o desde qué mundo (2D/3D/Holograma) se invoque `announceNewMail` para el
// mismo correo (sondeo repetido, lote diferido por estar ocupado, etc.): la voz solo suena una vez
// por correo durante la vida de esta pestaña.
let spokenMail = new Set();
let promptNode = null;
let pendingMail = null;
const PENDING_MAIL_KEY = 'mia.pending-mail-prompt.v1';
const STARTUP_CATCHUP_MS = 5 * 60 * 1000;

function readPendingMail() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(PENDING_MAIL_KEY) || 'null');
    if (!saved || Date.now() - Number(saved.savedAt || 0) > 24 * 60 * 60 * 1000) {
      sessionStorage.removeItem(PENDING_MAIL_KEY);
      return null;
    }
    return saved.correo || null;
  } catch (_) { return null; }
}

function savePendingMail(correo) {
  try {
    // Solo se conserva remitente/asunto/fecha en el almacenamiento de esta pestaña; nunca cuerpo,
    // token ni identificador Graph. Permite recuperar el aviso si se recarga o cambia de mundo.
    const { de, asunto, recibido, huella } = correo || {};
    sessionStorage.setItem(PENDING_MAIL_KEY, JSON.stringify({ correo: { de, asunto, recibido, huella }, savedAt: Date.now() }));
  } catch (_) { /* El aviso sigue funcionando en memoria aunque el navegador bloquee sessionStorage. */ }
}

function mailFingerprint(correo) {
  if (correo?.huella) return String(correo.huella);
  return [correo?.recibido || '', correo?.de || '', correo?.asunto || '', correo?.extracto || '']
    .map((part) => String(part).trim().toLocaleLowerCase('es')).join('|');
}

async function authHeaders() {
  try {
    const token = await getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export async function checkOnce(onNewMail) {
  if (checking) return;
  checking = true;
  try {
    const response = await fetch('/api/mail/notifications/poll?limite=10', { headers: await authHeaders() });
    if (!response.ok) { console.warn(`[mIA Mail] El sondeo respondió HTTP ${response.status}; se reintentará.`); return; }
    const data = await response.json();
    const correos = Array.isArray(data?.correos) ? data.correos : [];
    console.info(`[mIA Mail] Sondeo correcto; mensajes recientes=${correos.length}.`);
    const nuevos = [];
    if (!primed) {
      // En el primer sondeo, evita anunciar toda la bandeja, pero conserva los
      // correos que hayan llegado desde que arrancó el monitor aunque la primera
      // petición a Graph haya tardado o fallado.
      for (const correo of correos) {
        const key = mailFingerprint(correo);
        const received = Date.parse(correo?.recibido || '');
        if (received >= startedAt - STARTUP_CATCHUP_MS && !seenMail.has(key)) nuevos.push(correo);
      }
      primed = true;
    } else {
      // La huella opaca de Graph identifica el mensaje; no dependemos de que
      // receivedDateTime sea parseable ni de que dos mensajes tengan fechas distintas.
      for (const correo of correos) {
        const key = mailFingerprint(correo);
        if (!seenMail.has(key)) nuevos.push(correo);
      }
    }
    if (nuevos.length) {
      console.info(`[mIA Mail] Detectados ${nuevos.length} mensaje(s) nuevo(s).`);
      // Si la interfaz falla al presentar el aviso, no marcamos esos mensajes como
      // vistos: el siguiente sondeo podrá reintentarlo.
      await onNewMail(nuevos);
    }
    for (const correo of correos) seenMail.add(mailFingerprint(correo));
    // Graph entrega los más recientes primero. Mantener un conjunto acotado evita duplicados
    // incluso cuando dos mensajes comparten la misma precisión de receivedDateTime.
    if (seenMail.size > 100) seenMail = new Set([...seenMail].slice(-50));
  } catch (error) {
    console.warn('[mIA Mail] No se ha podido comprobar el correo:', error);
  } finally {
    checking = false;
  }
}

export function start(onNewMail) {
  stop();
  // El cursor nace al arrancar, no al primer sondeo correcto: si la primera petición falla y llega
  // un correo antes de la siguiente, ese correo también debe detectarse.
  startedAt = Date.now();
  primed = false;
  seenMail = new Set();
  spokenMail = new Set();
  const restoredMail = readPendingMail();
  if (restoredMail) {
    seenMail.add(mailFingerprint(restoredMail));
    // Recupera el aviso pendiente al volver a la página, sin crear una nueva alerta del sistema.
    window.setTimeout(() => onNewMail?.([restoredMail], { restored: true }), 0);
  }
  const first = checkOnce(onNewMail);
  timer = window.setInterval(() => checkOnce(onNewMail), POLL_MS);
  const onVisible = () => {
    if (document.visibilityState === 'visible') void checkOnce(onNewMail);
  };
  document.addEventListener('visibilitychange', onVisible);
  window.addEventListener('focus', onVisible);
  stop.removeListeners = () => {
    document.removeEventListener('visibilitychange', onVisible);
    window.removeEventListener('focus', onVisible);
  };
  return first;
}

export function stop() {
  if (timer) {
    window.clearInterval(timer);
    timer = null;
  }
  stop.removeListeners?.();
  stop.removeListeners = null;
}

/** Pide permiso de notificaciones si todavía no se ha concedido ni denegado. */
export async function ensureNotificationPermission() {
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  try {
    return (await Notification.requestPermission()) === 'granted';
  } catch {
    return false;
  }
}

/** `correo` trae los campos de `correos_sin_leer`: de, asunto, recibido, extracto... */
export function showNotification(correo, onClick) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  const n = new Notification(`Correo nuevo de ${correo.de || 'remitente desconocido'}`, {
    body: correo.asunto || '(sin asunto)',
  });
  if (typeof onClick === 'function') n.onclick = () => { window.focus(); onClick(correo); };
}

/** «con un adjunto: informe.pdf (PDF)» / «con 2 adjuntos: a.pdf (PDF), b.docx (Word)» / '' si no hay. */
function attachmentsPhrase(correo) {
  const items = Array.isArray(correo?.adjuntos_detalle) ? correo.adjuntos_detalle : [];
  if (!items.length) return '';
  const list = items.map((a) => `${a?.nombre || 'adjunto'}${a?.tipo ? ` (${a.tipo})` : ''}`).join(', ');
  return items.length > 1 ? `con ${items.length} adjuntos: ${list}` : `con un adjunto: ${list}`;
}

function clearMailPrompt() {
  if (promptNode?.parentNode) promptNode.parentNode.removeChild(promptNode);
  promptNode = null;
  pendingMail = null;
  try { sessionStorage.removeItem(PENDING_MAIL_KEY); } catch (_) { /* Ignorar almacenamiento no disponible. */ }
}

/** Aviso recuperable de correo: no crea un turno hasta que la persona elige una acción. */
export function promptForMail(correo, { onSummary, onDetails, onDismiss } = {}) {
  clearMailPrompt();
  if (!document?.body) return;
  pendingMail = correo;
  savePendingMail(correo);
  const box = document.createElement('section');
  box.setAttribute('role', 'alertdialog');
  box.setAttribute('aria-label', 'Correo nuevo');
  box.style.cssText = 'position:fixed;right:18px;top:18px;z-index:12000;width:min(390px,calc(100vw - 36px));padding:16px;border:1px solid rgba(23,32,68,.14);border-radius:18px;background:#fff;box-shadow:0 18px 55px rgba(23,32,68,.22);font:14px/1.45 Arial,Helvetica,sans-serif;color:#172044';
  const sender = String(correo?.de || 'remitente desconocido');
  const subject = String(correo?.asunto || '(sin asunto)');
  const title = document.createElement('strong'); title.textContent = `Correo nuevo · ${sender}`;
  const attachments = attachmentsPhrase(correo);
  const body = document.createElement('div'); body.textContent = `${subject}${attachments ? `\n${attachments}` : ''}\n¿Quieres un resumen, ver el detalle o seguir con lo que estabas haciendo?`;
  body.style.cssText = 'margin-top:6px;white-space:pre-line;overflow-wrap:anywhere;color:#526579';
  const actions = document.createElement('div'); actions.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:12px';
  const add = (label, callback, primary = false) => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.style.cssText = `border:1px solid ${primary ? '#172044' : '#dce1e8'};border-radius:999px;padding:8px 12px;background:${primary ? '#172044' : '#fff'};color:${primary ? '#fff' : '#172044'};font:600 12px Arial,Helvetica,sans-serif;cursor:pointer`;
    button.addEventListener('click', () => { clearMailPrompt(); callback?.(correo); }); actions.appendChild(button);
  };
  add('Resumir correo', onSummary, true); add('Ver detalle', onDetails); add('Ahora no', onDismiss);
  box.append(title, body, actions); document.body.appendChild(box); promptNode = box;
}

/** Devuelve una intención de la respuesta hablada/escrita y retira el aviso pendiente. */
export function consumeMailPrompt(text) {
  if (!pendingMail || !String(text || '').trim()) return null;
  const value = String(text).toLocaleLowerCase('es').normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  let action = 'other';
  if (/\b(no|ahora no|luego|continua|continuemos|sigamos|dejalo)\b/.test(value)) action = 'dismiss';
  else if (/\b(detalle|muestr|mostrar|abre|abrir|ver correo)\b/.test(value)) action = 'details';
  else if (/\b(resum|resumen|cuentame|que dice|contenido)\b/.test(value)) action = 'summary';
  if (action === 'other') return { action, correo: pendingMail };
  const correo = pendingMail;
  clearMailPrompt();
  return { action, correo };
}

export function mailPromptQuery(correo, action) {
  const sender = String(correo?.de || 'el remitente del correo');
  const subject = String(correo?.asunto || 'sin asunto');
  const target = `remitente «${sender}» y asunto «${subject}»`;
  const lookup = `Busca primero ese mensaje en mi buzón con correos_recientes (límite 10, incluir_texto=true), identifica la coincidencia exacta por remitente y asunto y después lee el correo usando la referencia que devuelva esa búsqueda. No llames a leer_correo hasta tener esa referencia; el remitente y el asunto no son referencias.`;
  return action === 'details'
    ? `Quiero ver el detalle y escuchar un resumen del correo nuevo con ${target}. ${lookup}`
    : `Resúmeme con detalle el contenido del correo nuevo con ${target}. ${lookup}`;
}

/** Notificación común para los mundos web; clic en la notificación del sistema abre el detalle. */
export function announceNewMail(correos, { speak, onSummary, onDetails, onDismiss, restored = false } = {}) {
  const items = Array.isArray(correos) ? correos : [];
  if (!items.length) return;
  const correo = items[0];
  const attachments = attachmentsPhrase(correo);
  const announcement = `${items.length > 1 ? 'Han llegado correos nuevos' : 'Ha llegado un correo nuevo'}${attachments ? `, ${attachments}` : ''}. ¿Quieres que te resuma el contenido, que te muestre el detalle o seguimos con lo que estábamos?`;
  // El globo dentro de mIA es prioritario. Un fallo/permisos de Notification o de voz
  // nunca debe impedir que la persona vea y pueda atender el aviso.
  try { promptForMail(correo, { onSummary, onDetails, onDismiss }); }
  catch (error) { console.error('[mIA Mail] No se pudo pintar el globo del correo:', error); }
  if (!restored) {
    items.forEach((item) => {
      try { showNotification(item, () => onDetails?.(item)); }
      catch (error) { console.warn('[mIA Mail] Notificación del navegador no disponible:', error); }
    });
  }
  // La voz solo debe sonar la primera vez que se detecta un correo:
  //  - `restored` es true cuando este mismo aviso ya se anunció en una página anterior (recuperado
  //    de sessionStorage al recargar o cambiar de mundo sin haberlo atendido todavía) — hablar aquí
  //    de nuevo lo duplicaría cada vez que la persona cambia de mundo con un aviso pendiente.
  //  - `spokenMail` cubre el resto de los casos SIN recarga ni cambio de mundo: algunos mundos
  //    (3D/Holograma, ver flushMailNotices en 3d/main.js y hologram/main.js) encolan el aviso
  //    mientras mIA está ocupada y lo vuelven a pasar por `announceNewMail` al vaciar la cola; un
  //    sondeo que se reintente tras un fallo de UI también volvería a llamar aquí para el mismo
  //    correo. `spokenMail` es la única fuente de verdad de "ya se ha hablado este correo" en esta
  //    pestaña y se consulta en el único punto por el que pasa cualquier llamada a `speak`, así que
  //    da igual cuántas veces o desde qué ruta se invoque `announceNewMail`: la voz suena una vez.
  const key = mailFingerprint(correo);
  if (!restored && !spokenMail.has(key)) {
    spokenMail.add(key);
    try { speak?.(announcement); }
    catch (error) { console.warn('[mIA Mail] No se pudo anunciar el correo con voz:', error); }
  } else if (!restored) {
    console.info('[mIA Mail] Aviso de voz omitido: este correo ya se anunció en esta página.');
  }
}

// El mundo 2D en producción (mia-2d.js) es un script clásico (sin type="module"): no puede hacer
// `import` de este módulo. Se expone aquí igual que window.miaGetAccessToken en auth-gate.js, por
// si algún día hace falta desde ahí; hoy el arranque vive en mia-entry-v530.js (sí es módulo).
if (typeof window !== 'undefined') {
  window.miaMailWatch = { start, stop, checkOnce, ensureNotificationPermission, showNotification, promptForMail, consumeMailPrompt, mailPromptQuery };
}
