const IMPORTANT_TYPES = new Set([
  'employee360',
  'analytics',
  'comparison',
  'department',
  'shifts',
  'document'
])

const SUMMARY_RE = /\b(resum|resumen|resume|resumeme|sintesis|sintetiza|informe|report|conclusiones|conclusion|recap|puntos clave)\b/i

const TYPE_PLANS = {
  employee360: {
    variant: 'person',
    intro: ['mIA_GREET', 'mIA_YES'],
    reveal: ['mIA_POINT', 'mIA_AGREE'],
    follow: ['mIA_AGREE', 'mIA_YES'],
    accent: 'sunset'
  },
  scalar: {
    variant: 'metric',
    intro: ['mIA_YES', 'mIA_AGREE'],
    reveal: ['mIA_YES', 'mIA_POINT'],
    accent: 'gold'
  },
  person: {
    variant: 'person',
    intro: ['mIA_GREET', 'mIA_YES'],
    reveal: ['mIA_POINT', 'mIA_AGREE'],
    accent: 'coral'
  },
  department: {
    variant: 'analytics',
    intro: ['mIA_THINK', 'mIA_LOOK_AROUND'],
    reveal: ['mIA_POINT', 'mIA_AGREE'],
    follow: ['mIA_AGREE', 'mIA_YES'],
    accent: 'sunset'
  },
  analytics: {
    variant: 'analytics',
    intro: ['mIA_THINK', 'mIA_LOOK_AROUND'],
    reveal: ['mIA_POINT', 'mIA_AGREE'],
    follow: ['mIA_AGREE', 'mIA_YES'],
    accent: 'sunset'
  },
  comparison: {
    variant: 'comparison',
    intro: ['mIA_AGREE', 'mIA_THINK'],
    reveal: ['mIA_POINT', 'mIA_AGREE'],
    follow: ['mIA_YES', 'mIA_AGREE'],
    accent: 'burgundy'
  },
  shifts: {
    variant: 'operations',
    intro: ['mIA_LOOK_AROUND', 'mIA_LOOK_AROUND_ALT', 'mIA_THINK'],
    reveal: ['mIA_POINT', 'mIA_AGREE'],
    follow: ['mIA_YES', 'mIA_AGREE'],
    accent: 'coral'
  },
  list: {
    variant: 'list',
    intro: ['mIA_LOOK_AROUND_ALT', 'mIA_LOOK_AROUND', 'mIA_THINK'],
    reveal: ['mIA_POINT', 'mIA_YES'],
    accent: 'gold'
  },
  document: {
    variant: 'document',
    intro: ['mIA_TYPING', 'mIA_THINK'],
    reveal: ['mIA_CLAP', 'mIA_YES'],
    follow: ['mIA_AGREE', 'mIA_YES'],
    accent: 'gold'
  },
  text: {
    variant: 'summary',
    intro: ['mIA_AGREE', 'mIA_THINK'],
    reveal: ['mIA_POINT', 'mIA_YES'],
    accent: 'sunset'
  }
}

function getTableRows(presentation) {
  return Number(presentation?.table?.rows?.length || 0)
}

function getVisualCount(presentation) {
  return Number(presentation?.visualizations?.length || 0)
}

function getCardCount(presentation) {
  return Number(presentation?.cards?.length || 0)
}

function getInsightCount(presentation) {
  return Number(presentation?.insights?.length || 0)
}

export function buildPresentationPerformance({
  presentation,
  query = '',
  mobile = false,
  reducedMotion = false
} = {}) {
  const type = presentation?.type || 'text'
  const base = TYPE_PLANS[type] || TYPE_PLANS.text

  let score = 0

  if (IMPORTANT_TYPES.has(type)) score += 2
  if (getVisualCount(presentation) > 0) score += 2
  if (getCardCount(presentation) >= 3) score += 1
  if (getTableRows(presentation) >= 8) score += 1
  if (getInsightCount(presentation) >= 2) score += 1
  if (SUMMARY_RE.test(String(query || ''))) score += 1

  const featured = !reducedMotion && score >= 3
  const spectacular = !reducedMotion && score >= 5

  const speed = mobile ? 0.78 : 1

  return {
    type,
    variant: base.variant,
    accent: base.accent,
    importanceScore: score,
    featured,
    spectacular,
    introAnimations: base.intro || [],
    revealAnimations: base.reveal || [],
    followAnimations: base.follow || [],
    introMs: Math.round((spectacular ? 620 : featured ? 420 : 120) * speed),
    revealMs: Math.round((spectacular ? 360 : featured ? 260 : 140) * speed),
    postRevealMs: Math.round((spectacular ? 420 : featured ? 260 : 120) * speed),
    gestureWeight: spectacular ? 0.88 : featured ? 0.80 : 0.72,
    statusText: getPerformanceStatus(type, featured)
  }
}

function getPerformanceStatus(type, featured) {
  if (!featured) return 'Ya lo tengo. Te lo muestro.'

  const labels = {
    employee360: 'Tengo la ficha completa preparada. Te la muestro.',
    analytics: 'He cruzado los datos. Te enseño lo más relevante.',
    department: 'He analizado el conjunto. Te muestro las claves.',
    comparison: 'He preparado la comparativa. Vamos a verla.',
    shifts: 'He ordenado la operativa. Te la presento.',
    document: 'He preparado el resultado. Te lo presento.',
    list: 'He organizado los resultados. Te los muestro.',
    person: 'Tengo la ficha preparada. Te la muestro.',
    scalar: 'Ya tengo el dato.',
    text: 'He sintetizado la información. Te la presento.'
  }

  return labels[type] || 'He preparado el resultado. Te lo presento.'
}
