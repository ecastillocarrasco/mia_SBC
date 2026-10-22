/**
 * mIA — aviso de correo nuevo en el navegador (2D/3D). Mismo diseño que
 * mia-desktop/src/mail-watch.cjs: sondea GET /api/mail/unread cada pocos minutos; la primera
 * pasada solo fija el punto de partida (nunca notifica de golpe toda la bandeja al cargar la
 * página). Usa la API de notificaciones del navegador (pide permiso una vez) — funciona mientras
 * la pestaña esté abierta, aunque no tenga el foco; a diferencia de mia-desktop, no hay forma de
 * que siga sondeando con la pestaña cerrada, eso es exclusivo de una app que corre en segundo
 * plano de verdad.
 */
import { getAccessToken } from './auth-gate.js';

export const POLL_MS = 3 * 60 * 1000; // igual que mia-desktop: cada 3 minutos

let timer = null;
let lastSeenAt = null; // ISO de receivedDateTime del correo más reciente ya visto

async function authHeaders() {
  try {
    const token = await getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export async function checkOnce(onNewMail) {
  try {
    const response = await fetch('/api/mail/unread?limite=10', { headers: await authHeaders() });
    if (!response.ok) return; // sin permiso, backend no disponible, o modo dev sin buzón: se reintenta solo
    const data = await response.json();
    const correos = Array.isArray(data?.correos) ? data.correos : [];
    if (!correos.length) return;
    const previousSeen = lastSeenAt;
    const top = correos[0]?.recibido;
    if (top && (!lastSeenAt || new Date(top) > new Date(lastSeenAt))) lastSeenAt = top;
    if (!previousSeen) return; // primera pasada: solo fija el punto de partida
    const nuevos = correos.filter((c) => c.recibido && new Date(c.recibido) > new Date(previousSeen));
    if (nuevos.length) onNewMail(nuevos);
  } catch (error) {
    console.warn('[mIA Mail] No se ha podido comprobar el correo:', error);
  }
}

export function start(onNewMail) {
  stop();
  lastSeenAt = null;
  const first = checkOnce(onNewMail);
  timer = window.setInterval(() => checkOnce(onNewMail), POLL_MS);
  return first;
}

export function stop() {
  if (timer) {
    window.clearInterval(timer);
    timer = null;
  }
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

// El mundo 2D en producción (mia-2d.js) es un script clásico (sin type="module"): no puede hacer
// `import` de este módulo. Se expone aquí igual que window.miaGetAccessToken en auth-gate.js, por
// si algún día hace falta desde ahí; hoy el arranque vive en mia-entry-v530.js (sí es módulo).
if (typeof window !== 'undefined') {
  window.miaMailWatch = { start, stop, checkOnce, ensureNotificationPermission, showNotification };
}
