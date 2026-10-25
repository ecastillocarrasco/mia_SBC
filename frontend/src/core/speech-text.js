/**
 * Normalización mínima de texto antes de enviarlo a voz (TTS/browser). El
 * nombre se escribe siempre "mIA" en texto, pero debe pronunciarse "Mía"
 * (dos sílabas, acento en la primera). Usado por los mundos 3D y holograma;
 * 2D ya aplica su propia normalización más amplia en prepareSpeechText().
 */
export function withSpokenName(text) {
  return String(text ?? "").replace(/\bmIA\b/gi, "Mía");
}
