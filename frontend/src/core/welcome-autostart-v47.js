/**
 * mIA V4.7: saludo de voz sin boton de reproduccion.
 *
 * 1) Intenta reproducir el audio precargado al aparecer el avatar.
 * 2) Si el navegador lo rechaza, reintenta UNA vez directamente (sin click falso).
 * 3) Si sigue bloqueado, aprovecha la primera interaccion REAL del usuario.
 *
 * Los navegadores pueden denegar autoplay. No existe API para forzar permisos
 * con eventos sinteticos; nunca solicitamos microfono ni desactivamos sonido.
 */
export class MiaWelcomeAutostartV47 {
  constructor({ voice, canSpeak = () => true, eventTarget = window,
    retryDelayMs = 180, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
    if (!voice) throw new TypeError('MiaWelcomeAutostartV47 requiere voice');
    this.voice = voice;
    this.canSpeak = canSpeak;
    this.eventTarget = eventTarget;
    this.retryDelayMs = retryDelayMs;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this._generation = 0;
    this._message = '';
    this._active = false;
    this._playing = false;
    this._attempting = false;
    this._retried = false;
    this._timer = null;
    this._armed = false;
    this._disposed = false;
    this._gesture = (event) => this._onGesture(event);
  }

  _listen() {
    if (this._armed || !this._active || this._playing) return;
    this._armed = true;
    // Capture phase, so .play() happens before any asynchronous handler.
    for (const event of ['pointerdown', 'keydown', 'touchstart', 'click']) {
      this.eventTarget.addEventListener(event, this._gesture, { capture: true, passive: true });
    }
  }

  _unlisten() {
    if (!this._armed) return;
    this._armed = false;
    for (const event of ['pointerdown', 'keydown', 'touchstart', 'click']) {
      this.eventTarget.removeEventListener(event, this._gesture, true);
    }
  }

  _clear() {
    if (this._timer !== null) this.clearTimer(this._timer);
    this._timer = null;
    this._unlisten();
  }

  cancel() {
    this._generation += 1;
    this._active = false;
    this._playing = false;
    this._attempting = false;
    this._message = '';
    this._clear();
  }

  dispose() {
    this.cancel();
    this._disposed = true;
  }

  get pending() { return this._active && !this._playing; }

  markPlaying() {
    if (!this._active) return;
    this._playing = true;
    this._active = false;
    this._clear();
  }

  /** Also handles later speechSynthesis.onerror from the browser fallback. */
  blocked() {
    if (this._disposed || !this._active || this._playing) return;
    if (!this.canSpeak()) { this.cancel(); return; }
    this._listen();
  }

  async start(text) {
    if (this._disposed) return { status: 'disposed' };
    this.cancel();
    const message = String(text ?? '').trim();
    if (!message || !this.canSpeak()) return { status: 'skipped' };
    const generation = this._generation;
    this._message = message;
    this._active = true;
    let result;
    try { result = await this.voice.start(message); }
    catch (error) {
      console.warn('[mIA V4.7] Fallo al iniciar saludo:', error);
      result = { status: 'unavailable' };
    }
    if (generation !== this._generation || !this._active) return result;
    this._handleResult(result, { allowAutoRetry: true, generation });
    return result;
  }

  _handleResult(result, { allowAutoRetry = false, generation = this._generation } = {}) {
    if (generation !== this._generation || !this._active) return;
    if (result?.status === 'playing') { this.markPlaying(); return; }
    if (result?.status === 'browser-speaking') {
      // SpeechSynthesis triggers onStart asynchronously on some browsers.
      // Its error callback can still rearm gesture recovery.
      return;
    }
    if (result?.status === 'cancelled') return;
    this.blocked();
    if (allowAutoRetry && !this._retried) {
      this._retried = true;
      this._timer = this.setTimer(() => {
        this._timer = null;
        if (generation !== this._generation || !this._active || !this.canSpeak() ||
            this._attempting) return;
        // Cached ElevenLabs audio: no second request. If unavailable, ask
        // speechSynthesis directly, without creating any DOM button.
        const task = this.voice.playPrepared && result?.status === 'blocked'
          ? this.voice.playPrepared() : this.voice.replay(this._message);
        Promise.resolve(task).then((retry) => {
          if (generation !== this._generation) return;
          this._handleResult(retry, { generation });
        }).catch((error) => {
          console.warn('[mIA V4.7] Segundo intento de voz:', error);
          if (generation === this._generation) this.blocked();
        });
      }, this.retryDelayMs);
    }
  }

  _onGesture(event) {
    if (event?.isTrusted === false || !this._active || this._playing || this._attempting) return;
    // Ignore modifier-only shortcuts, but allow keyboard and assistive clicks.
    if (event?.type === 'keydown' &&
        ['Shift', 'Control', 'Alt', 'Meta'].includes(event.key)) return;
    // No solapar la voz de bienvenida con el reconocimiento del microfono,
    // una consulta enviada o el gesto de silenciar la voz.
    if (event?.target?.closest?.('#miaMicLauncher, #mic, #voiceToggle, #send, #miaTextLauncher, #miaInteractionDock')) return;
    if (event?.type === 'keydown' &&
        (event.target?.isContentEditable ||
         ['INPUT', 'TEXTAREA'].includes(event.target?.tagName))) return;
    if (!this.canSpeak()) { this.cancel(); return; }
    const generation = this._generation;
    this._attempting = true;
    // IMPORTANT: The cached media play call is invoked synchronously inside
    // the trusted event. No await or network request before .play().
    let attempt;
    try { attempt = this.voice.replay(this._message); }
    catch (error) {
      this._attempting = false;
      console.warn('[mIA V4.7] Reintento por interaccion:', error);
      return;
    }
    Promise.resolve(attempt).then((result) => {
      if (generation !== this._generation) return;
      this._attempting = false;
      this._handleResult(result, { generation });
    }).catch((error) => {
      if (generation !== this._generation) return;
      this._attempting = false;
      console.warn('[mIA V4.7] Interaccion de voz fallida:', error);
      this.blocked();
    });
  }
}
