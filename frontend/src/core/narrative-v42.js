/**
 * V4.2 — Narrativa tipográfica escénica (no es tarjeta ni panel de datos).
 * Todo el texto del backend se inserta con textContent para impedir HTML activo.
 */
function splitEditorial(value) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return { lead: "", body: "" };
  const sentences = text.match(/^(.+?[.!?¡¿])(?:\s+|$)([\s\S]*)$/);
  if (sentences && sentences[1].length <= 150) {
    return { lead: sentences[1], body: sentences[2] || "" };
  }
  if (text.length <= 130) return { lead: text, body: "" };
  const pivot = text.lastIndexOf(" ", 122);
  const point = pivot > 55 ? pivot : 122;
  return { lead: text.slice(0, point).trim(), body: text.slice(point).trim() };
}

export class MiaNarrativeV42 {
  constructor(element) {
    this.element = element;
    this.sequence = 0;
  }

  show(text, { kind = "answer" } = {}) {
    if (!this.element) return;
    const { lead, body } = splitEditorial(text);
    if (!lead) return this.clear();

    const container = this.element;
    const epoch = ++this.sequence;
    const kicker = document.createElement("span");
    kicker.className = "mia-narrative-kicker";
    kicker.textContent = kind === "welcome" ? "BIENVENIDO A SUNSET BEACH CLUB" :
      kind === "error" ? "MÍA · AVISO" : "MÍA · CONTIGO";
    const main = document.createElement("span");
    main.className = "mia-narrative-lead";
    main.textContent = lead;
    const copy = document.createElement("span");
    copy.className = "mia-narrative-body";
    copy.textContent = body;
    const accent = document.createElement("span");
    accent.className = "mia-narrative-accent";
    accent.setAttribute("aria-hidden", "true");

    container.replaceChildren(kicker, main, copy, accent);
    container.setAttribute("aria-label", String(text));
    container.dataset.kind = kind;
    container.classList.remove("is-revealed");
    container.classList.add("has-text");
    requestAnimationFrame(() => {
      if (this.sequence === epoch) container.classList.add("is-revealed");
    });
  }

  clear() {
    if (!this.element) return;
    this.sequence += 1;
    this.element.replaceChildren();
    this.element.classList.remove("has-text", "is-revealed");
    this.element.removeAttribute("aria-label");
  }
}
