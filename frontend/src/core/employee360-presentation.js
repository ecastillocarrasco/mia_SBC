const TECHNICAL_KEYS = new Set([
  'scope', 'history_loaded', 'metodo_busqueda', 'principles',
  'FechaAltaEstado', 'FechaAltaNota', 'DatosContactoVisibilidad',
  'MailsDepartamento', 'Mails Departamento', 'Mails_Departamento',
  'EmailsDepartamento', 'Emails', 'Mails'
])

function isObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

const E360_URL_RX = /^(https?:\/\/|\/api\/)/

function isApiUrl(value) {
  return typeof value === 'string' && E360_URL_RX.test(value.trim())
}

function urlLabelE360(url) {
  if (/\/api\/documents\/nomina\//.test(url)) return 'Ver nómina'
  if (/\/api\/documents\/cv\//.test(url)) return 'Ver CV'
  if (/\/api\/documents\//.test(url)) return 'Abrir documento'
  if (/\/api\/reports\//.test(url)) return 'Descargar'
  return 'Ver'
}

function renderApiLink(url) {
  return `<a class="mia-doc-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(urlLabelE360(url))}</a>`
}

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function clean(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  if (typeof value === 'number') {
    return new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 }).format(value)
  }
  return String(value).trim()
}

function prettyKey(key) {
  const raw = String(key || '')
    .replace(/[_-]+/g, ' ')
    .replace(/([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])/g, '$1 $2')
    .trim()
  if (!raw) return ''
  return raw.charAt(0).toUpperCase() + raw.slice(1)
}

function employee360Root(data) {
  return isObject(data?.employee360) ? data.employee360 : data
}

export function isEmployee360Payload(payload = {}, data = {}) {
  const nativePresentation = isObject(data?.presentation) ? data.presentation : null
  const intent = `${payload?.intent || ''} ${data?.intent || ''}`.toLowerCase()
  const domain = `${payload?.domain || ''} ${data?.domain || ''}`.toLowerCase()

  return Boolean(
    nativePresentation?.schema === 'mia.employee360.presentation' ||
    isObject(data?.employee360) ||
    data?.employee360_version ||
    intent.includes('employee360') ||
    domain.includes('employee360') ||
    (
      isObject(data?.empleado) &&
      (
        isObject(data?.turnos_inteligentes) ||
        isObject(data?.vacaciones_inteligentes) ||
        isObject(data?.datos_laborales)
      )
    )
  )
}

function describeShift(value) {
  if (!isObject(value)) return clean(value)
  const parts = [
    value.Turno || value.Tipo,
    value.Inicio && value.Fin ? `${value.Inicio}–${value.Fin}` : '',
    value.Area || value.Departamento
  ].map(clean).filter(Boolean)
  return parts.join(' · ')
}

function describeVacation(value) {
  if (!isObject(value)) return clean(value)
  const start = clean(value.FechaInicio || value.Inicio)
  const end = clean(value.FechaFin || value.Fin)
  const days = clean(value.Dias ?? value.Días)
  const state = clean(value.Estado)
  return [start && end ? `${start} – ${end}` : start || end, days ? `${days} días` : '', state]
    .filter(Boolean)
    .join(' · ')
}

function fallbackPresentation(data) {
  const root = employee360Root(data)
  if (!isObject(root)) return null

  const emp = isObject(root.empleado) ? root.empleado : {}
  const labor = isObject(root.datos_laborales) ? root.datos_laborales : {}
  const org = isObject(root.organizacion)
    ? root.organizacion
    : isObject(root.contexto_organizativo)
      ? root.contexto_organizativo
      : {}
  const shifts = isObject(root.turnos_inteligentes) ? root.turnos_inteligentes : {}
  const vac = isObject(root.vacaciones_inteligentes) ? root.vacaciones_inteligentes : {}
  const saldo = isObject(root.saldo_vacaciones) ? root.saldo_vacaciones : {}
  const absence = isObject(root.bajas) ? root.bajas : {}
  const pay = isObject(root.nominas) ? root.nominas : {}
  const docs = isObject(root.documentos_firmados) ? root.documentos_firmados : {}

  const name = clean(emp.Nombre || root.nombre_empleado || root.Empleado)
  if (!name) return null

  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0] || '')
    .join('')
    .toUpperCase()

  const timeline = []
  if (vac.proxima) {
    timeline.push({
      title: 'Próximas vacaciones',
      subtitle: describeVacation(vac.proxima),
      display_date: clean(vac.proxima?.FechaInicio || vac.proxima?.Inicio),
      state: 'vacation'
    })
  }
  if (shifts.proximo_turno) {
    timeline.push({
      title: 'Próximo turno',
      subtitle: describeShift(shifts.proximo_turno),
      display_date: clean(shifts.proximo_turno?.Fecha),
      state: 'work'
    })
  }
  if (shifts.proximo_dia_libre) {
    timeline.push({
      title: 'Próximo descanso',
      subtitle: describeShift(shifts.proximo_dia_libre),
      display_date: clean(shifts.proximo_dia_libre?.Fecha),
      state: 'rest'
    })
  }

  return {
    schema: 'mia.employee360.presentation',
    version: 'frontend-3d-fallback-1',
    layout: 'employee_360_premium',
    hero: {
      title: name,
      subtitle: [emp.Puesto, emp.Departamento].map(clean).filter(Boolean).join(' · '),
      initials,
      status: emp.Activo === false ? 'inactive' : 'active',
      badges: [emp.Puesto, emp.Departamento, org.Seccion].map(clean).filter(Boolean)
    },
    kpis: [
      {
        id: 'status',
        label: 'Situación',
        value: labor.Situacion || (emp.Activo === false ? 'Inactivo' : 'Activo'),
        variant: 'success'
      },
      {
        id: 'shift_today',
        label: 'Turno hoy',
        value: shifts?.hoy?.Turno || shifts?.hoy?.Tipo || 'Sin turno publicado',
        variant: 'primary'
      },
      {
        id: 'vacation_balance',
        label: 'Saldo vacaciones',
        value: saldo.SaldoActual,
        unit: 'días',
        variant: 'info'
      },
      {
        id: 'latest_payroll',
        label: 'Última nómina',
        value: pay.periodo_ultima || pay?.ultima?.Periodo || pay?.ultima?.periodo || '—',
        variant: 'neutral'
      }
    ],
    sections: [
      {
        id: 'today',
        title: 'Hoy',
        layout: 'spotlight',
        data: {
          turno: shifts.hoy,
          baja_actual: absence.actual,
          vacaciones_actuales: vac.actual
        }
      },
      {
        id: 'week',
        title: 'Semana actual',
        layout: 'week_strip',
        items: Array.isArray(shifts.semana_actual) ? shifts.semana_actual : []
      },
      {
        id: 'next',
        title: 'Próximos hitos',
        layout: 'timeline',
        items: timeline
      },
      {
        id: 'employment',
        title: 'Ficha laboral',
        layout: 'definition_grid',
        data: labor
      },
      {
        id: 'organization',
        title: 'Organización',
        layout: 'people_chips',
        data: org
      },
      {
        id: 'vacations',
        title: 'Vacaciones',
        layout: 'metric_detail',
        data: { saldo, ...vac }
      },
      {
        id: 'absence',
        title: 'Bajas',
        layout: 'metric_detail',
        data: absence
      },
      {
        id: 'documents',
        title: 'Documentación y nóminas',
        layout: 'compact_cards',
        data: { nominas: pay, documentos_firmados: docs }
      }
    ],
    quick_actions: [
      { id: 'shifts', label: 'Ver turnos', prompt: 'Muéstrame sus turnos' },
      { id: 'vacations', label: 'Ver vacaciones', prompt: 'Muéstrame sus vacaciones' },
      { id: 'absence', label: 'Ver bajas', prompt: 'Muéstrame sus bajas' },
      { id: 'payroll', label: 'Ver nóminas', prompt: 'Muéstrame sus nóminas' },
      { id: 'documents', label: 'Ver documentos', prompt: 'Muéstrame sus documentos' }
    ]
  }
}

