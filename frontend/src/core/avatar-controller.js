const BACKEND_STATE_MAP = {
  reposo: 'idle',
  escuchando: 'listening',
  pensando: 'thinking',
  concentrada: 'thinking',
  hablando: 'speaking',
  sonriendo: 'success',
  saludando: 'greeting',
  guinando: 'confirming',
  sorprendida: 'success',
  confundida: 'error',
  entusiasmada: 'success',
  celebrando: 'success',
  avisando: 'presenting',
  empatica: 'confirming',
  despedida: 'greeting',
  aprobando: 'confirming',
}

const STATE_CANDIDATES = {
  idle: ['mIA_IDLE'],
  listening: ['mIA_IDLE_STANDING', 'mIA_IDLE'],
  thinking: ['mIA_THINK', 'mIA_IDLE_STANDING'],
  speaking: ['mIA_TALK', 'mIA_IDLE_STANDING', 'mIA_IDLE'],
  presenting: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  greeting: ['mIA_GREET', 'mIA_WAVE', 'mIA_YES'],
  confirming: ['mIA_AGREE', 'mIA_YES', 'mIA_IDLE_HAPPY'],
  success: ['mIA_HAPPY', 'mIA_CLAP', 'mIA_IDLE_HAPPY'],
  error: ['mIA_SHRUG', 'mIA_NO', 'mIA_IDLE_STANDING'],
  waiting: ['mIA_IDLE', 'mIA_IDLE_STANDING'],
}

const PRESENTATION_CANDIDATES = {
  scalar: ['mIA_YES', 'mIA_AGREE', 'mIA_POINT'],
  employee360: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  person: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  department: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  analytics: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  comparison: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  list: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  shifts: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
  document: ['mIA_POINT', 'mIA_YES', 'mIA_AGREE'],
  text: ['mIA_AGREE', 'mIA_YES'],
}

const IDLE_MICRO_CANDIDATES = [
  'mIA_LOOK_AROUND_ALT',
  'mIA_YES',
  'mIA_AGREE',
]

const SPEAKING_GESTURES = [
  'mIA_AGREE',
  'mIA_YES',
  'mIA_POINT',
]

function normalized(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
}

function asPromise(value) {
  return Promise.resolve(value)
}

export class AvatarController {
  constructor({
    hasAnimation,
    playAnimation,
    playGesture = null,
    stopGesture = null,
    enableIdleMicroGestures = true,
    enableSpeakingGestures = true,
    debug = false,
  } = {}) {
    if (typeof hasAnimation !== 'function') {
      throw new Error('AvatarController necesita hasAnimation(name)')
    }

    if (typeof playAnimation !== 'function') {
      throw new Error('AvatarController necesita playAnimation(name, options)')
    }

    this.hasAnimation = hasAnimation
    this.playAnimation = playAnimation
    this.playGesture = typeof playGesture === 'function' ? playGesture : null
    this.stopGesture = typeof stopGesture === 'function' ? stopGesture : null
    this.enableIdleMicroGestures = enableIdleMicroGestures
    this.enableSpeakingGestures = enableSpeakingGestures
    this.debug = debug

    this.state = 'idle'
    this.context = {}
    this._idleTimer = null
    this._speakingTimer = null
    this._sequence = 0
    this._gestureCursor = 0
    this._idleCursor = 0
    this._speakingGestureCount = 0
    this._destroyed = false
  }

  enter(state, context = {}) {
    if (this._destroyed) return Promise.resolve()

    const safeState = STATE_CANDIDATES[state] ? state : 'idle'

    this._clearTimers()
    this._stopGestureLayer(0.12)

    this.state = safeState
    this.context = { ...context }
    this._sequence += 1
    this._speakingGestureCount = 0

    const sequence = this._sequence
    const animation = this._animationForState(safeState, context)

    if (this.debug) {
      console.log('[mIA AvatarController V2]', safeState, animation, context)
    }

    const playPromise = this._play(animation, this._optionsForState(safeState, context))

    if (safeState === 'listening') {
      this._scheduleListeningNod(sequence)
    }

    if (safeState === 'idle' && this.enableIdleMicroGestures) {
      this._scheduleIdleMicroGesture(sequence)
    }

    if (safeState === 'speaking' && this.enableSpeakingGestures) {
      this._scheduleSpeakingGesture(sequence)
    }

    return playPromise
  }

