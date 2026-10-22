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
    <section class="mia-boot__content" aria-label="Preparando Mía">
      <img class="mia-boot__logo" src="${base}assets/loading/sunset-beach-club-logo.png"
           alt="Sunset Beach Club" />
      <div class="mia-boot__eyebrow">TU EXPERIENCIA COMIENZA AQUÍ</div>
      <h1>Hola, soy <em>mIA</em></h1>
      <p class="mia-boot__intro">Estoy preparando todo para darte la bienvenida.</p>
      <div class="mia-boot__progress" role="progressbar" aria-label="Carga de Mía"
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
      <div class="mia-boot__actions" data-boot-actions hidden>
        <button class="mia-boot__continue" type="button" data-boot-continue>
          Comenzar experiencia <span aria-hidden="true">→</span>
        </button>
        <button class="mia-boot__skip" type="button" data-boot-skip hidden>
          Continuar sin sonido
        </button>
      </div>
      <button class="mia-boot__retry" type="button" hidden data-boot-retry>Reintentar carga</button>
    </section>
  </div>`;

export class MiaBootLoader {
  constructor({ mode = '3d', root = document.body, variant = 'classic', markup = null } = {}) {
    this.mode = mode;
    this.variant = variant;
    this.avatarScene = null;
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
    this.node.dataset.variant = variant;
    this.node.setAttribute('aria-label', 'Cargando Mía');
    this.node.innerHTML = variant === 'sbc-assembly' && typeof markup === 'function'
      ? markup(safeBase) : html(safeBase);
    root.appendChild(this.node);
    // V3: wait until the original HQ layers are decoded before starting the
    // composition clock. Without this, slower devices show jumps/half-loaded
    // pieces even though the CSS animation has already progressed.
    if (variant === 'sbc-assembly') {
      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
      const imgs = [...this.node.querySelectorAll('.mia-sbc-v2__face')];
      const decode = imgs.map(img => {
        if (typeof img.decode === 'function') return img.decode().catch(() => {});
        if (img.complete) return Promise.resolve();
        return new Promise(resolve => {
          img.addEventListener('load', resolve, { once: true });
          img.addEventListener('error', resolve, { once: true });
        });
      });
      this.assemblyDone = Promise.all(decode).then(() => {
        if (!this.active) return;
        this.node.classList.add('mia-sbc-v3--play');
        return new Promise(resolve => window.setTimeout(resolve, reduced ? 0 : 5650));
      });
    } else {
      this.assemblyDone = Promise.resolve();
    }
    this.percentEl = this.node.querySelector('[data-boot-percent]');
    this.barEl = this.node.querySelector('[data-boot-bar]');
    this.ringEl = this.node.querySelector('.mia-boot__ring-value');
    this.statusEl = this.node.querySelector('[data-boot-status]');
    this.detailEl = this.node.querySelector('[data-boot-details]');
    this.progressEl = this.node.querySelector('[role="progressbar"]');
    this.retryEl = this.node.querySelector('[data-boot-retry]');
    this.actionsEl = this.node.querySelector('[data-boot-actions]');
    this.continueEl = this.node.querySelector('[data-boot-continue]');
    this.skipEl = this.node.querySelector('[data-boot-skip]');
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
      this.statusEl.textContent = 'Cargando los recursos de Mía…';
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
    } else if (details.phase === '2d') {
      this.phase = '2d';
      this.statusEl.textContent = 'Preparando tu experiencia 2D…';
      this.detailEl.textContent = 'Cargando los recursos visuales';
    } else if (details.phase === 'animations') {
      this.phase = 'animations';
      this.statusEl.textContent = 'Sincronizando las animaciones…';
      this.detailEl.textContent = 'Preparando la bienvenida';
    }
  }

  /** Revela el modelo Three.js YA cargado: no crea un segundo avatar ni GLB. */
  async revealAvatar(scene) {
    if (this.variant !== 'sbc-assembly' || !this.active || !scene?.model) return;
    await this.assemblyDone;
    if (!this.active) return;
    this.avatarScene = scene;
    // Reframe the existing camera; never move the rig or the avatar root.
    this._introResize = () => {
      if (this.avatarScene === scene) scene._framingGoal = window.innerWidth < 850 ? 0 : -0.76;
    };
    window.addEventListener('resize', this._introResize);
    this._introResize();
    scene.play('mIA_IDLE_SAFE', { fade: .3, loop: true });
    this.node.classList.add('mia-boot--avatar-ready');
    await new Promise((resolve) => window.setTimeout(resolve,
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ? 0 : 860));
  }

  _restoreAvatar() {
    const scene = this.avatarScene;
    if (!scene) return;
    this.avatarScene = null;
    if (this._introResize) window.removeEventListener('resize', this._introResize);
    this._introResize = null;
    scene._framingGoal = 0; // Normal scene framing resumes smoothly.
  }

  async _exit() {
    if (!this.active) return;
    this.node.classList.add('mia-boot--leaving');
    this._restoreAvatar();
    await new Promise((resolve) => setTimeout(resolve, 290));
    this.dispose();
  }

  /**
   * Complete with an optional, REAL user gesture gate.
   * onContinue must call audio.play()/speechSynthesis.speak() synchronously,
   * before its first await. Never dispatch artificial clicks.
   * For other worlds complete() retains the original hands-free behavior.
   */
  async complete({ onContinue = null } = {}) {
    if (!this.active || this.phase === 'error') return;
    this.phase = 'done';
    this.target = this.displayed = 100;
    this.statusEl.textContent = '¡Todo listo para empezar!';
    this.detailEl.textContent = 'Mía está preparada';
    this._render();
    await this.assemblyDone;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (typeof onContinue !== 'function') {
      await new Promise((resolve) => setTimeout(resolve, 460));
      await this._exit();
      return { status: 'completed' };
    }
    if (!this.active) return { status: 'disposed' };
    this.phase = 'ready-for-user';
    this.actionsEl.hidden = false;
    this.continueEl.hidden = false;
    this.continueEl.disabled = false;
    this.continueEl.focus?.({ preventScroll: true });
    this.detailEl.textContent = 'Pulsa para conocer a Mía y escuchar su bienvenida';
    return new Promise((resolve) => {
      let inFlight = false;
      const finish = (result) => {
        if (!this.active) return;
        this._exit().then(() => resolve(result));
      };
      const retry = () => {
        inFlight = false;
        if (!this.active) return;
        this.continueEl.disabled = false;
        this.continueEl.innerHTML = 'Intentar de nuevo con sonido <span aria-hidden="true">→</span>';
        this.statusEl.textContent = 'No se ha podido reproducir el saludo';
        this.detailEl.textContent = 'Puedes reintentar o continuar sin sonido';
        this.skipEl.hidden = false;
      };
      this.continueEl.addEventListener('click', () => {
        if (inFlight || !this.active) return;
        inFlight = true;
        this.continueEl.disabled = true;
        let playing;
        // Do NOT introduce any await or timer before this call. The caller
        // starts the cached HTMLAudioElement within the trusted click event.
        try { playing = onContinue(); }
        catch (error) { console.warn('[mIA Boot] No se pudo iniciar voz:', error); retry(); return; }
        Promise.resolve(playing).then((result) => {
          if (result === false || ['blocked','unavailable','cancelled'].includes(result?.status)) retry();
          else finish(result);
        }).catch((error) => {
          console.warn('[mIA Boot] Error de voz:', error);
          retry();
        });
      });
      this.skipEl.addEventListener('click', () => {
        if (!this.active) return;
        this.skipEl.disabled = true;
        this.continueEl.disabled = true;
        finish({ status: 'skipped-audio' });
      });
    });
  }

  fail(error) {
    if (!this.active) return;
    console.error('[mIA Boot] Error de carga:', error);
    this.phase = 'error';
    this.statusEl.textContent = 'No se ha podido cargar Mía';
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
    this._restoreAvatar();
    this.node.remove();
  }
}
