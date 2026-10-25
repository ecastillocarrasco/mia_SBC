/**
 * Preferencia de silenciar la voz de mIA, compartida por los tres mundos
 * (2D, 3D, holograma) en el mismo navegador. Por defecto mIA NO está
 * silenciada. Persistida en localStorage para que sobreviva a recargas.
 */
const KEY = "mia.voice_muted";

export function isVoiceMuted() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setVoiceMuted(muted) {
  try {
    localStorage.setItem(KEY, muted ? "1" : "0");
  } catch {
    /* localStorage no disponible (modo privado, etc.): el flag vive solo en memoria */
  }
}
