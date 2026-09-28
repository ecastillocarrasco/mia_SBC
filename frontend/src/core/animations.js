/** Estado del avatar (backend) → animación del modelo mIA_WEB.glb (compartido por 3D y holograma).
 * Las 24 animaciones del modelo se leyeron del propio GLB; si alguna faltara en otra
 * versión del modelo, playState() cae a mIA_IDLE en lugar de fallar. */
export const STATE_ANIMATION = {
  reposo: "mIA_IDLE", escuchando: "mIA_IDLE_STANDING", pensando: "mIA_THINK", concentrada: "mIA_TYPING",
  hablando: "mIA_TALK", sonriendo: "mIA_IDLE_HAPPY", saludando: "mIA_WAVE", guinando: "mIA_YES",
  sorprendida: "mIA_SURPRISED", confundida: "mIA_SHRUG", entusiasmada: "mIA_HAPPY", celebrando: "mIA_CLAP",
  avisando: "mIA_POINT", empatica: "mIA_AGREE", despedida: "mIA_GREET", aprobando: "mIA_YES",
};

/** Animaciones que se repiten; el resto se reproducen una vez y vuelven a la de reposo. */
export const LOOPING = new Set([
  "mIA_IDLE", "mIA_IDLE_HAPPY", "mIA_IDLE_STANDING", "mIA_TALK", "mIA_THINK", "mIA_TYPING",
  "mIA_WALK", "mIA_WALK_ALT", "mIA_STRUT_WALK", "mIA_WALK_BACK", "mIA_LOOK_AROUND",
]);

/** Quita el desplazamiento de la raíz para que mIA anime en el sitio (misma técnica que el frontend anterior). */
export function inPlace(clip) {
  const clean = clip.clone();
  for (const track of clean.tracks) {
    const name = track.name.toLowerCase();
    if (!name.endsWith(".position") || !(name.includes("hips") || name.includes("root"))) continue;
    const v = track.values;
    for (let i = 3; i < v.length; i += 3) {
      v[i] = v[0];
      v[i + 2] = v[2];
    }
  }
  return clean;
}
