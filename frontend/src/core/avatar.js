/** Estado del avatar → imagen y etiqueta legible (compartido por 2D y holograma). */
const LABELS = {
  reposo: "Estoy aquí", escuchando: "Te escucho…", pensando: "Estoy pensando…",
  concentrada: "Consultando los datos…", hablando: "Te respondo…", sonriendo: "Encantada de ayudarte",
  saludando: "¡Hola!", guinando: "Entendido", sorprendida: "Vaya, qué interesante",
  confundida: "No estoy segura de haberte entendido", entusiasmada: "¡Qué buena noticia!",
  celebrando: "¡Lo hemos conseguido!", avisando: "Ten en cuenta esto", empatica: "Te entiendo",
  despedida: "Hasta pronto", aprobando: "De acuerdo",
};

export function avatarSrc(state) {
  const safe = LABELS[state] ? state : "reposo";
  return `/assets/avatar/${safe}.png`;
}

export function avatarLabel(state) {
  return LABELS[state] || LABELS.reposo;
}
