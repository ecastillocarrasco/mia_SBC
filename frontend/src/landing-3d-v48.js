import world3dMarkup from './worlds/3d/index.html?raw';
import { installInlineWorldEntry } from './core/landing-world-entry-v48.js';
import { ensureAuthenticated, ensureAuthorized } from './core/auth-gate.js';

// Si MIA_AUTH__MODE=entra exige login y no hay sesión, esto redirige a Microsoft y nunca
// resuelve: nada de lo que sigue (ni los enlaces del portal) llega a ejecutarse en ese caso.
await ensureAuthenticated();
// Login correcto no es lo mismo que tener acceso: si la cuenta no tiene ningún permiso asignado,
// esto sustituye la página entera por el aviso correspondiente y tampoco resuelve nunca.
await ensureAuthorized();

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