export function buildEmployee360Presentation(data = {}) {
  const nativePresentation = isObject(data?.presentation) ? data.presentation : null
  if (nativePresentation?.schema === 'mia.employee360.presentation') {
    return nativePresentation
  }
  return fallbackPresentation(data)
}

function primitiveEntries(obj, limit = 18) {
  if (!isObject(obj)) return []
  const rows = []
  for (const [key, value] of Object.entries(obj)) {
    if (rows.length >= limit) break
    if (TECHNICAL_KEYS.has(key)) continue
    if (value === null || value === undefined || value === '') continue
    if (typeof value === 'object') continue
    rows.push({ label: prettyKey(key), value: clean(value) })
  }
  return rows
}

function flattenComplete(root, prefix = '', out = [], depth = 0) {
  if (!isObject(root) || depth > 3 || out.length >= 80) return out

  for (const [key, value] of Object.entries(root)) {
    if (out.length >= 80) break
    if (TECHNICAL_KEYS.has(key)) continue
    const label = prefix ? `${prefix} · ${prettyKey(key)}` : prettyKey(key)

    if (value === null || value === undefined || value === '') continue

    if (Array.isArray(value)) {
      if (!value.length) continue
      if (value.every(item => item === null || typeof item !== 'object')) {
        out.push({ label, value: value.map(clean).filter(Boolean).join(', ') })
      }
      continue
    }

    if (isObject(value)) {
      flattenComplete(value, label, out, depth + 1)
      continue
    }

    out.push({ label, value: clean(value) })
  }

  return out
}

