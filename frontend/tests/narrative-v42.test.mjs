import test from "node:test";
import assert from "node:assert/strict";
import { MiaNarrativeV42 } from "../src/core/narrative-v42.js";

// Regresión real: "Sandra Asencio (Gobernanta, Pisos) cuenta con **6 periodos...**" se mostraba
// con los asteriscos literales en pantalla -- la narrativa es texto plano (nunca innerHTML, por
// seguridad), así que el énfasis Markdown del backend nunca se interpretaba, solo se veía la
// sintaxis en bruto.
function stub() {
  globalThis.requestAnimationFrame = (callback) => callback();
  globalThis.document = {
    createElement: () => ({
      textContent: "", className: "", attrs: {},
      setAttribute(key, value) { this.attrs[key] = value; },
    }),
  };
  const classes = new Set();
  const rootElement = {
    dataset: {}, attrs: {}, children: [],
    classList: {
      add(...xs) { xs.forEach((x) => classes.add(x)); },
      remove(...xs) { xs.forEach((x) => classes.delete(x)); },
    },
    replaceChildren(...elements) { this.children = elements; },
    setAttribute(key, value) { this.attrs[key] = value; },
    removeAttribute(key) { delete this.attrs[key]; },
  };
  return { rootElement, classes };
}

test("strips **negrita** Markdown so the asterisks never show up literally", () => {
  const { rootElement } = stub();
  const narrative = new MiaNarrativeV42(rootElement);
  narrative.show(
    "Sandra Asencio cuenta con **6 periodos de vacaciones aceptados en 2026**: detalle abajo.",
    { kind: "answer" },
  );
  const shown = rootElement.children.map((c) => c.textContent).join(" ");
  assert.doesNotMatch(shown, /\*\*/);
  assert.match(shown, /6 periodos de vacaciones aceptados en 2026/);
  assert.doesNotMatch(rootElement.attrs["aria-label"], /\*\*/);
});

test("strips _cursiva_ and *cursiva* without eating real asterisks/underscores in content", () => {
  const { rootElement } = stub();
  const narrative = new MiaNarrativeV42(rootElement);
  narrative.show("Esto es _importante_ y esto es *también*. 2*3=6 y nombre_variable siguen igual.");
  const shown = rootElement.children.map((c) => c.textContent).join(" ");
  assert.match(shown, /importante/);
  assert.match(shown, /también/);
  assert.match(shown, /2\*3=6/);
  assert.match(shown, /nombre_variable/);
});

test("never renders HTML from backend text (textContent only, security property preserved)", () => {
  const { rootElement } = stub();
  const narrative = new MiaNarrativeV42(rootElement);
  narrative.show("<script>alert('x')</script> Estoy revisando tu información.", { kind: "answer" });
  assert.equal(rootElement.children.length, 4);
  assert.match(rootElement.children[1].textContent, /<script>/);
});
