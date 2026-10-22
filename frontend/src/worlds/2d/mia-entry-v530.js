/**
 * mIA SBC: world 2D now inherits the SAME V4.3 loading screen the 3D
 * world used before the logo-assembly redesign. No second HTML template.
 * DOM readiness + actual image load/error events drive the progress.
 */
import { MiaBootLoader } from '../../core/boot-loader-v43.js';
import { ensureAuthenticated, ensureAuthorized, mountSignOutButton } from '../../core/auth-gate.js';
import { start as startMailWatch, ensureNotificationPermission, showNotification } from '../../core/mail-watch.js';
import './mia-entry-v530.css';

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
  // Aviso de correo nuevo (pedido del usuario, igual que mia-desktop): notificación del navegador
  // con un clic que deja la pregunta de resumen ya escrita en el composer, lista para confirmar.
  ensureNotificationPermission().then((granted) => {
    if (!granted) return;
    startMailWatch((correos) => {
      for (const correo of correos) {
        showNotification(correo, (c) => {
          const input = document.getElementById('input');
          if (!input) return;
          input.value = `Resúmeme el correo de ${c.de} sobre "${c.asunto}"`;
          input.focus();
        });
      }
    });
  });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => install2DEntry(), {once:true});
  } else install2DEntry();
}
