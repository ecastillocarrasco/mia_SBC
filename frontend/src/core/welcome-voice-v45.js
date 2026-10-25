/**
 * Mía V4.6: spoken welcome independently of microphone recognition.
 * - Pre-fetches the existing /api/voice/stream audio while GLB is loading.
 * - Attempts autoplay when the scene becomes ready.
 * - Keeps a prepared Audio element if autoplay is blocked so replay() calls
 *   play() synchronously inside the user's click (no new network wait).
 * - On TTS service failure, the same button can use browser speech synthesis.
 * Browser autoplay restrictions cannot be bypassed by JavaScript.
 */
import { withSpokenName } from "./speech-text.js";

export class MiaWelcomeVoiceV45 {
  constructor({ apiBase = '', onBlocked = null, onStart = null, onEnd = null,
    fetchImpl = null, audioFactory = null, getAuthHeaders = null } = {}) {
    this.apiBase = apiBase;
    this.onBlocked = onBlocked;
    this.onStart = onStart;
    this.onEnd = onEnd;
    this.fetchImpl = fetchImpl || ((...args) => fetch(...args));
    this.audioFactory = audioFactory || ((url) => new Audio(url));
    // /api/voice/stream exige sesión (UserDep en el backend, ver src/mia/api/routes/voice.py):
    // sin esto, el saludo recibe 401 y cae siempre a la voz del navegador en 3D/Holograma —
    // nunca se notaba en 2D porque su propio speak() ya adjunta el token (ver mia-2d.js).
    this.getAuthHeaders = getAuthHeaders || (async () => ({}));
    this._controller = null;
    this._audio = null;
    this._url = null;
    this._text = '';
    this._preparing = null;
    this._generation = 0;
    this._browserVoice = false;
  }

  cancel() {
    this._generation += 1;
    this._controller?.abort();
    this._controller = null;
    try { this._audio?.pause(); } catch { /* no active audio */ }
    this._audio = null;
    if (this._url) URL.revokeObjectURL(this._url);
    this._url = null;
    this._text = '';
    this._preparing = null;
    if (this._browserVoice) {
      try { globalThis.speechSynthesis?.cancel(); } catch { /* not available */ }
      this._browserVoice = false;
    }
  }

  prepare(text) {
    const message = String(text ?? '').trim();
    if (!message) return Promise.resolve({ status: 'empty' });
    if (message === this._text) {
      if (this._audio) return Promise.resolve({ status: 'ready' });
      if (this._preparing) return this._preparing;
    }
    this.cancel();
    const generation = this._generation;
    this._text = message;
    const controller = new AbortController();
    this._controller = controller;
    const promise = (async () => {
      try {
        const authHeaders = await this.getAuthHeaders().catch(() => ({}));
        // cancel() pudo llegar mientras esperábamos el token (p. ej. una consulta real
        // interrumpe el saludo): no lancemos la petición de voz si ya no hace falta.
        if (controller.signal.aborted || generation !== this._generation)
          return { status: 'cancelled' };
        const response = await this.fetchImpl(`${this.apiBase}/api/voice/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify({ text: withSpokenName(message) }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`voice/stream HTTP ${response.status}`);
        const blob = await response.blob();
        if (!blob?.size) throw new Error('El servicio de voz devolvió audio vacío');
        if (controller.signal.aborted || generation !== this._generation)
          return { status: 'cancelled' };
        const url = URL.createObjectURL(blob);
        this._url = url;
        this._audio = this.audioFactory(url);
        this._audio.preload = 'auto';
        this._audio.muted = false;
        this._audio.volume = 1;
        this._audio.addEventListener?.('ended', () => {
          if (generation === this._generation) this.onEnd?.();
        }, { once: true });
        return { status: 'ready' };
      } catch (error) {
        if (controller.signal.aborted || generation !== this._generation)
          return { status: 'cancelled' };
        console.warn('[mIA V4.6] Audio de bienvenida no disponible:', error?.message || error);
        return { status: 'unavailable' };
      } finally {
        if (generation === this._generation) {
          this._controller = null;
          this._preparing = null;
        }
      }
    })();
    this._preparing = promise;
    return promise;
  }

  /** This calls audio.play immediately, before any await. */
  async playPrepared() {
    if (!this._audio) {
      this.onBlocked?.('unavailable');
      return { status: 'unavailable' };
    }
    try {
      await this._audio.play();
      this.onStart?.();
      return { status: 'playing' };
    } catch (error) {
      const blocked = error?.name === 'NotAllowedError' ||
        /not.?allowed|autoplay|user.?gesture/i.test(String(error));
      // A failed attempt does not destroy the cached Audio element.
      if (!blocked) {
        // A corrupt/unsupported voice stream cannot be replayed. Release it
        // so the next user click falls back to the browser's Spanish voice.
        try { this._audio?.pause(); } catch { /* no media */ }
        this._audio = null;
        if (this._url) URL.revokeObjectURL(this._url);
        this._url = null;
      }
      this.onBlocked?.(blocked ? 'blocked' : 'unavailable');
      return { status: blocked ? 'blocked' : 'unavailable' };
    }
  }

  async start(text) {
    const status = await this.prepare(text);
    if (status.status !== 'ready') {
      if (status.status === 'unavailable') this.onBlocked?.('unavailable');
      return status;
    }
    return this.playPrepared();
  }

  /** Called from a real click. Prefer already loaded ElevenLabs audio. */
  replay(text) {
    const message = String(text || this._text).trim();
    if (this._audio && message === this._text) {
      try { this._audio.currentTime = 0; } catch { /* streaming source */ }
      return this.playPrepared();
    }
    // If backend voice failed, use the platform's Spanish voice on click.
    const synth = globalThis.speechSynthesis;
    const Utterance = globalThis.SpeechSynthesisUtterance;
    if (!synth || !Utterance) {
      this.onBlocked?.('unavailable');
      return Promise.resolve({ status: 'unavailable' });
    }
    const utterance = new Utterance(withSpokenName(message));
    utterance.lang = 'es-ES';
    utterance.rate = 0.96;
    const voices = synth.getVoices?.() || [];
    utterance.voice = voices.find((voice) => voice.lang?.toLowerCase().startsWith('es')) || null;
    utterance.onstart = () => this.onStart?.();
    utterance.onend = () => { this._browserVoice = false; this.onEnd?.(); };
    utterance.onerror = () => { this._browserVoice = false; this.onBlocked?.('unavailable'); };
    // Synchronous user-gesture action for browsers requiring activation.
    synth.cancel();
    this._browserVoice = true;
    synth.speak(utterance);
    return Promise.resolve({ status: 'browser-speaking' });
  }

  dispose() { this.cancel(); }
}
