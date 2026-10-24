/**
 * mIA · HOLOGRAMA V5 — exclusiva de src/worlds/hologram.
 * Realza los materiales ORIGINALES del GLB, sin retocar rig, geometría o clips.
 * La narración usa texto plano; las visualizaciones solo valores reales recibidos.
 */

const byId = (id) => document.getElementById(id);

export function projectionCopy(input, kind = "answer") {
  const message = String(input ?? "").replace(/\s+/gu, " ").trim();
  if (!message) return { eyebrow: "mIA · EN DIRECTO", headline: "mIA está preparada", body: "" };
  const eyebrow = ({
    welcome: "BIENVENIDO A SUNSET BEACH CLUB",
    waiting: "TRABAJANDO EN TU CONSULTA",
    presenting: "INFORMACIÓN EN PANTALLA",
    answer: "mIA TE RESPONDE",
    error: "REVISAR CONSULTA",
  })[kind] || "mIA TE RESPONDE";

  // El encabezado nunca parte una frase a mitad.
  const welcome = message.match(/^(¡?Hola\b[^.!?]{0,76}[.!?])(?:\s+([\s\S]+))?$/iu);
  if (welcome) return { eyebrow, headline: welcome[1], body: welcome[2] || "" };
  if (message.length <= 91) return { eyebrow, headline: message, body: "" };
  const sentence = message.match(/^(.{12,90}?[.!?])\s+([\s\S]+)$/su);
  if (sentence) return { eyebrow, headline: sentence[1], body: sentence[2] };
  return {
    eyebrow,
    headline: kind === "waiting" ? "Estoy preparando tu respuesta" :
      kind === "presenting" ? "Análisis preparado" : "Esto es lo que he encontrado",
    body: message,
  };
}

export function parseProjectionNumber(raw) {
  let s = String(raw ?? "").trim().replace(/[\u00a0\s]/gu, "");
  if (!/^[+-]?[\d.,]+(?:[%€])?$/u.test(s)) return null;
  s = s.replace(/[€%]/gu, "");
  if (!/\d/u.test(s)) return null;
  if (s.includes(",") && s.includes(".")) {
    const lastComma = s.lastIndexOf(",");
    const lastDot = s.lastIndexOf(".");
    s = lastComma > lastDot
      ? s.replace(/\./gu, "").replace(",", ".")
      : s.replace(/,/gu, "");
  } else if (s.includes(",")) {
    s = /^\d{1,3}(?:,\d{3})+$/u.test(s) ? s.replace(/,/gu, "") : s.replace(",", ".");
  } else if (/^\d{1,3}(?:\.\d{3})+$/u.test(s)) {
    s = s.replace(/\./gu, "");
  }
  const value = Number(s);
  return Number.isFinite(value) ? value : null;
}

export function extractBarRows(rows) {
  // 2 a 6 observaciones numéricas comparables, siempre procedentes del backend.
  const points = [];
  for (const row of rows || []) {
    const cells = [...row.querySelectorAll("td")];
    if (cells.length < 2) continue;
    const label = cells[0].textContent.trim();
    const valueLabel = cells[cells.length - 1].textContent.trim();
    const value = parseProjectionNumber(valueLabel);
    if (!label || value === null || value < 0 || value > 1e12) continue;
    points.push({ label, value, valueLabel });
    if (points.length === 6) break;
  }
  return points.length >= 2 ? points : [];
}

