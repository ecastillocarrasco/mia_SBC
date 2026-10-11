/**
 * mIA V4 | Behaviour director. Only plays clips exported in the 84-clip GLB.
 * Separates conversational states from data-driven presentations.
 * Never invents application data, interrupts long tasks gracefully, and varies waiting animations.
 */
const STATE_NAMES = new Set([
  'idle', 'greeting', 'listening', 'thinking', 'waiting', 'speaking',
  'presenting', 'success', 'error', 'farewell',
]);

const BACKEND_STATES = {
  reposo: 'idle', escuchando: 'listening', pensando: 'thinking',
  concentrada: 'thinking', hablando: 'speaking', sonriendo: 'success',
  saludando: 'greeting', guinando: 'success', sorprendida: 'success',
  confundida: 'error', entusiasmada: 'success', celebrando: 'success',
  avisando: 'presenting', empatica: 'listening', despedida: 'farewell',
  aprobando: 'success',
};

const PRESENTATIONS = {
  person: 'mIA_SEQ_EXPLICACION',
  employee360: 'mIA_SEQ_EXPLICACION',
  data: 'mIA_SEQ_SENALAR_PANTALLA',
  list: 'mIA_SEQ_SENALAR_PANTALLA',
  analytics: 'mIA_SEQ_PRESENTAR_KPI',
  comparison: 'mIA_SEQ_COMPARAR_DATOS',
  dashboard: 'mIA_SEQ_PRESENTAR_KPI',
  document: 'mIA_SEQ_EXPLICAR_DIAGRAMA',
  report: 'mIA_SEQ_EXPLICAR_DIAGRAMA',
  shifts: 'mIA_SEQ_EXPLICACION',
};

// V4.2: no usar el final defectuoso del idle original ni el último
// WEIGHT_SHIFT, que provocaba un gesto brusco en el reposo.
const IDLE_CYCLE = [
  'mIA_IDLE_SAFE', 'mIA_IDLE_BREATHING',
  'mIA_IDLE_SAFE', 'mIA_IDLE_HAPPY',
];
// Los gestos especiales de espera solo aparecen si la consulta realmente tarda.
const THINKING_CYCLE = [
  'mIA_THINK', 'mIA_SEQ_CONSULTANDO_DATOS',
  'mIA_TYPING', 'mIA_SEQ_TRABAJANDO',
];
const WAIT_BORED = 'mIA_IDLE_SAD';
const WAIT_COMPOSED = 'mIA_SEQ_ESPERA';
const WAIT_CIRCLE = 'mIA_WALK_CIRCLE';
// Los gestos muy girados se mantienen en la biblioteca para reproducción
// manual, pero no se incluyen en los ciclos automáticos de conversación.
const SPEAKING_CYCLE = [
  'mIA_TALK', 'mIA_TALK_ALT', 'mIA_TALK_ALT2',
];
const LISTENING_CYCLE = [
  'mIA_IDLE_SAFE', 'mIA_IDLE_BREATHING', 'mIA_AGREE_ALT',
];

function norm(value) {
  return String(value ?? '').trim().toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
}

function reduced() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
}

export class MiaBehaviorV4 {
  constructor({ scene, mode = '3d', onStateChange = null } = {}) {
    if (!scene) throw new Error('MiaBehaviorV4 requiere una escena');
    this.scene = scene;
    this.mode = mode;
    this.onStateChange = onStateChange;
    this.state = 'idle';
    this.context = {};
    this._timer = null;
    this._token = 0;
    this._cycles = new Map();
    this._destroyed = false;
    this._queryStartedAt = null;
    this._waitingRound = 0;
    this._boredShown = false;
    this._circleShown = false;
    this._frontPointing = false;
  }

  _available(candidates, { preferFront = false } = {}) {
    const present = candidates.filter((name) => this.scene.actions.has(name));
    if (preferFront) {
      const frontal = present.find((name) => this.scene.isFrontFacingClip?.(name) !== false);
      if (frontal) return frontal;
    }
    return present[0] ||
      (this.scene.actions.has('mIA_IDLE_SAFE') ? 'mIA_IDLE_SAFE' : 'mIA_IDLE');
  }

