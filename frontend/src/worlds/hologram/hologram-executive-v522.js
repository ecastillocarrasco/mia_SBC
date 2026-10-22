/**
 * Contrato ejecutivo exclusivo del holograma: brevedad, sin inventar totales.
 * Los datos del backend siguen siendo la fuente de verdad; no altera la consulta.
 */
const string = (value) => String(value ?? '').replace(/\s+/gu, ' ').trim();
const isObject = (value) => value && typeof value === 'object' && !Array.isArray(value);
const number = (value) => {
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? value : null;
  const raw = string(value);
  if (!/^[\d.,]+$/.test(raw)) return null;
  const parsed = Number(raw.includes(',') ? raw.replace(/\./g,'').replace(',','.') : raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
};

export function isWorkingNowQuestion(question) {
  const q = string(question).toLowerCase();
  // No convertimos "quién trabajó ayer" o "mañana" en un total de hoy.
  const now = /ahora|este momento|actualmente|en este instante|en servicio|de turno|hoy/iu.test(q);
  const workers = /emplead|trabajador|personal|plantilla|gente|qui[eé]n|cu[aá]ntos/iu.test(q);
  return now && workers && /trabaj|en servicio|de turno|turno|presente/iu.test(q);
}

function metricEntries(response, presentations) {
  const entries = [];
  const sources = [response, ...(presentations || [])].filter(isObject);
  const put = (label, value, unit) => {
    if (value === null || value === undefined) return;
    const n = number(value);
    if (n === null) return;
    entries.push({ label: string(label), value: n, unit: string(unit) });
  };
  for (const source of sources) {
    for (const property of ['working_now','staff_working_now','currently_working','on_duty_count']) {
      if (Object.prototype.hasOwnProperty.call(source, property)) {
        put('Trabajando ahora', source[property]);
      }
    }
    if (/^(metric|kpi)$/iu.test(source.type || '')) {
      put(source.label || source.title || '', source.value, source.unit);
    }
    for (const group of ['kpis','metrics','indicators','cards']) {
      const value = source[group];
      if (Array.isArray(value)) {
        for (const row of value) {
          if (isObject(row)) put(row.label || row.title || row.name || '',
            row.value ?? row.count ?? row.amount, row.unit);
        }
      } else if (isObject(value)) {
        for (const [key, row] of Object.entries(value)) {
          if (isObject(row)) put(row.label || row.title || key,
            row.value ?? row.count ?? row.amount, row.unit);
          else put(key, row);
        }
      }
    }
  }
  return entries;
}

export function confirmedWorkforceTotal(response, presentations) {
  // Etiquetas/valores en tarjetas KPI NO certifican por si solos que sean
  // totales reales de personal en servicio. No inventar una certificacion.
  const explicitlyVerified = response?.verified === true ||
    response?.data?.verified === true || response?.verification?.status === 'verified';
  if (!explicitlyVerified) return null;
  for (const entry of metricEntries(response,presentations)) {
    const label = entry.label.toLowerCase();
    if (/no\s+trabaj|ausent|vacacion|descans|\bbaja\b|\blibre\b/iu.test(label)) continue;
    if (/trabajando(?:\s+ahora)?|personal\s+en\s+servicio|empleados\s+en\s+servicio|en\s+turno|de\s+servicio|on\s+duty/iu.test(label)
        && Number.isInteger(entry.value)) return entry.value;
  }
  return null;
}

export function compactVoice(raw, maxChars = 360) {
  const text = string(raw);
  if (!text) return '';
  if (text.length <= maxChars) return text;
  // Preferimos frases completas, antes que truncar silenciosamente una cifra.
  const fragments = text.match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/gu) || [text];
  let selected = '';
  for (const part of fragments) {
    if ((selected + part).length > maxChars) break;
    selected += part;
    if (selected.trim().length >= maxChars * .55) break;
  }
  if (selected.trim()) return selected.trim();
  // Último recurso: primer segmento semántico completo, aunque sea algo largo.
  return fragments[0].trim();
}

export function hologramExecutiveCopy({ question, response, presentations = [] } = {}) {
  // La respuesta del backend es SIEMPRE la fuente de verdad -- la misma que verían 2D/3D para la
  // misma pregunta (directiva del holograma: responde exactamente lo mismo, solo cambia cómo se
  // muestra). Antes, si la pregunta parecía de personal "trabajando ahora" y el backend no marcaba
  // `verified:true` (nunca lo hace hoy: ningún código del backend fija ese campo), esto DESCARTABA
  // la respuesta real y la sustituía por un aviso genérico de "no puedo confirmar" -- se disparaba
  // el 100% de las veces, no como salvaguarda ocasional. Ahora esa respuesta real siempre se
  // muestra (resumida igual que cualquier otra pregunta); lo único que puede añadirse es una cifra
  // confirmada como dato destacado, nunca en sustitución del texto real.
  const reported = string(response?.speech_text || response?.speech || response?.answer || response?.natural_answer);
  const working = isWorkingNowQuestion(question);
  const summary = compactVoice(reported);
  const base = {
    caption: summary || 'No se han recibido datos suficientes para mostrar un resumen.',
    speech: summary || 'No he recibido información suficiente para responder a esa consulta. Puedes intentarlo de nuevo.',
    working, confirmed: false, value: null,
  };
  if (!working) return base;
  const total = confirmedWorkforceTotal(response, presentations);
  return total === null ? base : { ...base, confirmed: true, value: total };
}
