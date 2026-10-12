/**
 * mIA Holograma V5.2.9 — la MISMA ruta conversacional del 2D clásico.
 * Nunca se resuelven consultas por respuestas sociales locales ni se desvían
 * las preguntas de turnos/plantilla a una ruta específica del holograma.
 * El gateway/backend valida origen, permisos, frescura y significado de datos.
 * El HG exclusivamente transforma la presentación, no las conclusiones.
 *
 * 2D: LLM /api/mia/v4/chat -> NDJSON /api/mia/chat/stream -> JSON /api/mia/chat.
 */
export class HologramApiError extends Error {
  constructor(message, code = 'backend-unavailable') {
    super(message);
    this.name = 'HologramApiError';
    this.code = code;
  }
}

/** Generar archivos es una operación potencialmente NO idempotente. */
export function isReportGenerationIntent(message) {
  const q = String(message||'').toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g,'');
  return /\b(genera(?:me)?|generar|crea(?:me)?|crear|elabora(?:me)?|elaborar|prepara(?:me)?|preparar|hazme|emitir|emite|exportar|exporta(?:me)?|descarga(?:me)?)\b/.test(q) &&
    /\b(informe|report|pdf|excel|xlsx|word|docx|pptx|documento)\b/.test(q);
}
function isSimpleGreeting(message) {
  const q=String(message||'').toLowerCase().normalize('NFD')
    .replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9\s]/g,' ').replace(/\s+/g,' ').trim();
  return /^(?:hola|buenos dias|buenas tardes|buenas noches|saludos)(?: mia)?$/.test(q);
}
const BASE_CONTEXT = Object.freeze({
  language: 'es', locale: 'es-ES', company: 'Sunset Beach Club', role: null,
});
const isObject = (item) => item !== null && typeof item === 'object' && !Array.isArray(item);
const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
const SAFE_ROUTES = Object.freeze([
  ['llm', '/api/mia/v4/chat', 'application/json'],
  ['backend-stream', '/api/mia/chat/stream', 'application/x-ndjson'],
  ['backend-json', '/api/mia/chat', 'application/json'],
]);

function meaningful(response) {
  if (!isObject(response)) return false;
  const substantive = ['answer','natural_answer','response','speech','speech_text','data','presentations','visualizations','actions','job'];
  return substantive.some((key) => {
    if (!hasOwn(response,key) || response[key] == null || response[key] === '') return false;
    if (Array.isArray(response[key])) return response[key].length > 0;
    if (isObject(response[key])) return Object.keys(response[key]).length > 0;
    return true;
  });
}

function mergeContext(previous, incoming) {
  if (!isObject(incoming)) return previous;
  const result = {...previous};
  // Preserve the 2D conversational context but never override company/locale
  // with untrusted arrays/objects as whole values. A context field can be
  // structured; the backend supplied it, so retain it without flattening.
  for (const [key, value] of Object.entries(incoming)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    result[key] = value;
  }
  return result;
}

/** The 2D backend places tables/cards in response.data, not presentations. */
export function normalizeHologramApiResult(raw) {
  if (!isObject(raw)) throw new HologramApiError('El servidor no devolvio un objeto de respuesta', 'invalid-result');
  const data = isObject(raw.data) ? raw.data : {};
  const presentations = [];
  const add = (item) => {
    if (isObject(item) && !presentations.includes(item)) presentations.push(item);
  };
  for (const value of [raw.presentations, raw.visualizations, data.visualizations]) {
    if (Array.isArray(value)) value.forEach(add);
    else add(value);
  }
  if (isObject(raw.presentation)) add(raw.presentation);
  if (isObject(data.presentation)) add(data.presentation);
  for (const item of [data.table, raw.table, data.chart, raw.chart]) add(item);
  // Otros formatos del 2D: filas directas, resúmenes y tablas anidadas.
  for (const source of [data,raw]) {
    if (Array.isArray(source.rows) && source.rows.length) {
      add({ title:source.title || source.query_summary?.title || 'Datos recibidos',
        rows:source.rows, columns:source.columns });
    }
    if (Array.isArray(source.results) && source.results.length) {
      add({title:source.title || 'Resultados recibidos',records:source.results});
    }
  }
  if (Array.isArray(data.tables)) data.tables.forEach(add);
  if (Array.isArray(data.charts)) data.charts.forEach(add);
  const summary = {};
  for (const name of ['cards', 'kpis', 'metrics', 'indicators', 'documents', 'records', 'employees', 'people', 'personal', 'items', 'results']) {
    if (hasOwn(data, name) && data[name] != null) summary[name] = data[name];
  }
  // Some responses put records or kpis at the top-level.
  for (const name of ['cards','kpis','metrics','indicators','documents','tables','charts','records','employees','people','personal','items','results']) {
    if (hasOwn(raw, name) && raw[name] != null && !hasOwn(summary, name)) summary[name] = raw[name];
  }
  if (Object.keys(summary).length) add(summary);
  if (Array.isArray(data.comparacion) && data.comparacion.length) {
    add({ title: 'Comparativa recibida', rows: data.comparacion });
  }
  const answer = String(raw.answer || raw.natural_answer || raw.response || raw.speech || raw.speech_text || '');
  const speech = String(raw.speech_text || raw.speech || answer);
  return { ...raw, answer, speech, presentations };
}