  _next(candidates, key) {
    const present = candidates.filter((name) => this.scene.actions.has(name));
    // Si un clip gira mucho la cadera, no se elige automáticamente como
    // reposo/charla. No se modifica su animación original.
    const frontal = present.filter((name) => this.scene.isFrontFacingClip?.(name) !== false);
    const available = frontal.length ? frontal : present;
    if (!available.length) return this._available(candidates);
    const index = this._cycles.get(key) ?? 0;
    this._cycles.set(key, index + 1);
    return available[index % available.length];
  }

  _start(name, options = {}) {
    if (!name) return;
    if (name !== WAIT_CIRCLE) this.scene.stopWaitOrbit?.();
    this.scene.play(name, {
      fade: reduced() ? 0 : 0.48,
      loop: false,
      clamp: false,
      ...options,
    });
  }

  _schedule(delay, callback) {
    const token = this._token;
    this._timer = window.setTimeout(() => {
      this._timer = null;
      if (this._destroyed || token !== this._token) return;
      callback();
    }, delay);
  }

  enter(state, context = {}) {
    if (this._destroyed) return;
    const next = STATE_NAMES.has(state) ? state : 'idle';
    this._token += 1;
    window.clearTimeout(this._timer);
    this._timer = null;
    const wasWaiting = this.state === 'thinking' || this.state === 'waiting';
    this.state = next;
    this.context = { ...context };
    this._frontPointing = false;
    // Conservar el tiempo de la consulta si solo cambiamos pensando/esperando.
    if (next === 'thinking' || next === 'waiting') {
      if (!wasWaiting || this._queryStartedAt == null) {
        this._queryStartedAt = Date.now();
        this._waitingRound = 0;
        this._boredShown = false;
        this._circleShown = false;
      }
    } else {
      this._queryStartedAt = null;
      this.scene.stopWaitOrbit?.();
    }
    this.scene.stopGesture?.(0.2);
    this.onStateChange?.(next, context);

    if (next === 'greeting') {
      this._start(this._available(['mIA_SEQ_BIENVENIDA', 'mIA_GREET']));
    } else if (next === 'farewell') {
      this._start(this._available(['mIA_SEQ_DESPEDIDA', 'mIA_WAVE']));
    } else if (next === 'presenting') {
      const type = norm(context.presentationType || context.type || 'data');
      // The raw POINT clip has the torso/head/arms we need, but playing its
      // whole-body posture or chaining a long POINT composition can appear
      // sideways. Stabilize the hips/feet on frontal IDLE_SAFE and play only
      // the upper-body gesture. Do not rotate the entire 3D model.
      const frontTypes = new Set(['data','list','shifts','person','employee360']);
      this._frontPointing = frontTypes.has(type) &&
        typeof this.scene.playGesture === 'function' &&
        this.scene.actions.has('mIA_POINT');
      if (this._frontPointing) {
        this._start(this._available(['mIA_IDLE_SAFE','mIA_IDLE']), { loop: true, fade: 0.65 });
        this.scene.playGesture('mIA_POINT', { fadeIn: 0.38, fadeOut: 0.34, weight: 0.82 });
        if (!reduced()) this._schedule(4900, () => this._runPresentationTalk());
      } else {
        const special = this._available([
          PRESENTATIONS[type], 'mIA_SEQ_EXPLICACION', 'mIA_TALK',
        ].filter(Boolean), { preferFront: true });
        // KPI, report and comparison retain their contextual sequences.
        this._start(special, { loop: true, fade: 0.62 });
        const duration = Math.max(4000, Math.min(14500, (this.scene.clipDuration?.(special) || 7) * 1000));
        if (!reduced()) this._schedule(duration, () => this._runPresentationTalk());
      }
    } else if (next === 'success') {
      this._start(this._available(['mIA_SEQ_CONFIRMACION', 'mIA_AGREE']));
    } else if (next === 'error') {
      this._start(this._available(['mIA_SEQ_DUDA', 'mIA_SHRUG']));
    } else {
      this._runCycle(next);
    }
  }

