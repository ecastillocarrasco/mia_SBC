/**
 * mIA SBC: world 2D now inherits the SAME V4.3 loading screen the 3D
 * world used before the logo-assembly redesign. No second HTML template.
 * DOM readiness + actual image load/error events drive the progress.
 */
import { MiaBootLoader } from '../../core/boot-loader-v43.js';
import { ensureAuthenticated, ensureAuthorized, getAccessToken, mountSignOutButton } from '../../core/auth-gate.js';
import { start as startMailWatch, ensureNotificationPermission, announceNewMail, mailPromptQuery } from '../../core/mail-watch.js';
import { getWelcomeText } from '../../core/identity-v45.js';
import { MiaWelcomeVoiceV45 } from '../../core/welcome-voice-v45.js';
import { MiaWelcomeAutostartV47 } from '../../core/welcome-autostart-v47.js';
import './mia-entry-v530.css';

// El saludo hablado, con el nombre real del usuario y la voz configurada en el backend
// (antes el 2D solo pintaba un saludo genérico de texto, sin voz ni nombre — a diferencia
// de 3D/Holograma). mia-2d.js (script clásico) ya pintó #greetingEyebrow/#welcomeGreeting
// con el saludo por franja horaria antes de que este módulo (diferido) llegue aquí; lo
// sustituimos por el personalizado una vez confirmados login y acceso.
function playPersonalized2DWelcome() {
  const text = getWelcomeText();
  const eyebrow = document.getElementById('greetingEyebrow');
  const welcome = document.getElementById('welcomeGreeting');
  if (welcome) welcome.textContent = text;
  if (eyebrow) eyebrow.textContent = 'MÍA';
  const voice = new MiaWelcomeVoiceV45({
    getAuthHeaders: async () => {
      const token = await getAccessToken();
      return token ? { Authorization: `Bearer ${token}` } : {};
    },
  });
  const autostart = new MiaWelcomeAutostartV47({ voice, canSpeak: () => !document.hidden });
  void autostart.start(text);
}

export function install2DEntry({ root = document.body } = {}) {
  if (!root || document.getElementById('mia2DEntry')) return null;
  const previousFocus = document.activeElement;
  const previousOverflow = document.documentElement.style.overflow;
  const boot = new MiaBootLoader({ mode: '2d', root });
  boot.node.id = 'mia2DEntry';
  boot.node.setAttribute('role', 'dialog');
  boot.node.setAttribute('aria-modal', 'true');
  boot.node.setAttribute('aria-label', 'Bienvenida a mIA, universo 2D');
  document.documentElement.style.overflow = 'hidden';

  // Hand the first frame from the synchronous paint guard to the actual
  // boot DOM. Never reveal the 2D world before the loading screen exists.
  const releaseGuard = () => {
    document.documentElement.classList.remove('mia2d-entry-loading');
    if (window.__mia2dEntryGuardTimeout) {
      clearTimeout(window.__mia2dEntryGuardTimeout);
      window.__mia2dEntryGuardTimeout = null;
    }
  };
  requestAnimationFrame(() => requestAnimationFrame(releaseGuard));

  const keepFocus = (event) => {
    if (event.key !== 'Tab' || !boot.active) return;
    event.preventDefault();
    if (!boot.continueEl.hidden && !boot.actionsEl.hidden) boot.continueEl.focus({ preventScroll:true });
  };
  document.addEventListener('keydown', keepFocus, true);

  const done = async () => {
    // The page's classic scripts have already been executed before
    // DOMContentLoaded. Important images are tracked by real load events.
    const ids = ['avatarA','avatarB'];
    const targets = [
      ...ids.map(id => document.getElementById(id)),
      document.querySelector('.field-a-logo'),
      document.querySelector('.mini-avatar'),
    ].filter(img => img?.tagName === 'IMG');
    let settled = 1; // The 2D DOM and classic scripts are already available.
    const total = 1 + targets.length;
    const update = () => boot.progress(Math.min(.99, settled / total), { phase:'2d' });
    update();
    await Promise.all(targets.map(img => new Promise(resolve => {
      let finished = false;
      let watchdog = null;
      const settle = (ok) => {
        if (finished) return;
        finished = true;
        img.removeEventListener('load', onLoad);
        img.removeEventListener('error', onError);
        window.clearTimeout(watchdog);
        if (!ok) console.warn('[mIA 2D] Recurso visual no disponible:', img.currentSrc || img.src);
        settled++;
        update();
        resolve();
      };
      const onLoad = () => settle(true);
      const onError = () => settle(false);
      if (img.complete) { settle(img.naturalWidth > 0); return; }
      img.addEventListener('load', onLoad, {once:true});
      img.addEventListener('error', onError, {once:true});
      // An optional 2D image must not block entry forever.
      watchdog = window.setTimeout(() => settle(false), 7500);
    })));
    if (!boot.active) return;
    const result = await boot.complete({ onContinue: () => ({ status:'entered-2d' }) });
    document.removeEventListener('keydown', keepFocus, true);
    document.documentElement.style.overflow = previousOverflow;
    const input = document.getElementById('input') || previousFocus;
    if (result && result.status !== 'disposed') input?.focus?.({ preventScroll:true });
  };
  void done().catch(error => {
    console.error('[mIA 2D] Error al preparar la entrada:', error);
    boot.fail(error);
  });
  return { close: () => { // Only used by explicit code, never a simulated user click.
    document.removeEventListener('keydown', keepFocus, true);
    document.documentElement.style.overflow = previousOverflow;
    boot.dispose();
    releaseGuard();
  }};
}

if (typeof document !== 'undefined') {
  // Si MIA_AUTH__MODE=entra exige login y no hay sesión, `interactive: false` vuelve al portal
  // (el único punto con login real — ver auth-gate.js) en vez de iniciar aquí su propio redirect
  // a Microsoft: el mundo 2D (boot loader, avatar, chat…) nunca llega a montarse en ese caso —
  // ni siquiera si alguien navega directo a mia-2d.html sin pasar por el portal.
  await ensureAuthenticated({ interactive: false });
  // Igual que el login: si la cuenta no tiene ningún permiso, esto sustituye la página entera
  // (levantando la misma cortina de pintura) y nunca resuelve — install2DEntry() nunca se llama.
  await ensureAuthorized();
  mountSignOutButton('#miaSignOut');
  playPersonalized2DWelcome();
  // El permiso controla la notificación del navegador, no el sondeo ni el aviso de voz.
  void ensureNotificationPermission();
  startMailWatch((correos, { restored = false } = {}) => announceNewMail(correos, {
    restored,
    speak: (text) => window.miaSpeakMailNotification?.(text),
    onSummary: (correo) => window.ask?.(mailPromptQuery(correo, 'summary')),
    onDetails: (correo) => { window.miaAutoOpenNextMail = true; window.ask?.(mailPromptQuery(correo, 'details')); },
    onDismiss: () => window.miaSpeakMailNotification?.('De acuerdo, seguimos con lo que estábamos.'),
  }));
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => install2DEntry(), {once:true});
  } else install2DEntry();
}