function renderDefinitionGrid(entries) {
  if (!entries.length) return '<div class="e360x-empty">Sin datos disponibles.</div>'
  return `<div class="e360x-defs">${entries.map(item => {
    const valueHtml = isApiUrl(item.value) ? renderApiLink(item.value) : `<strong>${esc(item.value)}</strong>`
    return `<div class="e360x-def">
      <span>${esc(item.label)}</span>
      ${valueHtml}
    </div>`
  }).join('')}</div>`
}

function renderSpotlight(data) {
  if (!isObject(data)) return '<div class="e360x-empty">Sin información para hoy.</div>'
  const rows = []
  if (data.turno) rows.push({ label: 'Turno', value: describeShift(data.turno) })
  if (data.baja_actual) rows.push({ label: 'Baja actual', value: clean(data.baja_actual?.Tipo || data.baja_actual?.Estado || data.baja_actual) })
  if (data.vacaciones_actuales) rows.push({ label: 'Vacaciones', value: describeVacation(data.vacaciones_actuales) })
  return renderDefinitionGrid(rows.filter(row => row.value))
}

function renderWeek(items) {
  if (!Array.isArray(items) || !items.length) return '<div class="e360x-empty">No hay semana publicada.</div>'
  return `<div class="e360x-week">${items.slice(0, 7).map(item => `
    <article class="e360x-day">
      <span>${esc(clean(item?.Fecha || item?.FechaISO || 'Día'))}</span>
      <strong>${esc(clean(item?.Turno || item?.Tipo || '—'))}</strong>
      <small>${esc(clean(item?.Area || item?.Departamento || ''))}</small>
    </article>`).join('')}</div>`
}

function renderTimeline(items) {
  if (!Array.isArray(items) || !items.length) return '<div class="e360x-empty">Sin próximos hitos.</div>'
  return `<div class="e360x-timeline">${items.slice(0, 8).map(item => `
    <div class="e360x-event">
      <span>${esc(clean(item?.display_date || item?.date || ''))}</span>
      <div><strong>${esc(clean(item?.title || 'Hito'))}</strong><small>${esc(clean(item?.subtitle || ''))}</small></div>
    </div>`).join('')}</div>`
}

function collectPeople(data) {
  const people = []
  const push = value => {
    const name = isObject(value)
      ? clean(value.nombre || value.Nombre || value.Title || value.DisplayName || value.Empleado)
      : clean(value)
    if (name && !people.includes(name)) people.push(name)
  }

  if (!isObject(data)) return people

  push(data.ResponsableDirecto)
  for (const key of ['Responsables', 'responsables', 'ResponsablesDepartamento', 'responsables_departamento']) {
    const value = data[key]
    if (Array.isArray(value)) value.forEach(push)
  }

  return people
}

function renderPeople(data) {
  const people = collectPeople(data)
  const dep = clean(data?.Departamento || data?.departamento)
  if (!people.length) {
    const entries = primitiveEntries(data, 12)
    return entries.length ? renderDefinitionGrid(entries) : '<div class="e360x-empty">Sin información organizativa.</div>'
  }
  return `<div class="e360x-people">${people.map((name, index) => `
    <span class="e360x-person${index === 0 ? ' direct' : ''}">${esc(name)}</span>`).join('')}</div>
    ${dep ? `<p class="e360x-note">Responsables asociados a ${esc(dep)}.</p>` : ''}`
}

function renderMetrics(data) {
  if (!isObject(data)) return '<div class="e360x-empty">Sin datos disponibles.</div>'
  const blocks = []
  for (const [key, value] of Object.entries(data)) {
    if (blocks.length >= 12) break
    if (TECHNICAL_KEYS.has(key) || value === null || value === undefined || value === '') continue

    if (isObject(value)) {
      const summary = primitiveEntries(value, 5)
      if (summary.length) {
        blocks.push({
          label: prettyKey(key),
          value: summary.map(item => `${item.label}: ${item.value}`).join(' · ')
        })
      }
      continue
    }

    if (Array.isArray(value)) {
      if (value.length) blocks.push({ label: prettyKey(key), value: `${value.length} registros` })
      continue
    }

    blocks.push({ label: prettyKey(key), value: clean(value) })
  }
  return renderDefinitionGrid(blocks)
}

