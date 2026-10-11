/**
 * mIA V4.2 — Progreso legible para personas.
 * Un estado técnico jamás se muestra literalmente. Los mensajes ya redactados
 * para el usuario se mantienen; se descartan trazas, rutas e identificadores.
 * No inventar el proceso o fuente que está utilizando el backend.
 */
const STATUS = Object.freeze({
  analisis_financiero: "Estoy tramitando tu solicitud.",
  analisis_economico: "Estoy tramitando tu solicitud.",
  analisis_economico_nominas: "Estoy tramitando tu solicitud.",
  consultando_sql: "Estoy consultando la información que necesitas.",
  buscando_empleados: "Estoy revisando los datos disponibles.",
  generando_informe: "Estoy preparando el informe solicitado.",
  calculando_estadisticas: "Estoy organizando los resultados para presentártelos.",
  procesando_llm: "Estoy preparando una respuesta para ti.",
  esperando_backend: "La consulta sigue en curso. Gracias por esperar.",
  tool_call: "Estoy atendiendo tu consulta.",
  tool_result: "Estoy preparando el resultado.",
  searching: "Estoy buscando información para responderte.",
  thinking: "Estoy revisando tu consulta.",
  loading: "Estoy preparando la información.",
  pending: "Estoy tramitando tu solicitud.",
});

const TECHNICAL = /(?:traceback|stacktrace|exception|select\s+.+\s+from|sqlstate|\/api\/|https?:\/\/\S+|[a-z]:\\|\.py\b|\.js\b|token\s*=|secret\s*=|password\s*=|Bearer\s+\S+|tool[_\s-]?name|[_{}[\]\\])/i;
const CAMEL_CASE = /(?:[a-z]+[A-Z][a-z]+){2}/;

function normalize(value) {
  return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

export function friendlyProgress(raw, fallback = "Estoy tramitando tu solicitud.") {
  if (raw && typeof raw === "object") {
    return friendlyProgress(raw.message ?? raw.label ?? raw.state ?? raw.status ?? raw.step ?? "", fallback);
  }
  const text = String(raw ?? "").trim();
  if (!text) return fallback;
  const alias = STATUS[normalize(text)];
  if (alias) return alias;
  // Any path, module identifier or debug-like string remains internal.
  if (TECHNICAL.test(text) || CAMEL_CASE.test(text) || /^[a-z0-9]+(?:_[a-z0-9]+){1,}$/i.test(text))
    return fallback;
  // A backend sentence is user-visible only if it resembles ordinary prose.
  const words = text.split(/\s+/);
  if (words.length >= 3 && text.length <= 220 && !/[<>]/.test(text)) return text;
  return fallback;
}

export const FRIENDLY_PROGRESS_ALIASES = STATUS;
