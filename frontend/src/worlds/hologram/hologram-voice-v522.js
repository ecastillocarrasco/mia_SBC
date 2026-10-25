/**
 * mIA SBC V5.3.1. Backend-only speech with cached playback and manual recovery.
 * Same contract as 3D: POST /api/voice/stream, body {text}.
 * No speechSynthesis fallback. Audio is retained until the NEXT turn or pagehide,
 * so a blocked autoplay can be replayed by a real user gesture without re-TTS.
 */
import { withSpokenName } from "../../core/speech-text.js";

export class HologramVoiceV522 {
  constructor({ apiBase = '', fetchImpl = (...args) => fetch(...args),
    createAudio = url => new Audio(url), maxMs = 90000,
    fetchTimeoutMs = 45000, getAuthHeaders = async () => ({}) } = {}) {
    this.apiBase = apiBase;
    this.fetchImpl = fetchImpl;
    this.createAudio = createAudio;
    this.maxMs = maxMs;
    this.fetchTimeoutMs = fetchTimeoutMs;
    this.getAuthHeaders = getAuthHeaders;
    this.controller = null;
    this.audio = null;
    this.audioURL = null;
    this.lastText = '';
    this._seq = 0;
    this._cancelPlayback = null;
    this._playing = false;
    this.lastResult = {status:'idle'};
  }
  stop() {
    this._seq++;
    this.controller?.abort();
    this.controller = null;
    this._cancelPlayback?.('cancelled');
    this._cancelPlayback = null;
    try { this.audio?.pause?.(); } catch { /* ignored */ }
    this.audio = null;
    this._playing = false;
    if (this.audioURL) {
      try { URL.revokeObjectURL(this.audioURL); } catch { /* ignored */ }
      this.audioURL = null;
    }
    this.lastText = '';
  }
  async _playAudio(seq, onStart) {
    const audio = this.audio;
    if (!audio || seq !== this._seq) return {status:'cancelled'};
    if (this._playing) return {status:'already-playing'};
    this._playing = true;
    return new Promise(resolve => {
      let finished = false;
      const done = status => {
        if (finished) return;
        finished = true;
        this._playing = false;
        audio.removeEventListener('ended', ended);
        audio.removeEventListener('error', failed);
        if (this._cancelPlayback === done) this._cancelPlayback = null;
        const result = {status};
        this.lastResult = result;
        resolve(result);
      };
      const ended = () => done('completed');
      const failed = () => done('playback-error');
      this._cancelPlayback = done;
      audio.addEventListener('ended', ended, {once:true});
      audio.addEventListener('error', failed, {once:true});
      try {
        audio.muted = false;
        audio.volume = 1;
        if (audio.readyState !== undefined && audio.readyState >= 1) audio.currentTime = 0;
        // IMPORTANT: play() is invoked synchronously. For replay(), this call
        // happens directly inside the real click and retains user activation.
        const attempt = audio.play();
        Promise.resolve(attempt).then(() => {
          if (seq !== this._seq) return done('cancelled');
          onStart?.();
        }).catch(error => {
          const blocked = error?.name === 'NotAllowedError' || /not.?allowed|autoplay|user.?gesture/i.test(String(error));
          console.warn('[mIA HG TTS] Audio.play rechazado:', error?.name || error);
          done(blocked ? 'playback-blocked' : 'playback-error');
        });
      } catch (error) {
        console.warn('[mIA HG TTS] Audio.play falló:', error?.name || error);
        done('playback-error');
      }
      if (seq !== this._seq) done('cancelled');
    });
  }
  async speak(text, {onStart, maxMs = this.maxMs} = {}) {
    this.stop();
    const summary = String(text || '').trim();
    if (!summary) return {status:'empty'};
    this.lastText = summary;
    const seq = this._seq;
    const controller = new AbortController();
    this.controller = controller;
    let fetchTimer;
    let budgetTimer;
    let fetchTimedOut = false;
    let fullTimedOut = false;
    const budget = new Promise(resolve => {
      budgetTimer = setTimeout(() => {
        fullTimedOut = true;
        if (seq === this._seq) this.stop();
        resolve({status:'voice-timeout'});
      }, Math.max(250,maxMs));
    });
    const work = (async () => {
      try {
        fetchTimer = setTimeout(() => {
          fetchTimedOut = true;
          controller.abort();
        }, Math.max(250,this.fetchTimeoutMs));
        const authHeaders = (await this.getAuthHeaders()) || {};
        const response = await this.fetchImpl(`${this.apiBase}/api/voice/stream`, {
          method:'POST',
          headers:{'Content-Type':'application/json','Accept':'audio/*, application/octet-stream',...authHeaders},
          body:JSON.stringify({text:withSpokenName(summary)}),
          signal:controller.signal,
        });
        if (!response.ok) return {status:'voice-http-error',http:response.status};
        const mime = response.headers?.get?.('content-type') || '';
        if (/text\/html|application\/json|text\/plain/i.test(mime)) {
          return {status:'voice-invalid-content-type',mime};
        }
        const blob = await response.blob();
        if (!blob.size) return {status:'voice-empty-audio',mime};
        if (seq !== this._seq) return {status:'cancelled'};
        clearTimeout(fetchTimer);
        fetchTimer = null;
        this.audioURL = URL.createObjectURL(blob);
        this.audio = this.createAudio(this.audioURL);
        this.audio.preload = 'auto';
        // A failed initial play must NOT revoke the cached audio.
        const result = await this._playAudio(seq,onStart);
        return {...result,mime,bytes:blob.size};
      } catch (error) {
        if (seq !== this._seq) return {status:fullTimedOut?'voice-timeout':'cancelled'};
        console.warn('[mIA HG TTS] Fallo de TTS remoto:', error?.name || error);
        return {status:fetchTimedOut?'voice-fetch-timeout':'voice-network-error',errorName:error?.name||'Error'};
      } finally {
        clearTimeout(fetchTimer);
      }
    })();
    try {
      const result = await Promise.race([work,budget]);
      if (seq === this._seq) this.lastResult = result;
      return result;
    } finally {
      clearTimeout(budgetTimer);
      clearTimeout(fetchTimer);
      if (seq === this._seq) this.controller = null;
      // The audio is intentionally kept for replay()/a second real click.
    }
  }
  replay({onStart} = {}) {
    if (!this.audio) return Promise.resolve({status:'no-cached-audio'});
    if (this._playing) return Promise.resolve({status:'already-playing'});
    return this._playAudio(this._seq,onStart);
  }
  get hasCachedAudio() { return Boolean(this.audio); }
}
