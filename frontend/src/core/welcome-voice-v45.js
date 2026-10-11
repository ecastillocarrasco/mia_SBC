/**
 * Spoken welcome on entry (distinct from recognition/microphone).
 * Attempts TTS automatically after 3D assets are ready, WITHOUT waiting for
 * the visitor to type. Browser autoplay policy can still block it; the UI
 * may then offer a clear 'Escuchar saludo' button.
 */
export class MiaWelcomeVoiceV45 {
  constructor({ apiBase = '', onBlocked = null, fetchImpl = null, audioFactory = null } = {}) {
    this.apiBase = apiBase;
    this.onBlocked = onBlocked;
    this.fetchImpl = fetchImpl || ((...args) => fetch(...args));
    this.audioFactory = audioFactory || ((url) => new Audio(url));
    this._controller = null;
    this._audio = null;
    this._url = null;
    this._generation = 0;
  }

  cancel() {
    this._generation++;
    this._controller?.abort();
    this._controller = null;
    if (this._audio) {
      try { this._audio.pause(); } catch { /* already finished */ }
      this._audio = null;
    }
    if (this._url) {
      URL.revokeObjectURL(this._url);
      this._url = null;
    }
  }

  async start(text) {
    this.cancel();
    const generation = this._generation;
    const controller = new AbortController();
    this._controller = controller;
    if (!String(text || '').trim()) return { status: 'empty' };
    try {
      const response = await this.fetchImpl(`${this.apiBase}/api/voice/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }), signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      if (controller.signal.aborted || generation !== this._generation) return { status: 'cancelled' };
      const url = URL.createObjectURL(blob);
      this._url = url;
      const audio = this.audioFactory(url);
      this._audio = audio;
      // The user sees the visual greeting immediately. The voice is a bonus
      // which cannot bypass media autoplay permissions on an unknown browser.
      await audio.play();
      return { status: 'playing' };
    } catch (error) {
      if (controller.signal.aborted || generation !== this._generation) return { status: 'cancelled' };
      const blocked = error?.name === 'NotAllowedError' || /not.?allowed|autoplay|user.?gesture/i.test(String(error));
      if (blocked) this.onBlocked?.();
      else console.warn('[mIA V4.5] Voz de bienvenida no disponible:', error?.message || error);
      return { status: blocked ? 'blocked' : 'unavailable' };
    } finally {
      if (generation === this._generation) this._controller = null;
    }
  }

  dispose() { this.cancel(); }
}
