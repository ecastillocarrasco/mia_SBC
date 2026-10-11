/**
 * Catálogo de animaciones y perfiles de comportamiento de mIA.
 *
 * El GLB actual contiene 24 clips corporales Mixamo. Para evitar el efecto
 * "reproducir un vídeo tras otro", los estados del avatar se descomponen en:
 *   - una animación base (cuerpo completo, siempre estable), y
 *   - un gesto superpuesto (torso/cabeza/brazos) cuando procede.
 *
 * El rig facial se añadirá en Blender; esta capa queda preparada para convivir
 * después con visemas, parpadeo y expresiones sin cambiar la API del frontend.
 */

/** Compatibilidad: estado de backend -> clip principal conocido. */
export const STATE_ANIMATION = {
  reposo: "mIA_IDLE",
  escuchando: "mIA_IDLE_BREATHING",
  pensando: "mIA_THINK",
  concentrada: "mIA_TYPING",
  hablando: "mIA_TALK",
  sonriendo: "mIA_IDLE_HAPPY",
  saludando: "mIA_WAVE",
  guinando: "mIA_AGREE",
  sorprendida: "mIA_SURPRISED",
  confundida: "mIA_SHRUG",
  entusiasmada: "mIA_HAPPY_HANDS",
  celebrando: "mIA_CLAP",
  avisando: "mIA_POINT",
  empatica: "mIA_AGREE",
  despedida: "mIA_GREET",
  aprobando: "mIA_AGREE",
};

/** Animaciones que pueden mantenerse en bucle. */
export const LOOPING = new Set([
  "mIA_IDLE",
  "mIA_IDLE_HAPPY",
  "mIA_IDLE_BREATHING",
  "mIA_TALK",
  "mIA_THINK",
  "mIA_TYPING",
  "mIA_WALK",
  "mIA_WALK_FEMALE",
  "mIA_STRUT_WALK",
  "mIA_WALK_BACK",
  "mIA_LOOK_AROUND",
]);

/**
 * Perfiles usados por AvatarController.
 *
 * base:       clip de cuerpo completo que mantiene la postura.
 * gesture:    clip superpuesto al base.
 * mask:       zona corporal a la que se limita el gesto.
 * weight:     intensidad de mezcla del gesto (0..1).
 * loop:       si el gesto se repite.
 * timeScale:  ajuste de velocidad. WAVE se ralentiza porque el clip original
 *             dura aproximadamente medio segundo.
 */
export const STATE_PROFILE = {
  reposo: {
    base: "mIA_IDLE",
    behavior: "idle",
  },
  escuchando: {
    base: "mIA_IDLE_BREATHING",
    behavior: "listening",
  },
  pensando: {
    base: "mIA_IDLE",
    gesture: "mIA_THINK",
    mask: "upper",
    weight: 0.76,
    loop: true,
    behavior: "thinking",
  },
  concentrada: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_TYPING",
    mask: "upper",
    weight: 0.72,
    loop: true,
    behavior: "thinking",
  },
  hablando: {
    base: "mIA_IDLE",
    gesture: "mIA_TALK",
    mask: "upper",
    weight: 0.72,
    loop: true,
    behavior: "speaking",
  },
  sonriendo: {
    base: "mIA_IDLE_HAPPY",
    behavior: "happy",
  },
  saludando: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_WAVE",
    mask: "upper",
    weight: 0.96,
    loop: false,
    timeScale: 0.68,
    behavior: "greeting",
  },
  guinando: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_AGREE",
    mask: "upper",
    weight: 0.78,
    loop: false,
    behavior: "agreeing",
  },
  sorprendida: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_SURPRISED",
    mask: "upper",
    weight: 0.82,
    loop: false,
    behavior: "surprised",
  },
  confundida: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_SHRUG",
    mask: "upper",
    weight: 0.82,
    loop: false,
    behavior: "confused",
  },
  entusiasmada: {
    base: "mIA_IDLE_HAPPY",
    gesture: "mIA_HAPPY_HANDS",
    mask: "upper",
    weight: 0.84,
    loop: false,
    behavior: "happy",
  },
  celebrando: {
    base: "mIA_IDLE_HAPPY",
    gesture: "mIA_CLAP",
    mask: "upper",
    weight: 0.9,
    loop: false,
    behavior: "happy",
  },
  avisando: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_POINT",
    mask: "upper",
    weight: 0.86,
    loop: false,
    behavior: "presenting",
  },
  empatica: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_AGREE",
    mask: "upper",
    weight: 0.78,
    loop: false,
    behavior: "agreeing",
  },
  despedida: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_GREET",
    mask: "upper",
    weight: 0.9,
    loop: false,
    behavior: "greeting",
  },
  aprobando: {
    base: "mIA_IDLE_BREATHING",
    gesture: "mIA_AGREE",
    mask: "upper",
    weight: 0.8,
    loop: false,
    behavior: "agreeing",
  },
};

/**
 * Huesos Mixamo incluidos en cada máscara de gesto.
 * Las comparaciones se hacen contra el nombre del nodo sin distinguir
 * mayúsculas/minúsculas, de modo que seguimos siendo tolerantes a pequeñas
 * variaciones de exportación.
 */
export const BONE_MASKS = {
  head: ["neck", "head", "headtop_end"],
  arms: [
    "leftshoulder", "leftarm", "leftforearm", "lefthand",
    "rightshoulder", "rightarm", "rightforearm", "righthand",
    "lefthandthumb", "lefthandindex", "righthandthumb", "righthandindex",
  ],
  upper: [
    "spine", "spine1", "spine2", "neck", "head", "headtop_end",
    "leftshoulder", "leftarm", "leftforearm", "lefthand",
    "rightshoulder", "rightarm", "rightforearm", "righthand",
    "lefthandthumb", "lefthandindex", "righthandthumb", "righthandindex",
  ],
};

function normalizedTrackNode(trackName) {
  const propertySeparator = trackName.lastIndexOf(".");
  const nodeName = propertySeparator >= 0 ? trackName.slice(0, propertySeparator) : trackName;
  return nodeName.toLowerCase().replace(/^(?:mixamorig|smartrig):/, "");
}

export function trackMatchesMask(trackName, mask = "upper") {
  const allowed = BONE_MASKS[mask];
  if (!allowed) return true;
  const node = normalizedTrackNode(trackName);
  return allowed.some((token) => node === token || node.startsWith(token));
}

/** Devuelve un clip con solo las pistas de la zona corporal solicitada. */
export function maskedClip(originalClip, mask = "upper", suffix = mask) {
  const clip = originalClip.clone();
  clip.name = `${originalClip.name}__${suffix}`;
  clip.tracks = clip.tracks.filter((track) => trackMatchesMask(track.name, mask));
  clip.resetDuration();
  return clip;
}

/**
 * Quita el desplazamiento horizontal de la raíz para que mIA anime en el sitio.
 * Conserva Y para no destruir la componente vertical de la animación original.
 */
export function inPlace(originalClip) {
  const clean = originalClip.clone();
  clean.tracks = clean.tracks.map((track) => {
    const name = track.name.toLowerCase();
    if (!name.endsWith(".position") || !(name.includes("hips") || name.includes("root"))) return track;

    const fixed = track.clone();
    const values = fixed.values;
    if (values.length < 3) return fixed;
    const x0 = values[0];
    const z0 = values[2];
    for (let i = 0; i < values.length; i += 3) {
      values[i] = x0;
      values[i + 2] = z0;
    }
    return fixed;
  });
  clean.resetDuration();
  return clean;
}
