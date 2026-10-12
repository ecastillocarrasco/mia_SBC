/**
 * Director de interpretación propio de mIA Holograma V5.2.
 * No importa ni modifica MiaBehaviorV4 (mundo 3D).
 * Usa los clips existentes de las 84 animaciones; el GLB es inmutable.
 * Personalidad: serena, luminosa, frontal; gestos de precisión; nada de paseos.
 */
const STATES = new Set([
  'idle', 'greeting', 'listening', 'thinking', 'waiting',
  'speaking', 'presenting', 'success', 'error', 'farewell',
]);

const STAGE = Object.freeze({
  idle: ['mIA_IDLE_BREATHING', 'mIA_SEQ_ESCUCHA_ACTIVA', 'mIA_IDLE_HAPPY'],
  greeting: ['mIA_SEQ_OFRECER_AYUDA', 'mIA_WAVE_ALT', 'mIA_SEQ_AGRADECIMIENTO'],
  listening: ['mIA_SEQ_ESCUCHA_ACTIVA', 'mIA_IDLE_BREATHING', 'mIA_AGREE_ALT'],
  thinking: ['mIA_SEQ_CONSULTANDO_DATOS', 'mIA_SEQ_PENSANDO', 'mIA_SEQ_ESPERA'],
  waiting: ['mIA_SEQ_ESPERA', 'mIA_SEQ_CONSULTANDO_DATOS', 'mIA_SEQ_PENSANDO'],
  speaking: ['mIA_TALK_ALT3', 'mIA_SEQ_RESPUESTA_CORTA', 'mIA_TALK_ALT2'],
  presenting: ['mIA_SEQ_EXPLICAR_DIAGRAMA', 'mIA_SEQ_SENALAR_PANTALLA'],
  success: ['mIA_SEQ_CONFIRMACION', 'mIA_AGREE_ALT2'],
  error: ['mIA_SEQ_DUDA', 'mIA_SHRUG'],
  farewell: ['mIA_SEQ_DESPEDIDA', 'mIA_WAVE_ALT'],
});
const PRESENTATIONS = Object.freeze({
  analytics: ['mIA_SEQ_EXPLICAR_DIAGRAMA', 'mIA_SEQ_CONFIRMACION'],
  dashboard: ['mIA_SEQ_EXPLICAR_DIAGRAMA', 'mIA_SEQ_SENALAR_PANTALLA'],
  comparison: ['mIA_SEQ_EXPLICAR_DIAGRAMA', 'mIA_SEQ_ASENTIR'],
  data: ['mIA_SEQ_SENALAR_PANTALLA', 'mIA_SEQ_RESPUESTA_CORTA'],
  list: ['mIA_SEQ_SENALAR_PANTALLA', 'mIA_SEQ_ASENTIR'],
  person: ['mIA_SEQ_OFRECER_AYUDA', 'mIA_SEQ_ESCUCHA_ACTIVA'],
  employee360: ['mIA_SEQ_OFRECER_AYUDA', 'mIA_SEQ_ESCUCHA_ACTIVA'],
  report: ['mIA_SEQ_EXPLICAR_DIAGRAMA', 'mIA_SEQ_ASENTIR'],
  document: ['mIA_SEQ_SENALAR_PANTALLA', 'mIA_SEQ_ASENTIR'],
});
const BACKEND = Object.freeze({
  reposo: 'idle', escuchando: 'listening', pensando: 'thinking',
  concentrada: 'thinking', hablando: 'speaking', saludando: 'greeting',
  sonriendo: 'success', entusiasmada: 'success', celebrando: 'success',
  sorprendida: 'success', confundida: 'error', avisando: 'presenting',
  empatica: 'listening', despedida: 'farewell', aprobando: 'success',
});

function normalized(value) {
  return String(value || '').trim().toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
}

export class MiaHologramDirectorV52 {
  constructor({ scene, onStateChange = null, schedule = globalThis.setTimeout,
    clearSchedule = globalThis.clearTimeout, now = () => Date.now() } = {}) {
    if (!scene) throw new Error('Se requiere MiaScene para el director holográfico');
    this.scene = scene;
    this.onStateChange = onStateChange;
    this.state = 'idle';
    this.context = {};
    this._timer = null;
    this._schedule = schedule;
    this._clear = clearSchedule;
    this._now = now;
    this._token = 0;
    this._step = Object.create(null);
    this._waitingSince = null;
    this._destroyed = false;
  }

