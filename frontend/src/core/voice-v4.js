/**
 * mIA V4.4 — microphone with THREE EXPLICIT modes:
 *   off -> once -> continuous -> off.
 *
 * Mode never starts on initial page load. A continuous session is explicitly
 * opt-in: SpeechRecognition may stop after each phrase, in which case it is
 * rearmed with a delay; it is ALWAYS suspended during backend requests/TTS.
 * The separate outgoing voice (TTS) is handled by MiaClient.
 */
export const MIC_MODES = Object.freeze(['off', 'once', 'continuous']);

export class MiaVoiceV4 {
  constructor({ onInterim, onFinal, onListening, onModeChange, onError } = {}) {
    this.onInterim = onInterim;
    this.onFinal = onFinal;
    this.onListening = onListening;
    this.onModeChange = onModeChange;
    this.onError = onError;
    this.mode = 'off';
    this.listening = false;
    this.starting = false;
    this.suspended = false;
    this.destroyed = false;
    this.available = false;
    this.recognition = null;
    this._retry = null;
    this._transientErrors = 0;
    this._finalCaptured = false;
    this._isClosing = false;

    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return;
    this.recognition = new Recognition();
    this.available = true;
    this.recognition.lang = 'es-ES';
    // One request is one final sentence; the app decides whether to re-arm.
    this.recognition.continuous = false;
    this.recognition.interimResults = true;

    this.recognition.onstart = () => {
      if (this.destroyed || this.mode === 'off' || this.suspended || document.hidden) {
        // `onstart` puede llegar tarde, después de cancelar la solicitud.
        // Abortarla aunque `starting` ya esté a false evita captura no deseada.
        this._isClosing = true;
        try { this.recognition.abort(); } catch { this._isClosing = false; }
        this.listening = false;
        this.starting = false;
        this._notify();
        return;
      }
      this.starting = false;
      this.listening = true;
      this._notify();
    };
    this.recognition.onresult = (event) => {
      if (this.destroyed || this.suspended || this.mode === 'off' || this._finalCaptured) return;
      const final = [];
      const partial = [];
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const record = event.results[i];
        const text = record?.[0]?.transcript?.trim() || '';
        if (!text) continue;
        (record.isFinal ? final : partial).push(text);
      }
      if (final.length) {
        this._finalCaptured = true;
        const text = final.join(' ');
        // Freeze capture immediately: NEVER transcribe Mía's synthesized voice.
        // En una sola pregunta la escucha física termina, pero conservamos
        // la etapa 1 del ciclo hasta el siguiente clic (que será CONTINUO).
        this.pause();
        this._transientErrors = 0;
        this.onFinal?.(text);
      } else if (partial.length) {
        this.onInterim?.(partial.join(' '));
      }
    };
    this.recognition.onend = () => {
      this.listening = false;
      this.starting = false;
      this._isClosing = false;
      // Si la escucha de una pregunta caduca por silencio queda suspendida;
      // el segundo clic sigue significando "modo continuo", sin sorpresas.
      if (this.mode === 'once' && !this._finalCaptured) this.suspended = true;
      this._notify();
      if (this.mode === 'continuous' && !this.suspended && !document.hidden) {
        this._scheduleRestart();
      }
    };
    this.recognition.onerror = (event) => {
      const error = event?.error || 'unknown';
      if (this.destroyed) return;
      this.listening = false;
      this.starting = false;
      this._notify();
      if (this._isClosing && error === 'aborted') return;
      if (['not-allowed', 'service-not-allowed', 'audio-capture', 'language-not-supported'].includes(error)) {
        this._setMode('off');
        this._clearRetry();
        this.onError?.(error);
      } else if (error === 'no-speech') {
        if (this.mode === 'once') this.suspended = true;
        // Continuous mode will retry on onend, with a delay.
      } else if (error !== 'aborted') {
        this._transientErrors += 1;
        if (this._transientErrors >= 3) this._setMode('off');
        this.onError?.(error);
      }
    };