function renderSection(section) {
  if (!isObject(section)) return ''
  const title = clean(section.title || prettyKey(section.id) || 'Detalle')
  const layout = clean(section.layout)
  let body = ''

  if (layout === 'spotlight') body = renderSpotlight(section.data)
  else if (layout === 'week_strip') body = renderWeek(section.items)
  else if (layout === 'timeline') body = renderTimeline(section.items)
  else if (layout === 'definition_grid') body = renderDefinitionGrid(primitiveEntries(section.data, 18))
  else if (layout === 'people_chips') body = renderPeople(section.data)
  else body = renderMetrics(section.data)

  return `<section class="e360x-section">
    <header><span>${esc(title)}</span></header>
    <div class="e360x-section-body">${body}</div>
  </section>`
}


function employeeActionPrompt(action, employeeName) {
  const id = clean(action?.id).toLowerCase()
  const sourcePrompt = clean(action?.prompt)
  const name = clean(employeeName)

  if (!name) return sourcePrompt

  const prompts = {
    shifts: `Muéstrame los turnos de ${name}`,
    vacations: `Muéstrame las vacaciones de ${name}`,
    absence: `Muéstrame las bajas y ausencias de ${name}`,
    payroll: `Muéstrame las nóminas de ${name}`,
    documents: `Muéstrame los documentos firmados de ${name}`
  }

  if (prompts[id]) return prompts[id]

  if (!sourcePrompt) return ''

  if (new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(sourcePrompt)) {
    return sourcePrompt
  }

  if (/\b(sus?|de esta persona|del empleado|de la empleada)\b/i.test(sourcePrompt)) {
    return `${sourcePrompt.replace(/[.!?]+$/, '')} de ${name}`
  }

  return sourcePrompt
}

export function renderEmployee360PresentationHtml(presentation, data = {}, answer = '') {
  if (!presentation || presentation.schema !== 'mia.employee360.presentation') return ''

  const hero = isObject(presentation.hero) ? presentation.hero : {}
  const name = clean(hero.title || 'Ficha de empleado')
  const subtitle = clean(hero.subtitle || 'Employee360')
  const initials = clean(hero.initials) || name.split(/\s+/).slice(0, 2).map(x => x[0] || '').join('').toUpperCase()
  const badges = Array.isArray(hero.badges) ? [...new Set(hero.badges.map(clean).filter(Boolean))] : []
  const kpis = Array.isArray(presentation.kpis) ? presentation.kpis.filter(isObject).slice(0, 8) : []
  const sections = Array.isArray(presentation.sections) ? presentation.sections.filter(isObject) : []
  const actions = Array.isArray(presentation.quick_actions) ? presentation.quick_actions.filter(isObject).slice(0, 8) : []
  const root = employee360Root(data)
  const complete = flattenComplete(root).slice(0, 80)

  return `
    <div class="e360x">
      <header class="e360x-hero">
        <div class="e360x-avatar">${esc(initials || 'E')}</div>
        <div class="e360x-hero-copy">
          <h2>${esc(name)}</h2>
          <p>${esc(subtitle)}</p>
          ${badges.length ? `<div class="e360x-badges">${badges.map(b => `<span>${esc(b)}</span>`).join('')}</div>` : ''}
        </div>
        <div class="e360x-status${hero.status === 'inactive' ? ' inactive' : ''}">
          <i></i>${hero.status === 'inactive' ? 'Inactivo' : 'Activo'}
        </div>
        <button class="backend-result-close e360x-close" type="button" aria-label="Cerrar resultado">×</button>
      </header>

      <div class="e360x-body">
        ${answer ? `<section class="e360x-answer"><span>mIA</span><p>${esc(answer)}</p></section>` : ''}

        ${kpis.length ? `<section class="e360x-kpis">${kpis.map(kpi => `
          <article class="${esc(clean(kpi.variant))}">
            <span>${esc(clean(kpi.label || 'Dato'))}</span>
            <strong>${esc(clean(kpi.value) || '—')}${kpi.unit ? `<small>${esc(clean(kpi.unit))}</small>` : ''}</strong>
          </article>`).join('')}</section>` : ''}

        ${sections.length ? `<div class="e360x-sections">${sections.map(renderSection).join('')}</div>` : ''}

        ${complete.length ? `<details class="e360x-complete" open>
          <summary><span>Resumen completo de la ficha</span><small>${complete.length} datos</small></summary>
          <div>${renderDefinitionGrid(complete)}</div>
        </details>` : ''}

        ${actions.length ? `<div class="e360x-actions">${actions.map(action => {
          const prompt = employeeActionPrompt(action, name)
          const label = clean(action.label || 'Acción')
          if (!prompt || action.enabled === false) return ''
          return `<button type="button" data-mia-prompt="${esc(prompt)}" data-mia-action="${esc(clean(action.id || 'action'))}" aria-label="${esc(label)} para ${esc(name)}"><span>${esc(label)}</span><small>→</small></button>`
        }).join('')}</div>` : ''}
      </div>
    </div>`
}