  _runPresentationTalk() {
    if (this._destroyed || this.state !== 'presenting') return;
    if (this._frontPointing) {
      // Keep the avatar frontal throughout explanatory speech. Alternating
      // masked hand gestures preserves natural expression without hip turns.
      const index = this._cycles.get('front-pointing') ?? 0;
      this._cycles.set('front-pointing', index + 1);
      const gesture = index % 4 === 3 ? 'mIA_POINT' : (index % 2 ? 'mIA_TALK_ALT' : 'mIA_TALK');
      if (this.scene.actions.has(gesture)) {
        this.scene.playGesture(gesture, { fadeIn: 0.30, fadeOut: 0.32, weight: 0.78 });
      }
      if (!reduced()) this._schedule(4300, () => this._runPresentationTalk());
      return;
    }
    const kind = norm(this.context.presentationType || 'data');
    const contextual = PRESENTATIONS[kind];
    const round = this._cycles.get('presenting') || 0;
    this._cycles.set('presenting', round + 1);
    // Re-emphasise the current result occasionally; avoid endlessly restarting
    // a long sequence while the answer is still being read aloud.
    const candidates = round % 4 === 3 && contextual
      ? [contextual, 'mIA_SEQ_EXPLICACION']
      : SPEAKING_CYCLE;
    const name = this._next(candidates, 'presenting-talk');
    this._start(name, { loop: true, fade: reduced() ? 0 : 0.62 });
    if (!reduced()) {
      const duration = Math.max(3900, Math.min(11500,
        (this.scene.clipDuration?.(name) || 5) * 1000));
      this._schedule(duration, () => this._runPresentationTalk());
    }
  }

  _runCycle(state) {
    if (this.state !== state || this._destroyed) return;
    const cycles = {
      idle: IDLE_CYCLE,
      waiting: THINKING_CYCLE,
      thinking: THINKING_CYCLE,
      listening: LISTENING_CYCLE,
      speaking: SPEAKING_CYCLE,
    };
    const isQueryWait = state === 'thinking' || state === 'waiting';
    const elapsed = isQueryWait && this._queryStartedAt != null
      ? Math.max(0, (Date.now() - this._queryStartedAt) / 1000) : 0;
    let name = this._next(cycles[state] || IDLE_CYCLE, state);

    if (isQueryWait) {
      const round = this._waitingRound++;
      // 20 s: gestos suaves de espera. 35 s: un bostezo/aburrimiento
      // discreto. 65 s: pequeño paseo circular en el mundo 3D.
      // El holograma conserva siempre el avatar dentro de la proyección.
      if (elapsed >= 65 && this.mode === '3d' && !reduced() &&
          this.scene.actions.has(WAIT_CIRCLE) &&
          (!this._circleShown || round % 8 === 0)) {
        name = WAIT_CIRCLE;
        this._circleShown = true;
      } else if (elapsed >= 35 && this.scene.actions.has(WAIT_BORED) &&
                 (!this._boredShown || round % 6 === 0)) {
        name = WAIT_BORED;
        this._boredShown = true;
      } else if (elapsed >= 20 && this.scene.actions.has(WAIT_COMPOSED) &&
                 round % 3 === 0) {
        name = WAIT_COMPOSED;
      }
    }

    const seconds = Math.max(1, this.scene.clipDuration?.(name) || 5);
    // Los clips especiales se reproducen una sola vez; no reiniciar sin parar
    // una caminata circular de 12.5 s a mitad de recorrido.
    const maximum = name === WAIT_CIRCLE ? 12500 :
      name === WAIT_COMPOSED ? 8500 :
      state === 'idle' ? 4600 : state === 'speaking' ? 4900 : 7100;
    const time = Math.max(1400, Math.min(maximum, seconds *
      (name === WAIT_CIRCLE ? 0.95 : name === WAIT_COMPOSED ? 0.90 : 0.72) * 1000));

    this._start(name, { loop: name !== WAIT_CIRCLE && name !== WAIT_COMPOSED,
      fade: reduced() ? 0 : name === WAIT_CIRCLE ? 0.85 : 0.65 });
    if (name === WAIT_CIRCLE) this.scene.startWaitOrbit?.(time / 1000);
    if (reduced()) return;
    this._schedule(time, () => this._runCycle(state));
  }

  enterBackendState(value, context = {}) {
    const target = BACKEND_STATES[norm(value)];
    if (!target) return false;
    this.enter(target, context);
    return true;
  }

  /** Called on repeated streaming progress events; does not reset cycle timers. */
  progress() {
    if (this.state !== 'thinking' && this.state !== 'waiting') this.enter('thinking');
  }

  destroy() {
    this._destroyed = true;
    this._token += 1;
    window.clearTimeout(this._timer);
    this.scene.stopWaitOrbit?.();
    this.scene.stopGesture?.(0.1);
  }
}

export const MIA_V4_PRESENTATIONS = PRESENTATIONS;