export function enhanceHologramAvatar(scene, THREE) {
  if (!scene?.model || !scene?.renderer || !THREE) return { meshes: 0, textures: 0 };
  const quality = new URLSearchParams(location.search).get("quality");
  const requested = quality === "ultra" ? 2.5 : 2;
  // Supersampling incluso en pantallas de DPR 1, con presupuesto GPU.
  const pixels = Math.max(1, innerWidth * innerHeight);
  const gpuBudget = quality === "ultra" ? 10_000_000 : 7_000_000;
  const gpuCap = Math.sqrt(gpuBudget / pixels);
  const baseDpr = Math.max(devicePixelRatio || 1, quality === "ultra" ? 2 : 1.5);
  scene.renderer.setPixelRatio(Math.max(1, Math.min(baseDpr, requested, gpuCap)));
  scene.renderer.outputColorSpace = THREE.SRGBColorSpace;
  scene.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  scene.renderer.toneMappingExposure = 1.18;

  const fan = new URLSearchParams(location.search).get('fan') === '1';
  const portrait = new URLSearchParams(location.search).get('shot') === 'portrait';
  // Proyeccion: encuadre dentro del circulo util del ventilador; 3D no cambia.
  scene.camera.fov = portrait ? 29 : fan ? 35 : 32;
  scene.camera.position.set(0, portrait ? 1.65 : fan ? 1.18 : 1.33,
    portrait ? 2.65 : fan ? 5.35 : 4.55);
  scene.target.set(0, portrait ? 1.74 : fan ? 1.14 : 1.12, 0);
  scene.camera.updateProjectionMatrix();
  scene.resize();

  // Iluminación del MUNDO holograma: no afecta al GLB ni a otros mundos.
  scene.scene.add(new THREE.HemisphereLight(0xc8f9ff, 0x0b2637, 1.45));
  const key = new THREE.DirectionalLight(0xf0ffff, 2.15);
  key.position.set(-2.3, 4.0, 4.1);
  scene.scene.add(key);
  const fill = new THREE.DirectionalLight(0x43d8ff, 0.95);
  fill.position.set(2.4, 1.3, 3.0);
  scene.scene.add(fill);
  const rim = new THREE.DirectionalLight(0x37d9ff, 1.4);
  rim.position.set(0.2, 2.6, -2.3);
  scene.scene.add(rim);

  const cloned = new WeakMap();
  let meshes = 0, textures = 0;
  function convert(old) {
    if (!old || typeof old.clone !== "function") return old;
    if (cloned.has(old)) return cloned.get(old);
    const material = old.clone();
    // Si el material original es un ShaderMaterial, no puede recuperar
    // por sí solo una textura que ya haya sido descartada.
    if (old.isShaderMaterial) {
      console.warn("[mIA HG V5] No se puede recuperar la textura desde un shader anterior.");
      cloned.set(old, old);
      return old;
    }
    if (material.color) material.color.multiply(new THREE.Color(0xd9f8ff));
    if (material.emissive) {
      material.emissive.set(0x073744);
      material.emissiveIntensity = 0.38;
    }
    if ("metalness" in material) material.metalness = 0.10;
    if ("roughness" in material) material.roughness = 0.61;
    if (material.map) {
      material.map.colorSpace = THREE.SRGBColorSpace;
      textures += 1;
    }
    // Dejamos intacto el normalMap por defecto: parte del relieve puede
    // corresponder a detalles de la cara. Probar ?softNormals=1 si da artefactos.
    if (new URLSearchParams(location.search).get("softNormals") === "1") {
      if (material.normalMap) material.normalScale?.set(0.16, 0.16);
      if (material.bumpMap) material.bumpScale = 0.02;
    }
    material.blending = THREE.NormalBlending;
    material.depthWrite = true;
    material.depthTest = true;
    material.needsUpdate = true;
    cloned.set(old, material);
    return material;
  }

  scene.model.traverse((obj) => {
    if (!obj.isMesh) return;
    obj.material = Array.isArray(obj.material)
      ? obj.material.map(convert)
      : convert(obj.material);
    meshes++;
  });
  // No imponemos transparencia sobre la cara: evita "ojos vacíos".
  console.info(`[mIA HG V5] ${meshes} mallas, ${textures} texturas preservadas`);
  return { meshes, textures };
}