  enterBackendState(backendState, context = {}) {
    const state = BACKEND_STATE_MAP[normalized(backendState)] || null
    if (!state) return Promise.resolve(false)
    return this.enter(state, context).then(() => true)
  }

  gesture(intent, context = {}) {
    if (this._destroyed) return Promise.resolve()

    const safeIntent = normalized(intent)
    const map = {
      greet: STATE_CANDIDATES.greeting,
      greeting: STATE_CANDIDATES.greeting,
      confirm: STATE_CANDIDATES.confirming,
      confirming: STATE_CANDIDATES.confirming,
      success: STATE_CANDIDATES.success,
      error: STATE_CANDIDATES.error,
      warning: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
      point: ['mIA_POINT', 'mIA_AGREE', 'mIA_YES'],
    }

    const animation = this._pickAvailable(map[safeIntent] || STATE_CANDIDATES.confirming)

    if (
      this.playGesture &&
      ['speaking', 'idle', 'listening', 'waiting'].includes(this.state)
    ) {
      return this._playGesture(animation, {
        fadeIn: 0.16,
        fadeOut: 0.2,
        weight: 0.72,
        ...context.options,
      })
    }

    return this._play(animation, { fade: 0.3, loop: false, clamp: true, ...context.options })
  }

  destroy() {
    this._destroyed = true
    this._clearTimers()
    this._stopGestureLayer(0.08)
  }

  _animationForState(state, context) {
    if (state === 'presenting') {
      if (context.preferredAnimation && this.hasAnimation(context.preferredAnimation)) {
        return context.preferredAnimation
      }

      const type = normalized(context.presentationType || context.type)
      return this._pickAvailable(PRESENTATION_CANDIDATES[type] || STATE_CANDIDATES.presenting)
    }

    if (state === 'success') {
      const text = normalized(`${context.query || ''} ${context.answer || ''}`)
      if (/gracias|perfecto|genial|conseguido|completado|correcto/.test(text)) {
        return this._pickAvailable(['mIA_HAPPY', 'mIA_CLAP', 'mIA_IDLE_HAPPY'])
      }
    }

    return this._firstAvailable(STATE_CANDIDATES[state])
  }

  _optionsForState(state, context) {
    const fade = Number.isFinite(Number(context.fade)) ? Number(context.fade) : 0.34

    if (['idle', 'listening', 'thinking', 'speaking', 'waiting'].includes(state)) {
      return { fade, loop: true, clamp: false }
    }

    return { fade, loop: false, clamp: true }
  }

  _firstAvailable(candidates = []) {
    return candidates.find((name) => this.hasAnimation(name)) ||
      (this.hasAnimation('mIA_IDLE') ? 'mIA_IDLE' : null)
  }

  _pickAvailable(candidates = []) {
    const available = candidates.filter((name) => this.hasAnimation(name))
    if (!available.length) {
      return this.hasAnimation('mIA_IDLE') ? 'mIA_IDLE' : null
    }

    const index = this._gestureCursor % available.length
    this._gestureCursor += 1
    return available[index]
  }

  _play(name, options = {}) {
    if (!name || !this.hasAnimation(name)) return Promise.resolve()

    try {
      return asPromise(this.playAnimation(name, options)).catch((error) => {
        console.warn('[mIA AvatarController V2] fallo reproduciendo', name, error)
      })
    } catch (error) {
      console.warn('[mIA AvatarController V2] fallo reproduciendo', name, error)
      return Promise.resolve()
    }
  }

