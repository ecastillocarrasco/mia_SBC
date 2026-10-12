/**
 * V5.2.6 (desde V5.2.3): límite INDEPENDIENTE del fetch/SSE, para que la experiencia HG
 * nunca se quede pensando aunque el transporte ignore AbortSignal.
 * No afirma resultados ni termina consultas del backend por su cuenta.
 */
export class HologramDeadlineError extends Error {
  constructor(code = 'deadline') {
    super(code === 'cancelled' ? 'Consulta cancelada por el usuario' : 'La consulta superó el límite de espera');
    this.name = 'HologramDeadlineError';
    this.code = code;
  }
}

export function createHologramTurnGuard({
  work,
  signal,
  deadlineMs = 55000,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onDeadline = () => {},
} = {}) {
  if (typeof work !== 'function') throw new TypeError('work debe ser una función');
  let timer = null;
  let settled = false;
  let rejectCancel;
  let cancel = () => {};
  const end = () => {
    if (timer !== null) clearTimer(timer);
    timer = null;
    signal?.removeEventListener?.('abort', cancel);
  };
  const emergency = new Promise((_, reject) => {
    rejectCancel = reject;
  });
  cancel = () => {
    if (settled) return;
    settled = true;
    end();
    onDeadline('cancelled');
    rejectCancel(new HologramDeadlineError('cancelled'));
  };
  signal?.addEventListener?.('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  if (!settled) timer = setTimer(() => {
    if (settled) return;
    settled = true;
    end();
    onDeadline('deadline');
    rejectCancel(new HologramDeadlineError('deadline'));
  }, Math.max(200, deadlineMs));

  // Siempre se observa el rechazo de work, también después del timeout,
  // evitando errores asíncronos sin controlar. No bloquea el cierre visual.
  const source = Promise.resolve().then(() => {
    if (settled) throw new HologramDeadlineError('cancelled');
    return work();
  });
  const result = Promise.race([source, emergency]).finally(() => {
    settled = true;
    end();
  });
  return { result, cancel };
}

export function sanitizeHologramTrace(trace = {}) {
  // Nunca incluir consulta, session_id, nombres, datos de personal ni SSE raw.
  return {
    version: '5.2.9',
    phase: String(trace.phase || 'ready').slice(0, 40),
    event: String(trace.event || '-').slice(0, 40),
    events: Math.max(0, Number(trace.events) || 0),
    http: Number(trace.http) || null,
    elapsedSeconds: Math.max(0, Math.round((Number(trace.elapsedMs) || 0) / 1000)),
    lastError: String(trace.lastError || '-').slice(0, 50),
    result: Boolean(trace.result),
    requestStarted: Boolean(trace.requestStarted),
    uiWarning: String(trace.uiWarning || '-').slice(0, 40),
    route: String(trace.route || '-').slice(0, 40),
    validation: String(trace.validation || '-').slice(0, 40),
    turn: Math.max(0, Number(trace.turn) || 0),
  };
}
