'use strict';
// Sondeo periodico de correo sin leer, para avisar con una notificacion nativa de Windows cuando
// llega uno nuevo (pedido explicito del usuario). No existia nada proactivo en mia-desktop antes
// de esto: ni sondeo en segundo plano, ni notificaciones nativas (Electron las trae, pero no se
// usaban para nada).
//
// Llama a GET /api/mail/unread (mia.api.routes.mail.mail_unread), que invoca la herramienta
// correos_sin_leer directamente sobre el registro de herramientas -- sin pasar por el LLM, barato
// y determinista, pensado justo para preguntarse cada pocos minutos.
const { Notification } = require('electron');
const auth = require('./auth.cjs');

const POLL_MS = 3 * 60 * 1000; // cada 3 minutos (elegido por el usuario)

let timer = null;
let lastSeenAt = null; // ISO de receivedDateTime del correo mas reciente ya visto

async function authHeaders() {
  try {
    const token = await auth.getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function checkOnce(base, onNewMail) {
  try {
    const response = await fetch(`${base}/api/mail/unread?limite=10`, { headers: await authHeaders() });
    if (!response.ok) return; // backend no disponible, sin permiso, o modo dev sin buzon: se reintenta solo
    const data = await response.json();
    const correos = Array.isArray(data?.correos) ? data.correos : [];
    if (!correos.length) return;
    // correos_sin_leer pide $orderby=receivedDateTime desc: el primero es el mas reciente.
    const previousSeen = lastSeenAt;
    const top = correos[0]?.recibido;
    if (top && (!lastSeenAt || new Date(top) > new Date(lastSeenAt))) lastSeenAt = top;
    // En la PRIMERA pasada solo se fija el punto de partida: nunca se notifica de golpe toda la
    // bandeja al abrir la app, solo lo que llegue despues.
    if (!previousSeen) return;
    const nuevos = correos.filter(c => c.recibido && new Date(c.recibido) > new Date(previousSeen));
    if (nuevos.length) onNewMail(nuevos);
  } catch (e) {
    console.warn('[mIA Mail] No se ha podido comprobar el correo:', e);
  }
}

/** Arranca el sondeo. `onNewMail(correos)` se llama con los correos nuevos desde la comprobacion
 * anterior (nunca en la primera pasada). Seguro de llamar varias veces: reinicia el temporizador. */
function start(base, onNewMail) {
  stop();
  lastSeenAt = null;
  const first = checkOnce(base, onNewMail);
  timer = setInterval(() => checkOnce(base, onNewMail), POLL_MS);
  return first;
}

function stop() {
  if (timer) { clearInterval(timer); timer = null; }
}

/** `correo` trae los campos de `correos_sin_leer`: de, asunto, recibido, extracto... */
function showNotification(correo, onClick) {
  if (!Notification.isSupported()) return;
  const n = new Notification({
    title: `Correo nuevo de ${correo.de || 'remitente desconocido'}`,
    body: correo.asunto || '(sin asunto)',
  });
  if (typeof onClick === 'function') n.on('click', () => onClick(correo));
  n.show();
}

module.exports = { start, stop, checkOnce, showNotification, POLL_MS };
