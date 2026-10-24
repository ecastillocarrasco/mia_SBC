import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
const file = new URL("../src/worlds/hologram/hologram-premium-v5.js", import.meta.url);
const script = await fs.readFile(file, "utf8");
const mod = await import("data:text/javascript;charset=utf-8," + encodeURIComponent(script));

test("saludo dividido en frase completa", () => {
  const value = mod.projectionCopy("¡Hola Enrique! Soy mIA, tu asistente virtual.", "welcome");
  assert.equal(value.headline, "¡Hola Enrique!");
  assert.equal(value.body, "Soy mIA, tu asistente virtual.");
});

test("no fragmenta frases largas de forma arbitraria", () => {
  const sentence = "Estos son los empleados que trabajan ahora mismo en Sunset Beach Club durante la jornada actual sin una conclusión corta";
  const value = mod.projectionCopy(sentence);
  assert.equal(value.headline, "Esto es lo que he encontrado");
  assert.equal(value.body, sentence);
});

test("los estados usan narrativas diferentes", () => {
  assert.equal(mod.projectionCopy("Estamos tramitando tu solicitud.", "waiting").eyebrow, "TRABAJANDO EN TU CONSULTA");
  assert.equal(mod.projectionCopy("Preparado.", "presenting").eyebrow, "INFORMACIÓN EN PANTALLA");
});

test("números españoles no se confunden con separadores de miles", () => {
  assert.equal(mod.parseProjectionNumber("1.234,56 €"), 1234.56);
  assert.equal(mod.parseProjectionNumber("1.234"), 1234);
  assert.equal(mod.parseProjectionNumber("87,3%"), 87.3);
  assert.equal(mod.parseProjectionNumber("1,234.56"), 1234.56);
  assert.equal(mod.parseProjectionNumber("45"), 45);
});

test("valores no numéricos no generan gráfica ficticia", () => {
  for (const value of ["2026-10-01", "Empleado", "", "sin datos", "1.2.3"]) {
    assert.equal(mod.parseProjectionNumber(value), null);
  }
});

test("gráficas necesitan 2 registros numéricos y no negativos", () => {
  const make = (parts) => ({querySelectorAll: () => parts.map((text) => ({textContent:text}))});
  assert.deepEqual(mod.extractBarRows([make(["Cocina","12"])]), []);
  const rows = mod.extractBarRows([make(["Cocina","12"]),make(["Restaurante","8"]),make(["Desconocido","—"])]);
  assert.deepEqual(rows.map((row) => [row.label,row.value]), [["Cocina",12],["Restaurante",8]]);
});

test("clonación de materiales conserva la textura original", () => {
  globalThis.location = {search:""};
  globalThis.innerWidth = 1400;
  globalThis.innerHeight = 800;
  globalThis.devicePixelRatio = 1;
  const map = {colorSpace:"",name:"faceMap"};
  const old = {
    map, color: {multiply(v){this.tint=v}}, emissive: {set(value){this.value=value}},
    emissiveIntensity:0, roughness:.8, metalness:.2, transparent:false,
    clone(){return { ...this, color: {multiply(v){this.tint=v}}, emissive: {set(value){this.value=value}} }}
  };
  const mesh = {isMesh:true,material:old};
  const scene = {
    renderer:{setPixelRatio(value){this.dpr=value}, outputColorSpace:"",toneMapping:""},
    camera:{position:{set(){}},updateProjectionMatrix(){},fov:34},
    target:{set(){}},
    scene:{add(){}},
    model:{traverse(fn){fn(mesh)}},
    resize(){this.resized=true},
  };
  class Color {constructor(v){this.value=v}}
  class Light {constructor(...args){this.args=args;this.position={set(){}}}}
  const THREE = {
    Color, HemisphereLight:Light,DirectionalLight:Light,
    SRGBColorSpace:"srgb", ACESFilmicToneMapping:"ACES", NormalBlending:"normal"
  };
  const info=mod.enhanceHologramAvatar(scene, THREE);
  assert.equal(info.meshes,1);
  assert.equal(info.textures,1);
  assert.notEqual(mesh.material,old);
  assert.equal(mesh.material.map,map);
  assert.equal(old.color.tint,undefined);
  assert.ok(scene.renderer.dpr>=1.5);
  assert.equal(scene.resized,true);
});

test("el main conserva voz, preguntas, 84 clips y micrófono 3 estados", async () => {
  const main = await fs.readFile(new URL("../src/worlds/hologram/main.js", import.meta.url),"utf8");
  for (const phrase of ["new MiaVoiceV4","voice?.cycle()","await client.speak","renderHologramBrief","scene.load(", "sourceClipCount !== 84","new MiaHologramDirectorV52", "premiumStage.dataVisible"]) {
    assert.ok(main.includes(phrase),phrase);
  }
  assert.ok(!main.includes("scene.applyMaterial(() =>"));
  assert.ok(!main.includes("Math.sin(time * 0.19)"));
});
