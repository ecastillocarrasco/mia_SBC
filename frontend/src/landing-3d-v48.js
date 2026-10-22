import world3dMarkup from './worlds/3d/index.html?raw';
import { installInlineWorldEntry } from './core/landing-world-entry-v48.js';
import { ensureAuthenticated, ensureAuthorized, dismissEntryGuard, mountSignOutButton } from './core/auth-gate.js';

// Si MIA_AUTH__MODE=entra exige login y no hay sesión, esto redirige a Microsoft y nunca
// resuelve: nada de lo que sigue (ni los enlaces del portal) llega a ejecutarse en ese caso. La
// cortina de pintura del <head> mantiene los enlaces del portal ocultos y sin clic posible
// mientras tanto — si no, son HTML estático ya clicable antes de que este script (diferido por
// type="module") llegue siquiera a correr.
await ensureAuthenticated();
// Login correcto no es lo mismo que tener acceso: si la cuenta no tiene ningún permiso asignado,
// esto sustituye la página entera por el aviso correspondiente y tampoco resuelve nunca.
await ensureAuthorized();
// Login y autorización correctos: ya es seguro revelar el portal real y, si hay una sesión real
// que cerrar (modo entra), el botón de cerrar sesión.
dismissEntryGuard();
mountSignOutButton('#miaSignOut');

const link = document.querySelector('a.world-card.world-3d');
if (link) installInlineWorldEntry({
  link,
  markup: world3dMarkup,
  loadStyles: async () => {
    // Vite empaqueta estas CSS tanto en dev como en produccion (/mia/).
    await import('./worlds/3d/style.css');
    await import('./worlds/3d/v4-white.css');
  },
  loadApp: () => import('./worlds/3d/main.js'),
});

// Volver mediante el historial del navegador: restaurar la portada real.
// No interceptar enlaces del 2D ni del holograma.
window.addEventListener('popstate', () => {
  if (document.body.dataset.miaInlineEntry === '3d') window.location.reload();
});