  _playGesture(name, options = {}) {
    if (!name || !this.hasAnimation(name)) return Promise.resolve(false)

    if (!this.playGesture) {
      return this._play(name, {
        fade: 0.2,
        loop: false,
        clamp: true,
      }).then(() => true)
    }

    try {
      return asPromise(this.playGesture(name, options)).catch((error) => {
        console.warn('[mIA AvatarController V2] fallo en capa gestual', name, error)
        return false
      })
    } catch (error) {
      console.warn('[mIA AvatarController V2] fallo en capa gestual', name, error)
      return Promise.resolve(false)
    }
  }

  _stopGestureLayer(fade = 0.12) {
    if (!this.stopGesture) return
    try {
      this.stopGesture(fade)
    } catch (error) {
      console.warn('[mIA AvatarController V2] fallo deteniendo capa gestual', error)
    }
  }

  _scheduleListeningNod(sequence) {
    if (!this.playGesture || !this.hasAnimation('mIA_YES')) return

    window.setTimeout(() => {
      if (this._destroyed || this.state !== 'listening' || sequence !== this._sequence) return

      this._playGesture('mIA_YES', {
        fadeIn: 0.12,
        fadeOut: 0.16,
        weight: 0.62,
        timeScale: 1.05,
      })
    }, 90)
  }

  _scheduleIdleMicroGesture(sequence) {
    const idleDelays = [11800, 14600, 17200, 13200]
    const delay = idleDelays[this._idleCursor % idleDelays.length]
    this._idleCursor += 1

    this._idleTimer = window.setTimeout(async () => {
      this._idleTimer = null
      if (this._destroyed || this.state !== 'idle' || sequence !== this._sequence) return

      const candidates = IDLE_MICRO_CANDIDATES.filter((name) => this.hasAnimation(name))
      if (!candidates.length) {
        this._scheduleIdleMicroGesture(sequence)
        return
      }

      const animation = candidates[this._idleCursor % candidates.length]

      await this._playGesture(animation, {
        fadeIn: 0.18,
        fadeOut: 0.24,
        weight: animation === 'mIA_LOOK_AROUND_ALT' ? 0.58 : 0.52,
        timeScale: 0.92,
      })

      if (this._destroyed || this.state !== 'idle' || sequence !== this._sequence) return
      this._scheduleIdleMicroGesture(sequence)
    }, delay)
  }

  _speakingGestureBudget() {
    const answerLength = String(this.context.answer || '').trim().length

    if (answerLength >= 900) return 3
    if (answerLength >= 520) return 2
    if (answerLength >= 220) return 1
    return 0
  }

  _scheduleSpeakingGesture(sequence) {
    const budget = this._speakingGestureBudget()

    if (this._speakingGestureCount >= budget) return

    const delays = [4300, 6200, 7200]
    const delay = delays[Math.min(this._speakingGestureCount, delays.length - 1)]

    this._speakingTimer = window.setTimeout(async () => {
      this._speakingTimer = null
      if (this._destroyed || this.state !== 'speaking' || sequence !== this._sequence) return

      let candidates = SPEAKING_GESTURES
      const type = normalized(this.context.presentationType || this.context.type)

      if (['analytics', 'comparison', 'department', 'employee360', 'person', 'list'].includes(type)) {
        candidates = ['mIA_POINT', 'mIA_AGREE', 'mIA_YES']
      } else if (type === 'text') {
        candidates = ['mIA_AGREE', 'mIA_YES']
      }

      const available = candidates.filter((name) => this.hasAnimation(name))
      if (!available.length) return

      const animation = available[this._speakingGestureCount % available.length]
      this._speakingGestureCount += 1

      await this._playGesture(animation, {
        fadeIn: 0.14,
        fadeOut: 0.2,
        weight: animation === 'mIA_POINT' ? 0.74 : 0.6,
        timeScale: 1,
      })

      if (this._destroyed || this.state !== 'speaking' || sequence !== this._sequence) return
      this._scheduleSpeakingGesture(sequence)
    }, delay)
  }

  _clearTimers() {
    if (this._idleTimer) {
      window.clearTimeout(this._idleTimer)
      this._idleTimer = null
    }

    if (this._speakingTimer) {
      window.clearTimeout(this._speakingTimer)
      this._speakingTimer = null
    }
  }
}
