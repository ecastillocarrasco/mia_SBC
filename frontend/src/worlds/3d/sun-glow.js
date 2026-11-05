/**
 * mIA 3D - resplandor de sol muy sutil al responder, para evocar Sunset Beach
 * Club sin saturar la escena. Aparece solo en algunas respuestas (nunca
 * todas) y con un tiempo mínimo entre apariciones.
 */
import './sun-glow.css';

const CHANCE = 0.4;
const COOLDOWN_MS = 25000;
const VISIBLE_MS = 3400;

export function installSunGlow({ root = document.body, reducedMotion = false } = {}) {
  const node = document.createElement('div');
  node.className = 'mia-sun-glow';
  node.setAttribute('aria-hidden', 'true');
  root.appendChild(node);
  let lastShownAt = -Infinity;
  let hideTimer = null;

  function pulseNow() {
    window.clearTimeout(hideTimer);
    node.classList.add('is-active');
    hideTimer = window.setTimeout(() => node.classList.remove('is-active'), VISIBLE_MS);
  }

  /** Llamar cuando mIA empieza a responder. No siempre produce el resplandor. */
  function maybePulse() {
    if (reducedMotion) return;
    const now = Date.now();
    if (now - lastShownAt < COOLDOWN_MS) return;
    if (Math.random() > CHANCE) return;
    lastShownAt = now;
    pulseNow();
  }

  function dispose() {
    window.clearTimeout(hideTimer);
    node.remove();
  }

  return { maybePulse, dispose };
}
