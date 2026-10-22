/**
 * mIA HG V5.3.0 - TTS remoto exclusivamente.
 * La voz siempre se solicita al mismo contrato que el 3D: /api/voice/stream.
 * El backend elige el proveedor y la voz usando su .env; el navegador JAMAS
 * ejecuta speechSynthesis como reemplazo silencioso.
 * La respuesta visual se conserva si el servicio de voz falla.
 */
export class HologramVoiceV522 {
  constructor({ apiBase = '', fetchImpl = fetch,
    createAudio = (url) => new Audio(url), maxMs = 90000,
    fetchTimeoutMs = 45000 } = {}) {
    this.apiBase = apiBase;
    this.fetchImpl = fetchImpl;
    this.createAudio = createAudio;
    this.maxMs = maxMs;
    this.fetchTimeoutMs = fetchTimeoutMs;
    this.controller = null;
    this.audio = null;
    this.audioURL = null;
    this._cancelPlayback = null;
    this._seq = 0;
  }
  stop() {
    this._seq += 1;
    this.controller?.abort();
    this.controller = null;
    try { this.audio?.pause(); } catch { /* pause unsupported */ }
    this._cancelPlayback?.('cancelled');
    this._cancelPlayback = null;
    this.audio = null;
    if (this.audioURL) {
      URL.revokeObjectURL(this.audioURL);
      this.audioURL = null;
    }
  }
  async _playAudio(audio, seq, onStart) {
    return new Promise((resolve) => {
      let complete = false;
      const finish = (status) => {
        if (complete) return;
        complete = true;
        audio.removeEventListener('ended', ended);
        audio.removeEventListener('error', broken);
        if (this._cancelPlayback === finish) this._cancelPlayback = null;
        resolve({ status });
      };
      const ended = () => finish('completed');
      const broken = () => finish('playback-error');
      this._cancelPlayback = finish;
      audio.addEventListener('ended', ended, { once: true });
      audio.addEventListener('error', broken, { once: true });
      try {
        Promise.resolve(audio.play()).then(() => {
          if (seq !== this._seq) finish('cancelled');
          else onStart?.();
        }).catch((error) => {
          console.warn('[mIA HG TTS] La reproducción fue bloqueada:', error?.name || error);
          finish('playback-blocked');
        });
      } catch (error) {
        console.warn('[mIA HG TTS] No se pudo iniciar el audio:', error?.name || error);
        finish('playback-error');
      }
      if (seq !== this._seq) finish('cancelled');
    });
  }
  async speak(text, { onStart, maxMs = this.maxMs } = {}) {
    this.stop();
    const summary = String(text || '').trim();
    if (!summary) return { status: 'empty' };
    const seq = this._seq;
    const controller = new AbortController();
    this.controller = controller;
    let budgetTimer;
    let fetchTimer;
    let timedOut = false;
    let budgetExpired = false;
    const budget = new Promise((resolve) => {
      budgetTimer = setTimeout(() => {
        budgetExpired = true;
        if (seq === this._seq) this.stop();
        resolve({ status: 'voice-timeout' });
      }, Math.max(100, maxMs));
    });
    const perform = (async () => {
      try {
        fetchTimer = setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, Math.max(100, this.fetchTimeoutMs));
        const response = await this.fetchImpl(`${this.apiBase}/api/voice/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'audio/*, application/octet-stream' },
          body: JSON.stringify({ text: summary }),
          signal: controller.signal,
        });
        if (!response.ok) {
          console.warn(`[mIA HG TTS] /api/voice/stream -> HTTP ${response.status}`);
          return { status: 'voice-http-error', http: response.status };
        }
        const mime = response.headers?.get?.('content-type') || '';
        if (/text\/html|application\/json|text\/plain/i.test(mime)) {
          console.warn(`[mIA HG TTS] El endpoint no devolvio audio (Content-Type ${mime}).`);
          return { status: 'voice-invalid-content-type' };
        }
        const blob = await response.blob();
        if (!blob.size) return { status: 'voice-empty-audio' };
        if (seq !== this._seq) return { status: 'cancelled' };
        clearTimeout(fetchTimer);
        fetchTimer = null;
        this.audioURL = URL.createObjectURL(blob);
        const audio = this.createAudio(this.audioURL);
        this.audio = audio;
        return await this._playAudio(audio, seq, onStart);
      } catch (error) {
        if (seq !== this._seq) return { status: budgetExpired ? 'voice-timeout' : 'cancelled' };
        if (timedOut) console.warn('[mIA HG TTS] Tiempo agotado al solicitar el audio remoto.');
        else console.warn('[mIA HG TTS] El servicio remoto de voz no esta disponible:', error?.message || error);
        return { status: timedOut ? 'voice-fetch-timeout' : 'voice-network-error' };
      } finally {
        clearTimeout(fetchTimer);
      }
    })();
    try {
      return await Promise.race([perform, budget]);
    } finally {
      clearTimeout(budgetTimer);
      clearTimeout(fetchTimer);
      if (seq === this._seq) this.stop();
    }
  }
}
