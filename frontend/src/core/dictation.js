/** Dictado por voz (Web Speech API), igual que los frontends anteriores. Devuelve null si el
 * navegador no lo soporta (Firefox): el botón de micrófono se oculta en ese caso. */
export function createDictation({ lang = "es-ES", onInterim, onFinal, onListening } = {}) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return null;
  const recognition = new Recognition();
  recognition.lang = lang;
  recognition.continuous = false;
  recognition.interimResults = true;
  let listening = false;
  recognition.addEventListener("start", () => { listening = true; onListening?.(true); });
  recognition.addEventListener("end", () => { listening = false; onListening?.(false); });
  recognition.addEventListener("error", () => { listening = false; onListening?.(false); });
  recognition.addEventListener("result", (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const text = event.results[i][0].transcript;
      if (event.results[i].isFinal) onFinal?.(text.trim());
      else interim += text;
    }
    if (interim) onInterim?.(interim);
  });
  return {
    toggle() {
      if (listening) recognition.stop();
      else try { recognition.start(); } catch { /* ya estaba iniciándose */ }
    },
    stop() { if (listening) recognition.stop(); },
  };
}

/** Enlaza un botón de micrófono con un mundo: dicta y envía al terminar. */
export function bindMicButton(button, { onInterim, onFinal }) {
  const dictation = createDictation({
    onInterim,
    onFinal,
    onListening: (on) => {
      button.classList.toggle("listening", on);
      button.setAttribute("aria-pressed", String(on));
    },
  });
  if (!dictation) {
    button.hidden = true;
    return null;
  }
  button.addEventListener("click", () => dictation.toggle());
  return dictation;
}
