/**
 * mIA HG 5.2.6 - turn integrity and a deterministic local clock intent.
 * No backend, 2D, 3D or GLB changes.
 *
 * A 200 JSON response is NOT proof that it belongs to the current question.
 * Without a server-echoed request ID, relevance cannot be proven in general.
 * We reject explicit mismatched echoes and suspicious cross-turn replays.
 */

export class HologramReplyMismatchError extends Error {
  constructor(code = 'stale-reply') {
    super('La respuesta recibida no se ha podido vincular de forma fiable a la consulta actual');
    this.name = 'HologramReplyMismatchError';
    this.code = code;
  }
}

const obj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function normalizeQuestion(value) {
  return String(value ?? '').toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
}

export function isDeviceClockQuestion(value) {
  const q = normalizeQuestion(value);
  // Only pure clock requests. Do NOT intercept "a que hora entra el turno".
  return /^(?:que hora es(?: ahora| en este momento| actualmente)?|me dices la hora|dime la hora(?: actual)?|puedes decirme la hora|hora actual|que hora tienes|a que hora estamos|me puedes decir que hora es|sabes que hora es)$/.test(q);
}

export function buildDeviceClockReply(date = new Date(), format = null) {
  const formatter = format ?? new Intl.DateTimeFormat('es-ES', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
  const hours = formatter.format(date);
  const answer = `Según el reloj de este dispositivo, ahora son las ${hours}.`;
  return {
    answer, speech: answer, speech_text: answer, presentations: [],
    route: 'local-clock',
    source: 'device-clock',
  };
}

function responseText(raw) {
  if (!obj(raw)) return '';
  return String(raw.answer || raw.natural_answer || raw.response || raw.speech || raw.speech_text || '')
    .replace(/\s+/g, ' ').trim();
}

function extractEcho(raw) {
  // Only documented request-echo-like fields, not generated report/query fields.
  const candidates = [
    raw?.request?.message, raw?.request?.user_message,
    raw?.request?.input, raw?.metadata?.input_message,
    raw?.metadata?.request_message, raw?.meta?.request_message,
    raw?.echo?.message, raw?.echo?.request_message,
  ];
  return candidates.find((v) => typeof v === 'string' && v.trim()) || '';
}

function intentOf(question) {
  const q = normalizeQuestion(question);
  if (isDeviceClockQuestion(q)) return 'clock';
  if (/(?:trabajad|trabajand|emplead|plantill|personal|turnos|en servicio)/.test(q)) return 'workforce';
  if (/(?:correo|mail|bandeja|mensajes sin leer)/.test(q)) return 'mail';
  if (/^(?:hola|buenos dias|buenas tardes|buenas noches|saludos)(?: mia)?$/.test(q)) return 'greeting';
  return 'other';
}

/**
 * One state per hologram tab. `check` must run BEFORE contextState.update.
 * `commit` is called only after a response is accepted.
 */
export function createHologramReplyIntegrity() {
  let previous = null;
  let sequence = 0;
  return {
    next(question) {
      return { sequence: ++sequence, question: String(question).trim() };
    },
    check(question, raw) {
      const actualQuestion = normalizeQuestion(question);
      if (!obj(raw) || !actualQuestion) {
        return { ok: false, code: 'invalid-result', verification: 'rejected' };
      }
      if (raw.status === 'error' || raw.success === false) {
        return { ok: false, code: 'backend-error', verification: 'rejected' };
      }
      const echoedQuestion = extractEcho(raw);
      if (echoedQuestion && normalizeQuestion(echoedQuestion) !== actualQuestion) {
        return { ok: false, code: 'mismatched-echo', verification: 'rejected' };
      }
      const currentText = responseText(raw);
      const newIntent = intentOf(question);
      // Replayed answer with a clearly different question is suspicious.
      // For two workforce questions, identical real headcounts are normal.
      // Una respuesta generica de falta de datos puede repetirse legitimamente
      // en preguntas distintas. Sin eco de consulta tampoco se puede probar
      // que la igualdad sea un replay. Solo investigar cuando cambia un
      // intento especializado, la respuesta NO es generica y no hay eco.
      const genericNoData = /\b(?:no (?:hay|tengo|dispongo de) datos|sin datos|datos insuficientes|no puedo confirmar|informaci[oó]n insuficiente)\b/iu.test(currentText);
      if (!echoedQuestion && !genericNoData && previous && currentText.length >= 36 &&
        normalizeQuestion(previous.question) !== actualQuestion &&
        currentText === previous.text &&
        previous.intent !== newIntent &&
        previous.intent !== 'other' && newIntent !== 'other') {
        return { ok: false, code: 'repeated-previous-answer', verification: 'rejected' };
      }
      // A server-provided echoed question is verifiable. Without one, report
      // "unverified"; NEVER call a loosely substantive JSON "correlated".
      return { ok: true, code: '-', verification: echoedQuestion ? 'echo-matched' : 'unverified' };
    },
    commit(question, raw) {
      previous = {
        question: String(question),
        text: responseText(raw),
        intent: intentOf(question),
      };
    },
    reset() { previous = null; },
  };
}