/** Create a fresh HG-only context independent of legacy mia.session_id. */
export function createHologramApiContext(initial = {}) {
  let context = mergeContext(BASE_CONTEXT, initial);
  return {
    get value() { return { ...context }; },
    update(raw) { if (isObject(raw?.context)) context = mergeContext(context, raw.context); },
    reset() { context = { ...BASE_CONTEXT }; },
  };
}

function withTimeout(work, ms, parentSignal) {
  const controller = new AbortController();
  let timer;
  let abortListener;
  let timedOut = false;
  const stop = () => controller.abort();
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new HologramApiError('Tiempo de espera del servicio agotado', 'attempt-timeout'));
    }, Math.max(200, ms));
  });
  const cancellation = new Promise((_, reject) => {
    abortListener = () => {
      stop();
      reject(new HologramApiError('Consulta cancelada', 'cancelled'));
    };
    if (parentSignal?.aborted) abortListener();
    else parentSignal?.addEventListener?.('abort', abortListener, {once: true});
  });
  const action = Promise.resolve().then(() => {
    if (controller.signal.aborted) throw new HologramApiError('Consulta cancelada', 'cancelled');
    return work(controller.signal);
  });
  return Promise.race([action, timeout, cancellation]).catch((error) => {
    if (timedOut) throw new HologramApiError('Tiempo de espera del servicio agotado', 'attempt-timeout');
    if (parentSignal?.aborted) throw new HologramApiError('Consulta cancelada', 'cancelled');
    throw error;
  }).finally(() => {
    clearTimeout(timer);
    parentSignal?.removeEventListener?.('abort', abortListener);
    if (!controller.signal.aborted) controller.abort();
  });
}

function traceSafe(callback, value) {
  try { callback(value); } catch (error) { console.warn('[mIA HG] Diagnostico no disponible', error); }
}

async function postJson(url, payload, {fetchImpl, signal, onTrace, route}) {
  traceSafe(onTrace,{phase:'request', event:'fetch-start',requestStarted:true,route});
  const response = await fetchImpl(url, {
    method: 'POST',
    headers:{'Content-Type':'application/json; charset=utf-8', 'Accept':'application/json'},
    body: JSON.stringify(payload), signal, cache: 'no-store',
  });
  traceSafe(onTrace,{phase:'request',event:'http',http:response.status,route});
  if (!response.ok) throw new HologramApiError(`HTTP ${response.status}`, 'http');
  let json;
  try { json = await response.json(); }
  catch { throw new HologramApiError('La respuesta no es JSON valido','invalid-json'); }
  if (!meaningful(json)) throw new HologramApiError('El servidor no devolvio datos finales', 'missing-result');
  return json;
}

async function postNDJSON(url, payload, {fetchImpl, signal, onTrace, route, onProgress}) {
  traceSafe(onTrace,{phase:'request',event:'fetch-start',requestStarted:true,route});
  const response = await fetchImpl(url, {
    method:'POST',
    headers:{'Content-Type':'application/json; charset=utf-8','Accept':'application/x-ndjson'},
    body:JSON.stringify(payload), signal, cache:'no-store',
  });
  traceSafe(onTrace,{phase:'request',event:'http',http:response.status,route});
  if (!response.ok || !response.body) throw new HologramApiError(`HTTP ${response.status}`, 'http');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  const process = (line) => {
    let evt;
    try { evt = JSON.parse(line.trim()); } catch {
      traceSafe(onTrace,{phase:'stream',event:'invalid-ndjson',route});
      return null;
    }
    const type = String(evt?.type || evt?.event || 'unknown').slice(0,24);
    traceSafe(onTrace,{phase:'stream',event:type,route});
    if (type === 'progress') {
      try { onProgress?.(evt); } catch (err) { console.warn('[mIA HG] Progreso no disponible',err); }
      return null;
    }
    if (type === 'error' || type === 'fatal') throw new HologramApiError('El backend devolvio un error', 'backend-error');
    if (type === 'result') {
      const payload = evt.payload || evt.result || evt.data;
      if (meaningful(payload)) return payload;
      traceSafe(onTrace,{phase:'stream',event:'invalid-result',route});
    }
    return null;
  };
  try {
    for (;;) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      if (buffer.length > 5_000_000) throw new HologramApiError('Flujo excesivamente grande','invalid-stream');
      let idx;
      while ((idx = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0,idx).trim();
        buffer = buffer.slice(idx+1);
        if (!line) continue;
        const result = process(line);
        if (result) {
          return result;
        }
      }
      if (done) {
        if (buffer.trim()) {
          const result = process(buffer);
          if (result) {
            return result;
          }
        }
        break;
      }
    }
    throw new HologramApiError('El stream termino sin un resultado','missing-result');
  } finally {
    try { void reader.cancel().catch(() => {}); } catch { /* noop */ }
  }
}

