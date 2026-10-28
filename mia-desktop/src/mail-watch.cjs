'use strict';
// Sondeo periodico de mensajes recientes de la bandeja, para avisar con una notificacion nativa cuando
// llega uno nuevo (pedido explicito del usuario). No existia nada proactivo en mia-desktop antes
// de esto: ni sondeo en segundo plano, ni notificaciones nativas (Electron las trae, pero no se
// usaban para nada).
//
// Llama a GET /api/mail/unread (mia.api.routes.mail.mail_unread), que invoca la herramienta
// correos_sin_leer directamente sobre el registro de herramientas -- sin pasar por el LLM, barato
// y determinista, pensado justo para preguntarse cada pocos minutos.
const { Notification } = require('electron');
const auth = require('./auth.cjs');
const { withInsecureTls } = require('./insecure-tls.cjs');

const POLL_MS = 60 * 1000; // mantener el aviso al día también en segundo plano
const STARTUP_CATCHUP_MS = 5 * 60 * 1000;

let timer = null;
let primed = false;
let startedAt = 0;
let checking = false;
let seenMail = new Set();

function mailFingerprint(c) {
  if (c?.huella) return String(c.huella);
  return [c?.recibido || '', c?.de || '', c?.asunto || '', c?.extracto || '']
    .map(part => String(part).trim().toLocaleLowerCase('es')).join('|');
}

async function authHeaders() {
  try {
    const token = await auth.getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function checkOnce(base, onNewMail) {
  if (checking) return;
  checking = true;
  try {
    const response = await withInsecureTls(async () => fetch(`${base}/api/mail/notifications/poll?limite=10`, { headers: await authHeaders() }));
    if (!response.ok) { console.warn(`[mIA Mail] El sondeo respondio HTTP ${response.status}; se reintentara.`); return; }
    const data = await response.json();
    const correos = Array.isArray(data?.correos) ? data.correos : [];
    console.info(`[mIA Mail] Sondeo correcto; mensajes recientes=${correos.length}.`);
    const nuevos = [];
    if (!primed) {
      // El primer sondeo establece la bandeja conocida, pero conserva los mensajes
      // recibidos desde el arranque aunque Graph haya tardado o la primera petición fallara.
      for (const correo of correos) {
        const key = mailFingerprint(correo);
        const received = Date.parse(correo?.recibido || '');
        if (received >= startedAt - STARTUP_CATCHUP_MS && !seenMail.has(key)) nuevos.push(correo);
      }
      primed = true;
    } else {
      // Evita depender de receivedDateTime para detectar un mensaje que Graph acaba de mostrar.
      for (const correo of correos) {
        const key = mailFingerprint(correo);
        if (!seenMail.has(key)) nuevos.push(correo);
      }
    }
    if (nuevos.length) {
      console.info(`[mIA Mail] Detectados ${nuevos.length} mensaje(s) nuevo(s).`);
      await onNewMail(nuevos);
    }
    for (const correo of correos) seenMail.add(mailFingerprint(correo));
    if (seenMail.size > 100) seenMail = new Set([...seenMail].slice(-50));
  } catch (e) {
    console.warn('[mIA Mail] No se ha podido comprobar el correo:', e);
  } finally {
    checking = false;
  }
}

/** Arranca el sondeo. `onNewMail(correos)` se llama con los correos nuevos desde la comprobacion
 * anterior (nunca en la primera pasada). Seguro de llamar varias veces: reinicia el temporizador. */
function start(base, onNewMail) {
  stop();
  // Si el primer HTTP falla, conserva el punto de arranque para detectar mensajes que lleguen
  // antes del siguiente sondeo correcto. Se deja un margen corto por desviación de reloj.
  startedAt = Date.now();
  primed = false;
  seenMail = new Set();
  const first = checkOnce(base, onNewMail);
  timer = setInterval(() => checkOnce(base, onNewMail), POLL_MS);
  return first;
}

function stop() {
  if (timer) { clearInterval(timer); timer = null; }
}

/** `correo` trae los campos de `correos_sin_leer`: de, asunto, recibido, extracto... */
function showNotification(correo, onClick) {
  try {
    if (!Notification.isSupported()) return;
    const n = new Notification({
      title: `Correo nuevo de ${correo.de || 'remitente desconocido'}`,
      body: correo.asunto || '(sin asunto)',
    });
    if (typeof onClick === 'function') n.on('click', () => onClick(correo));
    n.show();
  } catch (error) {
    // Un toast de Windows no debe impedir que el aviso integrado en mIA aparezca.
    console.warn('[mIA Mail] Notificación de Windows no disponible:', error?.message || error);
  }
}

module.exports = { start, stop, checkOnce, showNotification, POLL_MS };
