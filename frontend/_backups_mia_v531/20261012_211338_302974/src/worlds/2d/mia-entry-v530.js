/** Pantalla de entrada para el mundo 2D SBC; NO simula ni sustituye autenticacion. */
import './mia-entry-v530.css';

export function install2DEntry({ root = document.body } = {}) {
  if (!root || document.getElementById('mia2DEntry')) return null;
  const overlay = document.createElement('div');
  overlay.id = 'mia2DEntry';
  overlay.className = 'mia2d-entry';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'mia2dEntryTitle');
  overlay.innerHTML = `
    <div class="mia2d-entry__glow" aria-hidden="true"></div>
    <div class="mia2d-entry__wrap">
      <section class="mia2d-entry__content">
        <div class="mia2d-entry__identity"><span class="mia2d-entry__symbol">✦</span>
          <span>mIA <small>· SUNSET BEACH CLUB</small></span></div>
        <p class="mia2d-entry__eyebrow">ACCESO AL UNIVERSO 2D</p>
        <h1 id="mia2dEntryTitle">La inteligencia empieza<br>con una <em>pregunta.</em></h1>
        <p class="mia2d-entry__lead">Tu espacio de conversación, análisis e informes con mIA.
        Información clara, resultados visuales y decisiones mejor fundamentadas.</p>
        <div class="mia2d-entry__features"><span>● Conversación</span><span>● Datos y KPIs</span><span>● Informes</span></div>
        <button type="button" id="mia2dEntryContinue" class="mia2d-entry__button">Comenzar experiencia <span aria-hidden="true">→</span></button>
        <p class="mia2d-entry__note">Mundo 2D Focus · Una misma mIA, una nueva forma de explorar.</p>
      </section>
      <div class="mia2d-entry__portrait" aria-hidden="true">
        <div class="mia2d-entry__halo"></div>
        <img src="/mia-assets/avatar/sonriendo.png" alt="" />
        <span class="mia2d-entry__orbit mia2d-entry__orbit--a"></span><span class="mia2d-entry__orbit mia2d-entry__orbit--b"></span>
        <span class="mia2d-entry__portraitlabel"><strong>mIA</strong> · 2D FOCUS</span>
      </div>
    </div>`;
  root.appendChild(overlay);
  const portraitImage = overlay.querySelector('.mia2d-entry__portrait img');
  portraitImage?.addEventListener('error', () => overlay.classList.add('mia2d-entry--no-avatar'), {once:true});
  if (portraitImage?.complete && !portraitImage.naturalWidth) overlay.classList.add('mia2d-entry--no-avatar');
  const button = overlay.querySelector('#mia2dEntryContinue');
  const previousFocus = document.activeElement;
  const previousOverflow = document.documentElement.style.overflow;
  document.documentElement.style.overflow = 'hidden';
  const trap = (event) => {
    if (event.key === 'Tab') { event.preventDefault(); button.focus(); }
  };
  document.addEventListener('keydown', trap, true);
  button.addEventListener('click', () => {
    document.removeEventListener('keydown', trap, true);
    document.documentElement.style.overflow = previousOverflow;
    overlay.classList.add('mia2d-entry--exit');
    overlay.addEventListener('transitionend', (event) => { if (event.target === overlay) overlay.remove(); }, {once:true});
    setTimeout(() => overlay.remove(), 500);
    const target = document.getElementById('input') || previousFocus;
    target?.focus?.({ preventScroll:true });
  });
  button.focus({ preventScroll:true });
  return { close: () => button.click() };
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => install2DEntry(), {once:true});
  } else install2DEntry();
}