    this._onVisibility = () => {
      if (document.hidden) {
        if (this.mode === 'once') this.suspended = true;
        this._clearRetry();
        this._abortRecognition();
      } else if (this.mode === 'continuous' && !this.suspended) {
        this._scheduleRestart();
      }
    };
    document.addEventListener('visibilitychange', this._onVisibility);
  }

  get wantsListening() { return this.mode !== 'off'; }

  _notify() {
    this.onListening?.(Boolean(this.listening || this.starting));
    this.onModeChange?.(this.mode, {
      listening: Boolean(this.listening || this.starting),
      paused: this.suspended || document.hidden,
    });
  }

  _setMode(mode) {
    if (!MIC_MODES.includes(mode)) throw new Error('Modo de micrófono no válido');
    this.mode = mode;
    if (mode === 'off') {
      this.suspended = false;
      this._clearRetry();
    }
    this._notify();
  }

  _clearRetry() {
    if (this._retry !== null) window.clearTimeout(this._retry);
    this._retry = null;
  }

  _abortRecognition() {
    if (!this.recognition || this._isClosing || (!this.listening && !this.starting)) return;
    this._isClosing = true;
    try { this.recognition.abort(); } catch { this._isClosing = false; }
    this.listening = false;
    this.starting = false;
    this._notify();
  }

  _startRecognition() {
    if (this.destroyed || !this.available || this.mode === 'off' ||
        this.suspended || document.hidden || this.listening || this.starting || this._isClosing) return false;
    this._clearRetry();
    this._finalCaptured = false;
    this.starting = true;
    this._notify();
    try {
      this.recognition.start();
      return true;
    } catch (error) {
      this.starting = false;
      this._transientErrors += 1;
      this._notify();
      if (this._transientErrors >= 3) this.stop();
      this.onError?.(error?.name || 'start-blocked');
      return false;
    }
  }

  _scheduleRestart(delayMs = 1100) {
    if (this.destroyed || this.mode !== 'continuous' || this.suspended || document.hidden) return;
    this._clearRetry();
    this._retry = window.setTimeout(() => {
      this._retry = null;
      if (this.mode === 'continuous' && !this.suspended && !document.hidden) {
        if (!this._startRecognition() && this.mode === 'continuous') {
          this._scheduleRestart(1900);
        }
      }
    }, delayMs);
  }

  /** This method is intended for a DIRECT button click only. */
  cycle() {
    if (!this.available) {
      this.onError?.('unsupported');
      return 'off';
    }
    if (this.destroyed) return 'off';
    if (this.mode === 'off') {
      this.suspended = false;
      this._setMode('once');
      this._startRecognition();
    } else if (this.mode === 'once') {
      this.suspended = false;
      this._setMode('continuous');
      if (!this.suspended && !this.listening && !this.starting) this._startRecognition();
    } else {
      this.stop();
    }
    return this.mode;
  }

  /** Compat for callers that previously used toggle(). */
  toggle() { return this.cycle(); }
  start() { if (this.mode === 'off') return this.cycle() === 'once'; return this._startRecognition(); }

  /** Suspend during request and especially while mIA's TTS is speaking. */
  pause() {
    if (this.mode === 'off') return;
    this.suspended = true;
    this._clearRetry();
    this._abortRecognition();
    this._notify();
  }

  /** Resume ONLY an explicitly enabled continuous mode. */
  resume() {
    if (this.mode !== 'continuous' || this.destroyed) return;
    this.suspended = false;
    this._notify();
    this._scheduleRestart(800);
  }

  stop() {
    this._setMode('off');
    this._abortRecognition();
    this.listening = false;
    this.starting = false;
    this._notify();
  }

  startIfPreviouslyAllowed() { return false; }
  destroy() {
    this.stop();
    this.destroyed = true;
    this._clearRetry();
    if (this._onVisibility) document.removeEventListener('visibilitychange', this._onVisibility);
    if (this.recognition) {
      this.recognition.onstart = null;
      this.recognition.onresult = null;
      this.recognition.onend = null;
      this.recognition.onerror = null;
    }
  }
}
