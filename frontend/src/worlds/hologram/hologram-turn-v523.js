/**
 * mIA Holograma V5.2.2 — transporte SSE LOCAL al holograma.
 * No cambia MiaClient ni el backend. La UI recibe el PRIMER evento result
 * válido, sin esperar al cierre del stream. El lector se cancela al terminar.
 * Un plazo absoluto y otro de inactividad impiden esperas infinitas.
 */
export class HologramTurnError extends Error {
  constructor(message, code = 'request-failed') {
    super(message);
    this.name = 'HologramTurnError';
    this.code = code;
  }
}

function normalizeSSE(block) {
  const lines = String(block).replace(/\r\n?/g, '\n').split('\n');
  let type = 'message';
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  let data;
  try { data = JSON.parse(dataLines.join('\n')); }
  catch { return null; }
  return { type, data };
}

export function parseSSEMessages(chunks) {
  // Utilidad de prueba: reconstruye eventos fragmentados.
  let buffer = '', result = [];
  for (const chunk of chunks) {
    buffer += String(chunk);
    buffer = buffer.replace(/\r\n/g, '\n');
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      const event = normalizeSSE(block);
      if (event) result.push(event);
    }
  }
  return result;
}

function forwardEvent(client, event) {
  if (typeof client._handle === 'function') {
    client._handle(event);
    return;
  }
  if (event.type === 'session' && event.data?.session_id) {
    client.sessionId = event.data.session_id;
    if (client.persistSession && typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('mia.session_id', client.sessionId);
    }
  }
  client.dispatchEvent?.(new CustomEvent(event.type, { detail: event.data }));
}

function getResult(data) {
  if (data?.result && typeof data.result === 'object') return data.result;
  if (data && typeof data === 'object' &&
      ('answer' in data || 'presentations' in data || 'speech' in data)) return data;
  return null;
}

/**
 * @param {object} opts
 * @param {MiaClient} opts.client mantiene la sesión real y los eventos existentes.
 * @param {string} opts.message consulta original sin cambiar su significado.
 * @param {number} opts.timeoutMs plazo máximo. Default 90 segundos.
 * @param {number} opts.inactivityMs máximo sin recibir ningún byte. 35 segundos.
 * @param {Function} opts.fetchImpl inyección para pruebas.
 * @param {AbortSignal} opts.signal señal opcional para cancelar al salir de la página.
 */
export async function sendHologramTurn({
  client, message, timeoutMs = 90000, inactivityMs = 35000,
  fetchImpl = fetch, signal = null, onTrace = () => {},
} = {}) {
  if (!client || !String(message || '').trim()) {
    throw new HologramTurnError('Consulta vacía', 'invalid-query');
  }
  // Trace before dispatching app listeners: if any extension throws, the
  // diagnostic still records that the transport layer was entered.
  onTrace({ phase: 'sending', event: 'entered' });
  client._emit?.('sending', { message });

  const controller = new AbortController();
  let timeoutType = null;
  let finished = false;
  let inactivityTimer = null;
  const stopOnParentAbort = () => {
    timeoutType = 'cancelled';
    controller.abort();
  };
  if (signal) {
    if (signal.aborted) stopOnParentAbort();
    else signal.addEventListener('abort', stopOnParentAbort, { once:true });
  }
  const absoluteTimer = setTimeout(() => {
    if (finished) return;
    timeoutType = 'timeout';
    controller.abort();
  }, Math.max(100, timeoutMs));
  const resetInactivity = () => {
    clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => {
      if (finished) return;
      timeoutType = 'inactivity';
      controller.abort();
    }, Math.max(100, inactivityMs));
  };

  let reader = null;
  try {
    resetInactivity();
    onTrace({ phase: 'sending', event: 'fetch-start', requestStarted: true });
    const response = await fetchImpl(`${client.apiBase || ''}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ message, session_id: client.sessionId }),
      signal: controller.signal,
    });
    onTrace({ phase: 'stream', event: 'http', http: response.status });
    if (!response.ok || !response.body) {
      throw new HologramTurnError(`El servidor devolvió HTTP ${response.status}`, 'http');
    }
    reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const consume = (raw) => {
      const event = normalizeSSE(raw);
      if (!event) {
        onTrace({phase: 'stream', event: 'invalid-sse'});
        return null;
      }
      onTrace({phase: 'stream', event: event.type});
      // Un error del servidor ES un resultado terminal. Antes se ignoraba y
      // Mía seguía pensando hasta agotar el timeout.
      if (event.type === 'error' || event.type === 'fatal') {
        throw new HologramTurnError('El backend ha indicado un error', 'backend-error');
      }
      if (event.type === 'done' || event.type === 'complete') {
        throw new HologramTurnError('El backend terminó sin emitir un resultado', 'missing-result');
      }
      try { forwardEvent(client, event); }
      catch (eventError) {
        console.warn('[HG] Fallo al distribuir evento SSE', eventError);
      }
      if (event.type !== 'result') return null;
      const output = getResult(event.data);
      if (!output) onTrace({phase: 'stream', event: 'result-invalid'});
      else onTrace({phase: 'received', event: 'result'});
      return output;
    };

    while (true) {
      const {value, done} = await reader.read();
      if (done) {
        buffer += decoder.decode();
        buffer = buffer.replace(/\r\n?/g, '\n');
        if (buffer.trim()) {
          const final = consume(buffer);
          if (final) return final;
        }
        break;
      }
      resetInactivity();
      buffer += decoder.decode(value, { stream:true });
      buffer = buffer.replace(/\r\n/g,'\n');
      // Evita acumular indefinidamente basura o un evento malformado.
      if (buffer.length > 5_000_000) {
        throw new HologramTurnError('Respuesta demasiado extensa', 'invalid-stream');
      }
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) {
        const result = consume(block);
        if (result) {
          // NO esperamos a reader.done() tras recibir un resultado válido.
          finished = true;
          return result;
        }
      }
    }
    throw new HologramTurnError('El servidor cerró la respuesta sin datos finales', 'missing-result');
  } catch (error) {
    if (timeoutType === 'timeout' || timeoutType === 'inactivity') {
      throw new HologramTurnError('La consulta ha superado el tiempo de espera', timeoutType);
    }
    if (timeoutType === 'cancelled') {
      throw new HologramTurnError('Consulta cancelada', 'cancelled');
    }
    if (error instanceof HologramTurnError) throw error;
    throw new HologramTurnError('No se ha podido completar la consulta', 'network');
  } finally {
    finished = true;
    clearTimeout(absoluteTimer);
    clearTimeout(inactivityTimer);
    if (signal) signal.removeEventListener('abort', stopOnParentAbort);
    // Cancelar la lectura y soltar la conexión sin bloquear la presentación.
    // AbortSignal cubre implementaciones de ReadableStream que no cancelan.
    controller.abort();
    try { void reader?.cancel()?.catch?.(() => {}); } catch { /* noop */ }
  }
}