/**
 * One HG turn through 2D-compatible routes. All attempts share the absolute
 * deadline imposed by the caller. Local attempt timeouts permit fallback.
 */
export async function sendHologramVia2D({
  message, contextState = createHologramApiContext(), signal = null,
  fetchImpl = fetch, onTrace = () => {}, onProgress = () => {},
  llmTimeoutMs = 75_000, streamTimeoutMs = 40_000, fallbackTimeoutMs = 20_000,
  routePrefix = '', replyIntegrity = null,
} = {}) {
  const question = String(message || '').trim();
  if (!question) throw new HologramApiError('Consulta vacia', 'invalid-query');
  // Paridad estricta con ask() del 2D (sin routers ni textos locales HG).
  // El contexto y la carga son equivalentes a {...miaProfile, ...context}.
  // Un saludo aislado es neutro: no arrastra un filtro de departamento anterior.
  const requestContext = isSimpleGreeting(question) ?
    {...BASE_CONTEXT} : contextState.value;
  const payload = {message:question,context:requestContext};
  const noRetry = isReportGenerationIntent(question);
  const routes = SAFE_ROUTES;
  const budgets = [llmTimeoutMs,streamTimeoutMs,fallbackTimeoutMs];
  let last = null;
  for (let i=0; i<routes.length; i++) {
    if (signal?.aborted) throw new HologramApiError('Consulta cancelada','cancelled');
    const [route,url,protocol] = routes[i];
    traceSafe(onTrace,{phase:'request',event:'attempt',route});
    try {
      const raw = await withTimeout((attemptSignal) => protocol === 'application/x-ndjson'
        ? postNDJSON(routePrefix+url,payload,{fetchImpl,signal:attemptSignal,onTrace,route,onProgress})
        : postJson(routePrefix+url,payload,{fetchImpl,signal:attemptSignal,onTrace,route}),
      budgets[i], signal);
      // If a replaced turn finishes late, it may NEVER update context or
      // accept a result, even if fetch ignored AbortSignal.
      if (signal?.aborted) throw new HologramApiError('Consulta sustituida', 'cancelled');
      // Never change the conversation context until relevance checks pass.
      const verified = replyIntegrity?.check(question, raw) ||
        {ok:true,code:'-',verification:'unverified'};
      traceSafe(onTrace,{phase:'validation',event:verified.code,
        route,validation:verified.verification});
      if (!verified.ok) {
        throw new HologramApiError(
          'La respuesta no corresponde de forma fiable a la consulta actual',
          verified.code,
        );
      }
      // No inventar un contrato de `data.provenance` que el backend no
      // garantiza: la respuesta válida se trata igual que en el mundo 2D.
      // Las comprobaciones de autorización/datos operativos deben ser servidor.
      const normalized = normalizeHologramApiResult(raw);
      contextState.update(raw);
      replyIntegrity?.commit(question, raw);
      traceSafe(onTrace,{phase:'received',event:'result',route,result:true,
        validation:verified.verification});
      return normalized;
    } catch (error) {
      if (signal?.aborted || error?.code === 'cancelled') throw new HologramApiError('Consulta cancelada','cancelled');
      last = error;
      traceSafe(onTrace,{phase:'fallback',event:String(error?.code || 'network').slice(0,32),route});
      // Un POST que crea un informe puede haberse ejecutado pese a perder la
      // respuesta. Reintentar en otras rutas podría crear PDFs duplicados.
      if (noRetry) {
        traceSafe(onTrace,{phase:'report',event:'non-idempotent-no-retry',route});
        throw new HologramApiError('Estado de informe sin confirmar', 'report-state-uncertain');
      }
      if (i === routes.length - 1) break;
    }
  }
  const suspiciousCodes = ['mismatched-echo','stale-reply'];
  const code = suspiciousCodes.includes(last?.code) ? 'stale-reply' : 'upstream-unavailable';
  throw new HologramApiError(last?.message || 'Ningun servicio entrego un resultado',code);
}

export const HOLOGRAM_COMPAT_ROUTES = SAFE_ROUTES.map(([name,path]) => ({name,path}));
