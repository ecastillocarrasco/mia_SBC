/**
 * mIA Sunset Beach Club / Scene opening V2.
 * Artwork source: EXACT original PNG. The three arc layers partition V1
 * arcoiris.png pixel-for-pixel; no new graphic or logo element is introduced.
 * All copies are the original alpha silhouettes viewed in CSS 3D space.
 */
export const SBC_V2_PIECES = Object.freeze([
  { id: 'sol', label: 'Sol original', delay: .45, z: 12, x: 0, y: 85, depth: 2 },
  { id: 'arco-exterior', label: 'Arco exterior original', delay: 1.35, z: -10, x: -80, y: -40, depth: 2 },
  { id: 'arco-rojo', label: 'Arco rojo original', delay: 1.76, z: 8, x: 78, y: -27, depth: 2 },
  { id: 'arco-interior', label: 'Arco interior original', delay: 2.17, z: 25, x: 0, y: 48, depth: 2 },
  { id: 'estrella-1', label: 'Estrella 1 de 4', delay: 2.92, z: 48, x: -110, y: -80, depth: 2 },
  { id: 'estrella-2', label: 'Estrella 2 de 4', delay: 3.23, z: 48, x: -45, y: -100, depth: 2 },
  { id: 'estrella-3', label: 'Estrella 3 de 4', delay: 3.54, z: 48, x: 45, y: -100, depth: 2 },
  { id: 'estrella-4', label: 'Estrella 4 de 4', delay: 3.85, z: 48, x: 110, y: -80, depth: 2 },
  { id: 'nombre', label: 'Nombre original Sunset Beach Club', delay: 4.40, z: 21, x: 0, y: 90, depth: 2 },
]);

/** Last full-logo transition end in seconds. Boot must wait for this before showing the avatar. */
export const SBC_V2_ASSEMBLY_SECONDS = 5.65;

export function sbcAssemblyMarkup(base = '/') {
  const safeBase = String(base).endsWith('/') ? String(base) : `${base}/`;
  const src = (id) => `${safeBase}assets/loading/logo-pieces/${id}.png?v=3`;
  const parts = SBC_V2_PIECES.map(({ id, delay, z, x, y, depth }) => {
    // Genuine stacked 3D alpha-silhouette planes. Depth copies are always
    // behind the unmodified full-color face; they add physical sidewalls.
    const slabs = Array.from({ length: depth }, (_, step) =>
      `<img class="mia-sbc-v2__edge" src="${src(id)}" alt="" aria-hidden="true" draggable="false" `+
      `style="transform:translateZ(${z - (depth - step) * 2.1}px)" />`
    ).join('');
    return `<div class="mia-sbc-v2__piece mia-sbc-v2__piece--${id}" data-sbc-piece="${id}" `+
      `style="--piece-delay:${delay}s;--from-x:${x}px;--from-y:${y}px;--layer-z:${z}px" aria-hidden="true">`+
        slabs + `<img class="mia-sbc-v2__face" src="${src(id)}" alt="" aria-hidden="true" `+
        `draggable="false" style="transform:translateZ(${z}px)" />`+
      `</div>`;
  }).join('');
  return `
    <div class="mia-sbc-v2__ambience" aria-hidden="true"></div>
    <div class="mia-sbc-intro__layout mia-sbc-v2__layout">
      <section class="mia-sbc-intro__identity mia-sbc-v2__identity" aria-label="Bienvenida a mIA Sunset Beach Club">
        <p class="mia-sbc-intro__eyebrow">BIENVENIDO A mIA</p>
        <div class="mia-sbc-v2__scene" data-sbc-scene style="--sbc-mask:url('${safeBase}assets/loading/sunset-beach-club-logo.png?v=3')">
          <div class="mia-sbc-v2__rotor" data-sbc-rotor role="img"
            aria-label="Logotipo original de Sunset Beach Club: sol, tres franjas del arcoíris, cuatro estrellas y nombre">
            ${parts}
          </div>
        </div>
        <p class="mia-sbc-intro__caption mia-sbc-v2__caption">Una experiencia más allá de la pantalla</p>
        <div class="mia-sbc-v3__footer">
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
          <div class="mia-boot__details" data-boot-details>Preparando el escenario</div>
          <div class="mia-boot__steps" aria-hidden="true"><span data-boot-step="0" class="active">Recursos</span><span data-boot-step="1">Animaciones</span><span data-boot-step="2">Listo</span></div>
        </div>
        <div class="mia-sbc-v3__ready">
        <p class="mia-sbc-intro__appearance">mIA está aquí para acompañarte.</p>
        <div class="mia-boot__actions" data-boot-actions hidden>
          <button class="mia-boot__continue" type="button" data-boot-continue>Continuar la experiencia <span aria-hidden="true">→</span></button>
          <button class="mia-boot__skip" type="button" data-boot-skip hidden>Continuar sin sonido</button>
        </div>
        </div>
        <button class="mia-boot__retry" type="button" hidden data-boot-retry>Reintentar carga</button>
        </div>
      </section>
      <div class="mia-sbc-intro__avatar-area mia-sbc-v2__avatar-veil" aria-hidden="true"></div>
    </div>`;
}
