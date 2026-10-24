/**
 * Exact artwork layers extracted from the original Sunset Beach Club logo.
 * Each visible source pixel belongs to precisely one layer. No new star,
 * curve, letter or pictogram has been drawn or removed.
 */
export const SBC_LOGO_PIECES = [
  ['sol', 'Sol'],
  ['arcoiris', 'Arcoíris'],
  ['estrella-1', 'Estrella 1 de 4'],
  ['estrella-2', 'Estrella 2 de 4'],
  ['estrella-3', 'Estrella 3 de 4'],
  ['estrella-4', 'Estrella 4 de 4'],
  ['nombre', 'Nombre Sunset Beach Club'],
];

export function sbcAssemblyMarkup(base = '/') {
  const imageBase = `${base}assets/loading/logo-pieces/`;
  const parts = SBC_LOGO_PIECES.map(([name, label], position) =>
    `<img class="mia-sbc-intro__piece mia-sbc-intro__piece--${name}" src="${imageBase}${name}.png" alt="" aria-hidden="true" data-sbc-piece="${name}" style="--piece-order:${position}" />`
  ).join('');
  return `
    <div class="mia-sbc-intro__layout">
      <div class="mia-sbc-intro__identity">
        <p class="mia-sbc-intro__eyebrow">BIENVENIDO A mIA</p>
        <div class="mia-sbc-intro__logo" role="img" aria-label="Logotipo original de Sunset Beach Club: sol, arcoíris, cuatro estrellas y nombre">
          ${parts}
        </div>
        <div class="mia-sbc-intro__caption">Una experiencia más allá de la pantalla</div>
        <div class="mia-sbc-intro__loading" aria-live="polite">
          <div class="mia-boot__progress" role="progressbar" aria-label="Carga de mIA" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
            <svg class="mia-boot__ring" viewBox="0 0 120 120" aria-hidden="true">
              <circle class="mia-boot__ring-track" cx="60" cy="60" r="52" />
              <circle class="mia-boot__ring-value" cx="60" cy="60" r="52" />
            </svg>
            <div class="mia-boot__ring-number"><strong data-boot-percent>0</strong><small>%</small></div>
          </div>
          <div class="mia-boot__status" data-boot-status aria-live="polite">Preparando mIA en 3D…</div>
          <div class="mia-boot__bar"><span data-boot-bar></span></div>
          <div class="mia-boot__details" data-boot-details>Iniciando la experiencia</div>
          <div class="mia-boot__steps" aria-hidden="true"><span data-boot-step="0" class="active">Recursos</span><span data-boot-step="1">Animaciones</span><span data-boot-step="2">Listo</span></div>
        </div>
        <div class="mia-sbc-intro__appearance" aria-live="polite">mIA está aquí para acompañarte.</div>
        <div class="mia-boot__actions" data-boot-actions hidden>
          <button class="mia-boot__continue" type="button" data-boot-continue>Continuar la experiencia <span aria-hidden="true">→</span></button>
          <button class="mia-boot__skip" type="button" data-boot-skip hidden>Continuar sin sonido</button>
        </div>
        <button class="mia-boot__retry" type="button" hidden data-boot-retry>Reintentar carga</button>
      </div>
      <div class="mia-sbc-intro__avatar-area" aria-hidden="true"></div>
    </div>`;
}
