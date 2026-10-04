const CHART_COLORS = [
  'var(--mia-coral)',
  'var(--mia-gold)',
  'var(--mia-burgundy)',
  'var(--mia-success)',
  'var(--mia-warning)',
  '#8e6f61',
  '#d8aa7a',
  '#a78b75'
]

const FRIENDLY_STAT_LABELS = {
  permiso_o_asuntos_propios: 'Permiso / asuntos propios',
  sinturnopublicado: 'Sin turno publicado',
  sin_turno_publicado: 'Sin turno publicado',
  saldomedio: 'Saldo medio',
  saldo_medio: 'Saldo medio',
  consaldonegativo: 'Con saldo negativo',
  con_saldo_negativo: 'Con saldo negativo'
}

function cleanText(value) {
  return String(value ?? '')
    .replace(/\*\*/g, '')
    .replace(/^#+\s*/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function normalizeKey(value) {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_]/g, '')
    .toLowerCase()
}

function friendlyStatLabel(value) {
  const raw = cleanText(value)
  const key = normalizeKey(raw)

  if (FRIENDLY_STAT_LABELS[key]) {
    return FRIENDLY_STAT_LABELS[key]
  }

  const spaced = raw
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

  if (!spaced) return ''

  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function parseNumericToken(value) {
  const match = cleanText(value).match(
    /^(.+?)\s+(-?\d+(?:[.,]\d+)?)\s*(%|€|h|horas?|d[ií]as?)?$/i
  )

  if (!match) return null

  const numeric = Number(match[2].replace(',', '.'))

  if (!Number.isFinite(numeric)) return null

  return {
    label: friendlyStatLabel(match[1]),
    value: numeric,
    unit: match[3] || ''
  }
}

function splitStatFragments(body) {
  return String(body || '')
    .split(/\s*[·•|;]\s*/)
    .map(part => parseNumericToken(part))
    .filter(Boolean)
}

function parseStatisticalSection(source) {
  const text = cleanText(source)
  const colon = text.indexOf(':')

  if (colon <= 0) return null

  const title = cleanText(text.slice(0, colon))
  const body = text.slice(colon + 1)
  const data = splitStatFragments(body)

  if (data.length < 2) return null

  return {
    title,
    data,
    source: text
  }
}

function collectStatisticalSections(answer, insights) {
  const candidates = []

  if (Array.isArray(insights)) {
    for (const insight of insights) {
      const text = typeof insight === 'string'
        ? insight
        : insight?.text || insight?.message || insight?.title || ''

      if (text) candidates.push(text)
    }
  }

  const rawAnswer = String(answer || '')

  if (rawAnswer.includes('✦')) {
    rawAnswer
      .split('✦')
      .map(part => cleanText(part))
      .filter(Boolean)
      .forEach(part => candidates.push(part))
  }

  const seen = new Set()
  const sections = []

  for (const candidate of candidates) {
    const parsed = parseStatisticalSection(candidate)

    if (!parsed) continue

    const key = normalizeKey(parsed.title)
    if (seen.has(key)) continue

    seen.add(key)
    sections.push(parsed)
  }

  return sections
}

function chooseVisualizationType(section) {
  const title = normalizeKey(section.title)
  const labels = section.data.map(item => normalizeKey(item.label))

  if (
    title.includes('vacacion') ||
    labels.some(label => label.includes('saldomedio')) ||
    labels.some(label => label.includes('consaldonegativo'))
  ) {
    return 'metrics'
  }

  if (
    section.data.length <= 7 &&
    (
      title === 'hoy' ||
      title.includes('situacion') ||
      title.includes('estado') ||
      title.includes('distribucionhoy')
    )
  ) {
    return 'donut'
  }

  return 'bars'
}

function normalizeBackendVisualization(viz) {
  if (!viz || !Array.isArray(viz.data) || !viz.data.length) {
    return null
  }

  const typeRaw = String(viz.type || 'bars').toLowerCase()
  const type =
    /pie|donut/.test(typeRaw)
      ? 'donut'
      : /metric|kpi/.test(typeRaw)
        ? 'metrics'
        : 'bars'

  const data = viz.data
    .map((item, index) => {
      const value = Number(
        item?.value ?? item?.total ?? item?.count ?? 0
      )

      if (!Number.isFinite(value)) return null

      return {
        label: cleanText(item?.label || item?.name || `Dato ${index + 1}`),
        value,
        unit: cleanText(item?.unit || '')
      }
    })
    .filter(Boolean)

  if (!data.length) return null

  return {
    type,
    title: cleanText(viz.title || 'Distribución'),
    data,
    source: 'backend'
  }
}

function sectionToVisualization(section) {
  return {
    type: chooseVisualizationType(section),
    title: section.title,
    data: section.data,
    source: section.source
  }
}

export function buildStatisticalPresentation({
  answer = '',
  insights = [],
  visualizations = []
} = {}) {
  const normalizedBackend = Array.isArray(visualizations)
    ? visualizations.map(normalizeBackendVisualization).filter(Boolean)
    : []

  const sections = collectStatisticalSections(answer, insights)
  const existingTitles = new Set(
    normalizedBackend.map(viz => normalizeKey(viz.title))
  )

  const derived = sections
    .filter(section => !existingTitles.has(normalizeKey(section.title)))
    .map(sectionToVisualization)

  const consumed = new Set(
    sections.map(section => normalizeKey(section.source))
  )

  const remainingInsights = Array.isArray(insights)
    ? insights.filter(insight => {
        const text = typeof insight === 'string'
          ? insight
          : insight?.text || insight?.message || insight?.title || ''
        return !consumed.has(normalizeKey(cleanText(text)))
      })
    : []

  const answerWasStatistical =
    derived.length > 0 &&
    (
      String(answer || '').includes('✦') ||
      /\bclaves\b|\blo mas relevante\b/i.test(String(answer || ''))
    )

  return {
    visualizations: [...normalizedBackend, ...derived].slice(0, 6),
    insights: remainingInsights,
    answerWasStatistical,
    hasDerived: derived.length > 0
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function formatNumber(value) {
  return new Intl.NumberFormat('es-ES', {
    maximumFractionDigits: 2
  }).format(value)
}

function renderSectionTitle(title, kicker = 'VISUALIZACIÓN') {
  return `
    <div class="v151-section-title">
      <div>
        <span>${escapeHtml(kicker)}</span>
        <h3>${escapeHtml(title)}</h3>
      </div>
    </div>
  `
}

function renderBars(viz) {
  const values = viz.data.map(item => Math.max(0, Number(item.value) || 0))
  const max = Math.max(1, ...values)
  const denseClass = viz.data.length > 7 ? ' is-dense' : ''

  return `
    <section class="v151-chart v154-chart v154-chart-bars reveal-item">
      ${renderSectionTitle(viz.title)}
      <div class="v154-bars${denseClass}">
        ${viz.data.map((item, index) => {
          const value = values[index]
          const width = Math.max(value > 0 ? 2.5 : 0, (value / max) * 100)
          return `
            <div class="v154-bar-item">
              <div class="v154-bar-copy">
                <span title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
                <strong>${escapeHtml(formatNumber(value))}${item.unit ? ` <small>${escapeHtml(item.unit)}</small>` : ''}</strong>
              </div>
              <div class="v154-bar-track" aria-hidden="true">
                <i style="--bar-width:${width}%"></i>
              </div>
            </div>
          `
        }).join('')}
      </div>
    </section>
  `
}

function renderDonut(viz) {
  const data = viz.data.filter(item => Number(item.value) > 0)
  const total = data.reduce((sum, item) => sum + Number(item.value || 0), 0)

  if (!total) return renderBars(viz)

  let cursor = 0
  const segments = data.map((item, index) => {
    const start = cursor
    cursor += (Number(item.value) / total) * 100
    const color = CHART_COLORS[index % CHART_COLORS.length]
    return `${color} ${start.toFixed(3)}% ${cursor.toFixed(3)}%`
  })

  return `
    <section class="v151-chart v154-chart v154-chart-donut reveal-item">
      ${renderSectionTitle(viz.title)}
      <div class="v154-donut-layout">
        <div class="v154-donut" style="background:conic-gradient(${segments.join(',')})">
          <div class="v154-donut-hole">
            <strong>${escapeHtml(formatNumber(total))}</strong>
            <span>Total</span>
          </div>
        </div>
        <div class="v154-donut-legend">
          ${data.map((item, index) => {
            const percentage = (Number(item.value) / total) * 100
            const color = CHART_COLORS[index % CHART_COLORS.length]
            return `
              <div class="v154-legend-item">
                <i style="--legend-color:${color}"></i>
                <span>${escapeHtml(item.label)}</span>
                <strong>${escapeHtml(formatNumber(item.value))}</strong>
                <small>${escapeHtml(percentage.toFixed(percentage >= 10 ? 0 : 1).replace('.', ','))}%</small>
              </div>
            `
          }).join('')}
        </div>
      </div>
    </section>
  `
}

function renderMetrics(viz) {
  return `
    <section class="v151-chart v154-chart v154-chart-metrics reveal-item">
      ${renderSectionTitle(viz.title, 'INDICADORES')}
      <div class="v154-metric-grid">
        ${viz.data.map(item => `
          <article class="v154-metric">
            <span>${escapeHtml(item.label)}</span>
            <div>
              <strong>${escapeHtml(formatNumber(item.value))}</strong>
              ${item.unit ? `<small>${escapeHtml(item.unit)}</small>` : ''}
            </div>
          </article>
        `).join('')}
      </div>
    </section>
  `
}

export function renderStatisticalVisualizations(visualizations) {
  if (!Array.isArray(visualizations) || !visualizations.length) {
    return ''
  }

  return visualizations
    .slice(0, 6)
    .map(viz => {
      if (viz.type === 'donut') return renderDonut(viz)
      if (viz.type === 'metrics') return renderMetrics(viz)
      return renderBars(viz)
    })
    .join('')
}