export function createHologramStage() {
  const eyebrow = byId("hgEyebrow");
  const headline = byId("hgHeadline");
  const narrative = byId("hgNarrative");
  const presentation = byId("hgDataPanel");
  const bars = byId("hgChart");
  const gauge = byId("hgGauge");
  const empty = byId("hgStandby");
  const stateLabel = byId("hgState");
  const shell = byId("hgShell");
  const fan = new URLSearchParams(location.search).get("fan") === "1";
  document.body.classList.toggle("hg-fan", fan);
  document.body.classList.toggle('hg-fan-controls', fan &&
    new URLSearchParams(location.search).get('controls') === '1');

  let lastMessage = "", lastKind = "";
  function caption(text, kind = "answer") {
    const message = String(text ?? "");
    if (message === lastMessage && kind === lastKind) return;
    lastMessage = message;
    lastKind = kind;
    const copy = projectionCopy(message, kind);
    eyebrow.textContent = copy.eyebrow;
    headline.textContent = copy.headline;
    narrative.textContent = copy.body;
    shell.dataset.state = kind;

    for (const node of [headline, narrative]) {
      node.classList.remove("hg-enter");
      void node.offsetWidth;
      node.classList.add("hg-enter");
    }
    if (stateLabel) stateLabel.textContent =
      kind === "waiting" ? "PROCESANDO" :
      kind === "presenting" ? "DATOS EN PANTALLA" :
      kind === "error" ? "REVISAR" : "ASISTENTE ACTIVA";
  }

  function chartFromRenderedTable(resultEl) {
    bars.replaceChildren();
    const rows = [...resultEl.querySelectorAll(".hg-mini-table tbody tr")];
    const points = extractBarRows(rows);
    if (points.length < 2) return 0;
    const label = document.createElement("div");
    label.className = "hg-chart-title";
    label.textContent = "COMPARATIVA VISUAL";
    bars.append(label);
    const max = Math.max(1, ...points.map((p) => p.value));
    points.forEach((point, i) => {
      const row = document.createElement("div");
      row.className = "hg-chart-row";
      const name = document.createElement("span");
      name.className = "hg-chart-name";
      name.textContent = point.label;
      name.title = point.label;
      const track = document.createElement("div");
      track.className = "hg-chart-track";
      const fill = document.createElement("span");
      fill.className = "hg-chart-fill";
      fill.style.setProperty("--hg-width", `${Math.max(3, 100 * point.value / max)}%`);
      fill.style.setProperty("--hg-delay", `${i * 95}ms`);
      track.append(fill);
      const value = document.createElement("strong");
      value.className = "hg-chart-value";
      value.textContent = point.valueLabel;
      row.append(name, track, value);
      bars.append(row);
    });
    return points.length;
  }

  function renderGauge(resultEl) {
    gauge.replaceChildren();
    const kpis = [...resultEl.querySelectorAll(".hg-kpi")];
    const found = kpis.map((item) => {
      const name = item.querySelector("span")?.textContent?.trim() || "Indicador";
      const raw = item.querySelector("strong")?.textContent?.trim() || "";
      const unit = item.querySelector("small")?.textContent?.trim() || "";
      if (!raw.includes("%") && !unit.includes("%")) return null;
      const value = parseProjectionNumber(raw);
      return value !== null && value >= 0 && value <= 100 ? { name, value } : null;
    }).find(Boolean);
    if (!found) return false;

    const card = document.createElement("div");
    card.className = "hg-gauge-card";
    const circular = document.createElement("div");
    circular.className = "hg-gauge-circle";
    circular.style.setProperty("--percentage", `${found.value}%`);
    const number = document.createElement("strong");
    number.textContent = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 })
      .format(found.value) + "%";
    circular.append(number);
    const name = document.createElement("span");
    name.className = "hg-gauge-name";
    name.textContent = found.name;
    card.append(circular, name);
    gauge.append(card);
    return true;
  }

  function dataVisible(visible, resultEl) {
    const present = Boolean(visible && resultEl?.textContent.trim());
    presentation.classList.toggle("hg-with-data", present);
    empty.hidden = present;
    if (present) {
      const barCount = chartFromRenderedTable(resultEl);
      const hasGauge = renderGauge(resultEl);
      const kpis = resultEl.querySelectorAll('.hg-kpi').length;
      presentation.classList.toggle('hg-has-kpis', kpis > 0);
      presentation.classList.toggle('hg-has-bars', barCount > 0);
      presentation.classList.toggle('hg-has-gauge', hasGauge);
    } else {
      bars.replaceChildren();
      gauge.replaceChildren();
      presentation.classList.remove('hg-has-kpis','hg-has-bars','hg-has-gauge');
    }
  }

  function speaking(active) {
    document.body.classList.toggle("hg-speaking", Boolean(active));
  }

  function waiting(active) {
    document.body.classList.toggle("hg-waiting", Boolean(active));
  }

  return { caption, dataVisible, speaking, waiting, fan };
}
