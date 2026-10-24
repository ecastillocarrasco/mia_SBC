/**
 * mIA V4.3 — splash profesional, progreso real de descarga e inicializacion.
 * Las imagenes NUNCA llevan porcentajes dibujados. Los valores se generan
 * segun el numero de bytes descargados y el estado efectivo de la escena.
 */
import './boot-loader-v43.css';

const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

const html = (base) => `
  <div class="mia-boot__layout">
    <div class="mia-boot__figure" aria-hidden="true">
      <img class="mia-boot__art" alt="" src="${base}assets/loading/mia-loading-art.webp" />
    </div>
    <section class="mia-boot__content" aria-label="Preparando mIA">
      <img class="mia-boot__logo" src="${base}assets/loading/sunset-beach-club-logo.png"
           alt="Sunset Beach Club" />
      <div class="mia-boot__eyebrow">TU EXPERIENCIA COMIENZA AQUÍ</div>
      <h1>Hola, soy <em>mIA</em></h1>
      <p class="mia-boot__intro">Estoy preparando todo para darte la bienvenida.</p>
      <div class="mia-boot__progress" role="progressbar" aria-label="Carga de mIA"
           aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
        <svg class="mia-boot__ring" viewBox="0 0 120 120" aria-hidden="true">
          <circle class="mia-boot__ring-track" cx="60" cy="60" r="52" />
          <circle class="mia-boot__ring-value" cx="60" cy="60" r="52" />
        </svg>
        <div class="mia-boot__ring-number"><strong data-boot-percent>0</strong><small>%</small></div>
      </div>
      <div class="mia-boot__status" data-boot-status aria-live="polite">Preparando el escenario…</div>
      <div class="mia-boot__bar" aria-hidden="true"><span data-boot-bar></span></div>
      <div class="mia-boot__details" data-boot-details>Iniciando el asistente</div>
      <div class="mia-boot__steps" aria-hidden="true">
        <span data-boot-step="0" class="active">Recursos</span>
        <span data-boot-step="1">Animaciones</span>
        <span data-boot-step="2">Listo</span>
      </div>
      <button class="mia-boot__retry" type="button" hidden data-boot-retry>Reintentar carga</button>
    </section>
  </div>`;

export class MiaBootLoader {
  constructor({ mode = '3d', root = document.body } = {}) {
    this.mode = mode;
    this.active = true;
    this.target = 0;
    this.displayed = 0;
    this.phase = 'initial';
    this.raf = null;
    const base = import.meta.env?.BASE_URL || '/';
    const safeBase = base.endsWith('/') ? base : `${base}/`;
    this.node = document.createElement('div');
    this.node.className = 'mia-boot';
    this.node.dataset.mode = mode;
    this.node.setAttribute('aria-label', 'Cargando mIA');
    this.node.innerHTML = html(safeBase);
    root.appendChild(this.node);
    this.percentEl = this.node.querySelector('[data-boot-percent]');
    this.barEl = this.node.querySelector('[data-boot-bar]');
    this.ringEl = this.node.querySelector('.mia-boot__ring-value');
    this.statusEl = this.node.querySelector('[data-boot-status]');
    this.detailEl = this.node.querySelector('[data-boot-details]');
    this.progressEl = this.node.querySelector('[role="progressbar"]');
    this.retryEl = this.node.querySelector('[data-boot-retry]');
    this.steps = Array.from(this.node.querySelectorAll('[data-boot-step]'));
    this.retryEl.addEventListener('click', () => window.location.reload());
    this._render();
    this._tick = this._tick.bind(this);
    this.raf = requestAnimationFrame(this._tick);
  }

  _render() {
    const value = clamp(Math.round(this.displayed), 0, 100);
    this.percentEl.textContent = String(value);
    this.barEl.style.width = `${value}%`;
    this.ringEl.style.strokeDasharray = `${(2 * Math.PI * 52).toFixed(2)}`;
    this.ringEl.style.strokeDashoffset = String(2 * Math.PI * 52 * (1 - value / 100));
    this.progressEl.setAttribute('aria-valuenow', String(value));
    const step = value >= 100 ? 2 : value >= 95 ? 1 : 0;
    this.steps.forEach((element, index) => {
      element.classList.toggle('active', index === step);
      element.classList.toggle('done', index < step);
    });
  }

  _tick() {
    if (!this.active) return;
    const distance = this.target - this.displayed;
    if (distance > 0) {
      // Animamos hacia el valor medido, nunca lo superamos ni inventamos %.
      this.displayed = Math.min(this.target, this.displayed + Math.max(0.16, distance * 0.13));
      this._render();
    }
    this.raf = requestAnimationFrame(this._tick);
  }

  progress(fraction, details = {}) {
    if (!this.active || this.phase === 'error') return;
    if (!Number.isFinite(fraction)) return;
    const bounded = clamp(fraction, 0, 0.99);
    this.target = Math.max(this.target, Math.floor(bounded * 100));
    if (details.phase === 'downloading') {
      this.phase = 'downloading';
      this.statusEl.textContent = 'Cargando los recursos de mIA…';
      if (details.loadedBytes && details.totalBytes) {
        const loaded = (details.loadedBytes / 1048576).toFixed(1);
        const total = (details.totalBytes / 1048576).toFixed(1);
        const estimate = details.estimatedTotal ? ' aprox.' : '';
        this.detailEl.textContent = `${loaded} de ${total} MB${estimate}`;
      }
    } else if (details.phase === 'processing') {
      this.phase = 'processing';
      this.statusEl.textContent = 'Preparando el personaje 3D…';
      this.detailEl.textContent = 'Organizando geometría y materiales';
    } else if (details.phase === 'animations') {
      this.phase = 'animations';
      this.statusEl.textContent = 'Sincronizando las animaciones…';
      this.detailEl.textContent = 'Preparando la bienvenida';
    }
  }

  async complete() {
    if (!this.active || this.phase === 'error') return;
    // Se alcanza 100 únicamente tras scene.load() y AnimationMixer listos.
    this.phase = 'done';
    this.target = this.displayed = 100;
    this.statusEl.textContent = '¡Todo listo para empezar!';
    this.detailEl.textContent = 'mIA está preparada';
    this._render();
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await new Promise((resolve) => setTimeout(resolve, 460));
    this.node.classList.add('mia-boot--leaving');
    await new Promise((resolve) => setTimeout(resolve, 480));
    this.dispose();
  }

  fail(error) {
    if (!this.active) return;
    console.error('[mIA Boot] Error de carga:', error);
    this.phase = 'error';
    this.statusEl.textContent = 'No se ha podido cargar mIA';
    this.detailEl.textContent = 'Comprueba la conexión y vuelve a intentarlo.';
    this.retryEl.hidden = false;
    cancelAnimationFrame(this.raf);
    this.node.classList.add('mia-boot--error');
    // Nunca muestra un 100 % falso tras error.
  }

  dispose() {
    if (!this.active) return;
    this.active = false;
    cancelAnimationFrame(this.raf);
    this.node.remove();
  }
}
