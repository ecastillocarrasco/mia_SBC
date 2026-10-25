/**
 * Núcleo compartido por los tres mundos (2D, 3D, holograma): sesión, streaming del
 * chat y voz. Nada de UI aquí — cada mundo se encarga de mostrarlo a su manera.
 *
 * Contrato del backend (mia/api): POST /api/chat/stream devuelve eventos SSE
 * (session, avatar, speech, progress, tool, result); POST /api/voice/stream
 * devuelve audio en streaming para un texto dado.
 */

import { getAccessToken } from "./auth-gate.js";
import { withSpokenName } from "./speech-text.js";

export const AVATAR_STATES = [
  "reposo", "escuchando", "pensando", "concentrada", "hablando", "sonriendo", "saludando",
  "guinando", "sorprendida", "confundida", "entusiasmada", "celebrando", "avisando",
  "empatica", "despedida", "aprobando",
];

const SESSION_KEY = "mia.session_id";

function speakWithBrowser(text, lang = "es-ES") {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang?.startsWith("es"));
    if (voice) utterance.voice = voice;
    utterance.addEventListener("end", resolve, { once: true });
    utterance.addEventListener("error", resolve, { once: true });
    window.speechSynthesis.speak(utterance);
  });
}

function parseSseBlock(block) {
  let type = "message";
  let data = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) {
      try {
        data = JSON.parse(line.slice(5).trim());
      } catch {
        data = null;
      }
    }
  }
  return data === null ? null : { type, data };
}

export class MiaClient extends EventTarget {
  constructor({ apiBase = "", persistSession = true } = {}) {
    super();
    this.apiBase = apiBase;
    this.persistSession = persistSession;
    this.sessionId = persistSession ? sessionStorage.getItem(SESSION_KEY) : null;
    this._voiceAudio = null;
  }

  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail }));
  }

  /** Cabecera Authorization (Bearer) si hay sesión Entra activa; objeto vacío en modo dev/easyauth,
   * donde `getAccessToken()` devuelve `null` porque nunca se inicializó MSAL (ver auth-gate.js). */
  async _authHeaders() {
    const token = await getAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  /** Envía un mensaje y va emitiendo eventos según llegan; devuelve el TurnResult final. */
  async send(message, { attachmentIds = [] } = {}) {
    this._emit("sending", { message });
    const body = { message, session_id: this.sessionId };
    if (attachmentIds.length) body.attachment_ids = attachmentIds;
    const response = await fetch(`${this.apiBase}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await this._authHeaders()) },
      body: JSON.stringify(body),
    });
    if (!response.ok || !response.body) {
      const detail = { status: response.status };
      this._emit("error", detail);
      throw new Error(`chat/stream HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let result = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const event = parseSseBlock(block);
        if (!event) continue;
        this._handle(event);
        if (event.type === "result") result = event.data.result;
      }
    }
    if (!result) throw new Error("El stream terminó sin un evento «result»");
    return result;
  }

  _handle(event) {
    if (event.type === "session") {
      this.sessionId = event.data.session_id;
      if (this.persistSession) sessionStorage.setItem(SESSION_KEY, this.sessionId);
    }
    this._emit(event.type, event.data);
  }

  /** Reproduce la voz de un texto. Devuelve una promesa que se resuelve al terminar (o al fallar). */
  async speak(text, { onStart } = {}) {
    this.stopSpeaking();
    if (!text?.trim()) return;
    const spoken = withSpokenName(text);
    try {
      const response = await fetch(`${this.apiBase}/api/voice/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await this._authHeaders()) },
        body: JSON.stringify({ text: spoken }),
      });
      if (!response.ok) throw new Error(`voice/stream HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this._voiceAudio = audio;
      onStart?.();
      await new Promise((resolve) => {
        audio.addEventListener("ended", resolve, { once: true });
        audio.addEventListener("error", resolve, { once: true });
        audio.play().catch(resolve);
      });
    } catch (error) {
      // Igual que antes: si ElevenLabs no responde, habla la voz del navegador.
      console.warn("[mIA] voz no disponible, uso la del navegador:", error);
      onStart?.();
      await speakWithBrowser(spoken);
    } finally {
      if (this._voiceAudio) URL.revokeObjectURL(this._voiceAudio.src);
      this._voiceAudio = null;
    }
  }

  stopSpeaking() {
    window.speechSynthesis?.cancel();
    if (this._voiceAudio) {
      try {
        this._voiceAudio.pause();
      } catch {
        /* noop */
      }
    }
  }

  resetSession() {
    this.sessionId = null;
    if (this.persistSession) sessionStorage.removeItem(SESSION_KEY);
  }
}