  _pick(candidates = [], key = '') {
    const actions = this.scene.actions;
    if (!actions?.has) return 'mIA_IDLE_SAFE';
    const existing = candidates.filter((name) => actions.has(name));
    // Para la proyección se prefieren gestos que no giren la cadera.
    const frontal = existing.filter((name) => this.scene.isFrontFacingClip?.(name) !== false);
    const usable = frontal.length ? frontal : existing;
    const next = this._step[key] ?? 0;
    this._step[key] = next + 1;
    return usable[next % usable.length] ||
      (actions.has('mIA_IDLE_BREATHING') ? 'mIA_IDLE_BREATHING' : 'mIA_IDLE_SAFE');
  }

  _presentCandidates() {
    const kind = normalized(this.context.presentationType || this.context.type || 'analytics');
    return PRESENTATIONS[kind] || STAGE.presenting;
  }

  _run() {
    if (this._destroyed) return;
    let choices = this.state === 'presenting' ? this._presentCandidates() : STAGE[this.state];
    if (!choices) choices = STAGE.idle;
    const key = this.state === 'presenting'
      ? `present-${normalized(this.context.presentationType)}` : this.state;
    if ((this.state === 'thinking' || this.state === 'waiting') && this._waitingSince != null) {
      const duration = Math.max(0, this._now() - this._waitingSince);
      if (duration >= 32000) {
        // Espera paciente, no aburrida ni caminando alrededor del ventilador.
        choices = ['mIA_SEQ_ESPERA', 'mIA_SEQ_ESCUCHA_ACTIVA', 'mIA_SEQ_PENSANDO'];
      }
    }
    const clip = this._pick(choices, key);
    const oneShot = new Set(['greeting', 'success', 'error', 'farewell']);
    const loop = !oneShot.has(this.state);
    try {
      this.scene.stopGesture?.(0.32);
      this.scene.play(clip, { fade: this.state === 'greeting' ? 0.65 : 0.72,
        loop, clamp: false, timeScale: this.state === 'speaking' ? 0.93 : 0.91 });
    } catch (animationError) {
      // The animation layer must never crash a query or leave a repeat timer.
      console.warn('[mIA HG V5.2.5] Clip incompatible:', clip, animationError);
      try { this.scene.play('mIA_IDLE_SAFE', {fade:0.35,loop:true}); }
      catch { /* Query and result remain operational. */ }
      return;
    }
    if (oneShot.has(this.state)) return;
    const seconds = this.scene.clipDuration?.(clip) || 5;
    const ms = Math.max(2800, Math.min(this.state === 'idle' ? 8800 : 10500,
      seconds * 850));
    const token = this._token;
    this._timer = this._schedule(() => {
      this._timer = null;
      if (!this._destroyed && token === this._token) this._run();
    }, ms);
  }

  enter(state, context = {}) {
    if (this._destroyed) return;
    const next = STATES.has(state) ? state : 'idle';
    this._token++;
    if (this._timer !== null) this._clear(this._timer);
    this._timer = null;
    const waitingBefore = this.state === 'thinking' || this.state === 'waiting';
    this.state = next;
    this.context = { ...context };
    if (next === 'thinking' || next === 'waiting') {
      if (!waitingBefore) this._waitingSince = this._now();
    } else this._waitingSince = null;
    this.onStateChange?.(next, this.context);
    this._run();
  }

  enterBackendState(value) {
    const state = BACKEND[normalized(value)];
    if (!state) return false;
    this.enter(state);
    return true;
  }

  progress() {
    if (this.state !== 'thinking' && this.state !== 'waiting') this.enter('thinking');
  }

  destroy() {
    this._destroyed = true;
    this._token++;
    if (this._timer !== null) this._clear(this._timer);
    this._timer = null;
    this.scene.stopGesture?.(0.2);
  }
}

export const HOLOGRAM_V52_CLIP_PROFILE = STAGE;
