/**
 * mIA - motor compartido de gráficos de datos en 3D real (barras, donut y
 * línea/cinta temporal), usado por el mundo 3D y el holograma. Nunca lee el
 * DOM: recibe filas ya estructuradas de quien lo llama. El panel plano HTML
 * sigue siendo la fuente completa de datos/accesibilidad; esto es un
 * refuerzo visual que vive flotando junto al avatar, nunca dentro del panel.
 *
 * Cada barra/gajo/punto lleva su propia etiqueta (nombre + cifra) en una
 * sprite de texto que siempre mira a cámara: sin etiqueta, un grupo de
 * formas de colores no dice nada por sí solo.
 */
import * as THREE from 'three';

const DEFAULT_PALETTE = ['#d1a85c', '#83d0ca', '#e87959', '#90a7d4', '#b99bd6', '#7c9295', '#d6b88e'];

function buildSliceGeometry(innerR, outerR, startAngle, sweepAngle, depth) {
  // THREE.CylinderGeometry con thetaStart/thetaLength no cierra bien las
  // paredes radiales ni el agujero central de un gajo de donut; un Shape
  // extruido sí genera esas caras automáticamente.
  const shape = new THREE.Shape();
  shape.absarc(0, 0, outerR, startAngle, startAngle + sweepAngle, false);
  shape.lineTo(innerR * Math.cos(startAngle + sweepAngle), innerR * Math.sin(startAngle + sweepAngle));
  shape.absarc(0, 0, innerR, startAngle + sweepAngle, startAngle, true);
  shape.closePath();
  return new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 24 });
}

function systemReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
}

function truncateLabel(text, max = 14) {
  const s = String(text ?? '').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function formatValue(value) {
  const abs = Math.abs(value);
  return new Intl.NumberFormat('es-ES', {
    maximumFractionDigits: abs >= 100 ? 0 : abs >= 10 ? 1 : 2,
    notation: abs >= 100000 ? 'compact' : 'standard',
  }).format(value);
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Sprite de texto (nombre + cifra) que siempre mira a cámara. No requiere cargar ninguna fuente 3D. */
function makeLabelSprite(lines) {
  const canvas = document.createElement('canvas');
  canvas.width = 384;
  canvas.height = 150;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(8,20,26,.74)';
  roundRect(ctx, 3, 3, canvas.width - 6, canvas.height - 6, 22);
  ctx.fill();
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  if (lines.length === 1) {
    ctx.fillStyle = '#fff6e6';
    ctx.font = '700 48px system-ui, Arial, sans-serif';
    ctx.fillText(lines[0], canvas.width / 2, canvas.height / 2);
  } else {
    ctx.fillStyle = '#d8ece9';
    ctx.font = '600 32px system-ui, Arial, sans-serif';
    ctx.fillText(lines[0], canvas.width / 2, canvas.height * 0.36);
    ctx.fillStyle = '#ffd98a';
    ctx.font = '700 50px system-ui, Arial, sans-serif';
    ctx.fillText(lines[1], canvas.width / 2, canvas.height * 0.74);
  }
  const texture = new THREE.CanvasTexture(canvas);
  if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(.6, .6 * (canvas.height / canvas.width), 1);
  sprite.renderOrder = 10;
  return sprite;
}

// Fracción del medio-alto del frustum (a la profundidad elegida) que ocupa como
// máximo el gráfico: el tamaño real en unidades de mundo se deriva de esto en
// _setAnchor(), nunca de constantes fijas — así nunca puede salir más grande
// que la pantalla ni depende de a qué FOV/profundidad se configure la escena.
const SIZE_FRACTION = .3;

export class DataChart3D {
  constructor(scene, { reducedMotion = false, minWidth = 1100, maxBars = 5, depth = 2.2, palette = DEFAULT_PALETTE } = {}) {
    this.scene = scene;
    this.reducedMotion = reducedMotion;
    this.minWidth = minWidth;
    this.maxBars = maxBars;
    this.depth = depth;
    this._anchor = { x: 0, y: 0 };
    this._offset = new THREE.Vector3();
    this._labels = [];

    this._group = new THREE.Group();
    this._group.name = 'mIA_DataChart3D';
    this._group.visible = false;
    this._barGroup = new THREE.Group();
    this._donutGroup = new THREE.Group();
    this._lineGroup = new THREE.Group();
    this._group.add(this._barGroup, this._donutGroup, this._lineGroup);
    this.scene.scene.add(this._group);

    this._materials = palette.map((hex) => {
      const color = new THREE.Color(hex);
      return new THREE.MeshStandardMaterial({
        color, metalness: .22, roughness: .42,
        emissive: color.clone().multiplyScalar(.12), transparent: true, opacity: .9,
      });
    });
    this._barGeometry = new THREE.BoxGeometry(1, 1, 1);
    this._barMeshes = Array.from({ length: maxBars }, (_, i) => {
      const mesh = new THREE.Mesh(this._barGeometry, this._materials[i % this._materials.length]);
      mesh.visible = false;
      this._barGroup.add(mesh);
      return mesh;
    });
    this._donutMeshes = [];
    this._lineMesh = null;

    // Cadena cooperativa: nunca pisa a un consumidor anterior de onFrame
    // (p. ej. HolographicResults3D). Instanciar DESPUÉS de esos consumidores.
    this._previousOnFrame = scene.onFrame;
    this._ourOnFrame = (t) => {
      if (this._previousOnFrame) this._previousOnFrame.call(this.scene, t);
      this._frame(t);
    };
    scene.onFrame = this._ourOnFrame;
  }

  _canShow() {
    return !this.reducedMotion && !systemReducedMotion() && window.innerWidth >= this.minWidth;
  }

  /** chart: {type:'bars'|'donut'|'line', title, rows:[{label,value,unit?}]} | null. Nunca inventa datos. */
  show(chart, { anchorRect } = {}) {
    if (!chart || !Array.isArray(chart.rows) || chart.rows.length < 2 || !anchorRect || !this._canShow()) {
      this.hide();
      return;
    }
    this._setAnchor(anchorRect);
    this._clearLabels();
    if (chart.type === 'donut') this._layoutDonut(chart.rows);
    else if (chart.type === 'line') this._layoutLine(chart.rows);
    else this._layoutBars(chart.rows);
    this._barGroup.visible = chart.type !== 'donut' && chart.type !== 'line';
    this._donutGroup.visible = chart.type === 'donut';
    this._lineGroup.visible = chart.type === 'line';
    this._group.visible = true;
  }

  hide() {
    this._group.visible = false;
  }

  _setAnchor(rect) {
    const camera = this.scene.camera;
    const vw = window.innerWidth, vh = window.innerHeight;
    const worldHalfH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * this.depth;
    const worldHalfW = worldHalfH * camera.aspect;
    // Ancla a la izquierda del rect (zona libre junto al avatar), nunca sobre el propio panel.
    // La Y es una fracción fija del viewport (altura de pecho del avatar), NUNCA derivada de
    // rect.height: el panel ocupa casi toda la pantalla, así que usar su alto como referencia
    // empujaba el ancla (y por tanto las barras, que crecen hacia arriba desde ahí) muy arriba,
    // por encima de la cabeza del avatar.
    const margin = Math.max(70, rect.width * .08);
    const pxX = Math.max(60, rect.left - margin);
    const pxY = vh * .56;
    this._anchor = {
      x: (pxX / vw * 2 - 1) * worldHalfW,
      y: (1 - pxY / vh * 2) * worldHalfH,
    };
    // Las geometrías de barras/donut/línea están definidas en unidades "normalizadas" (altura/
    // radio máximos ≈ 1); el tamaño real en unidades de mundo se fija aquí como una fracción del
    // medio-alto visible del frustum a esta profundidad, así nunca puede salirse de pantalla ni
    // depender a ciegas de constantes absolutas (eso fue lo que produjo barras gigantes).
    this._group.scale.setScalar(worldHalfH * SIZE_FRACTION);
  }

  _clearLabels() {
    for (const sprite of this._labels) {
      sprite.material.map?.dispose();
      sprite.material.dispose();
      sprite.parent?.remove(sprite);
    }
    this._labels = [];
  }

  _addLabel(lines, position, parentGroup) {
    const sprite = makeLabelSprite(lines);
    sprite.position.copy(position);
    parentGroup.add(sprite);
    this._labels.push(sprite);
  }

  _layoutBars(rows) {
    const visible = rows.slice(0, this.maxBars);
    const max = Math.max(...visible.map((row) => Math.abs(row.value)), 1);
    const gap = .28;
    const barSide = .16;
    // El ancla (_anchor, ver _setAnchor) marca el borde DERECHO del contenido, junto al
    // panel: todo crece hacia la izquierda desde ahí, nunca centrado sobre el ancla —
    // centrarlo hacía que la mitad derecha invadiera el panel (visto en pruebas reales).
    const totalWidth = (visible.length - 1) * gap;
    visible.forEach((row, i) => {
      const mesh = this._barMeshes[i];
      const ratio = Math.max(.08, Math.min(1, Math.abs(row.value) / max));
      const x = i * gap - totalWidth;
      mesh.scale.set(barSide, ratio, barSide);
      mesh.position.set(x, ratio / 2, 0);
      mesh.material = this._materials[i % this._materials.length];
      mesh.visible = true;
      this._addLabel(
        [truncateLabel(row.label), `${formatValue(row.value)}${row.unit === '%' ? '%' : ''}`],
        new THREE.Vector3(x, ratio + .24, 0), this._barGroup,
      );
    });
    for (let i = visible.length; i < this._barMeshes.length; i++) this._barMeshes[i].visible = false;
  }

  _layoutDonut(rows) {
    for (const mesh of this._donutMeshes) {
      mesh.geometry.dispose();
      this._donutGroup.remove(mesh);
    }
    this._donutMeshes = [];
    const positive = rows.filter((row) => row.value > 0).slice(0, 8);
    const total = positive.reduce((sum, row) => sum + row.value, 0);
    if (!total) return;
    const outerR = 1, innerR = .55, sliceDepth = .4;
    const labelR = outerR + .38;
    // Igual que en las barras: el ancla es el borde derecho, así que todo el donut (incluidas
    // sus etiquetas, que sobresalen hasta labelR) se desplaza a la izquierda esa distancia.
    this._donutGroup.position.x = -labelR;
    // Gajos finos adyacentes (ángulos medios muy próximos) se pisan si todas las etiquetas
    // viven en el mismo radio: alterna un radio más lejano cuando la separación angular con
    // la etiqueta anterior es pequeña, para separarlas en vez de amontonarlas.
    const minGap = .34;
    let angle = -Math.PI / 2;
    let previousMid = null;
    let stagger = false;
    positive.forEach((row, i) => {
      const sweep = (row.value / total) * Math.PI * 2;
      const geometry = buildSliceGeometry(innerR, outerR, angle, sweep, sliceDepth);
      const mesh = new THREE.Mesh(geometry, this._materials[i % this._materials.length]);
      mesh.position.z = -sliceDepth / 2;
      this._donutGroup.add(mesh);
      this._donutMeshes.push(mesh);
      const mid = angle + sweep / 2;
      stagger = previousMid != null && Math.abs(mid - previousMid) < minGap ? !stagger : false;
      const r = stagger ? labelR + .26 : labelR;
      const pct = Math.round((row.value / total) * 100);
      this._addLabel(
        [truncateLabel(row.label), `${pct}%`],
        new THREE.Vector3(Math.cos(mid) * r, Math.sin(mid) * r, 0), this._donutGroup,
      );
      previousMid = mid;
      angle += sweep;
    });
  }

  _layoutLine(rows) {
    if (this._lineMesh) {
      this._lineMesh.geometry.dispose();
      this._lineGroup.remove(this._lineMesh);
      this._lineMesh = null;
    }
    const points = rows.slice(0, 14);
    if (points.length < 2) return;
    const values = points.map((row) => row.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 1e-6);
    // Ancla = borde derecho (ver _layoutBars): el último punto (más reciente) cae en x=0,
    // junto al panel, y la curva se extiende hacia la izquierda, hacia el pasado.
    const spread = 1.3;
    const curvePoints = points.map((row, i) => {
      const x = points.length === 1 ? 0 : (i / (points.length - 1) - 1) * spread * 2;
      const y = ((row.value - min) / range) * .8 - .05;
      return new THREE.Vector3(x, y, 0);
    });
    const curve = new THREE.CatmullRomCurve3(curvePoints, false, 'catmullrom', .25);
    const geometry = new THREE.TubeGeometry(curve, Math.max(24, points.length * 6), .045, 10, false);
    this._lineMesh = new THREE.Mesh(geometry, this._materials[1]);
    this._lineGroup.add(this._lineMesh);

    const peakIndex = values.indexOf(max);
    const labelAt = (i) => {
      const pos = curvePoints[i].clone();
      pos.y += .22;
      this._addLabel([truncateLabel(points[i].label, 10), formatValue(points[i].value)], pos, this._lineGroup);
    };
    labelAt(0);
    if (peakIndex > 0 && peakIndex < points.length - 1) labelAt(peakIndex);
    labelAt(points.length - 1);
  }

  _frame(time) {
    if (!this._group.visible) return;
    const camera = this.scene.camera;
    this._offset.set(this._anchor.x, this._anchor.y, -this.depth).applyQuaternion(camera.quaternion);
    this._group.position.copy(camera.position).add(this._offset);
    this._group.quaternion.copy(camera.quaternion);
    this._group.rotation.y = -.05 + Math.sin(time * .5) * .025;
  }

  dispose() {
    this.hide();
    if (this.scene.onFrame === this._ourOnFrame) this.scene.onFrame = this._previousOnFrame;
    this._clearLabels();
    this._barGeometry.dispose();
    this._materials.forEach((material) => material.dispose());
    for (const mesh of this._donutMeshes) mesh.geometry.dispose();
    if (this._lineMesh) this._lineMesh.geometry.dispose();
    this._group.parent?.remove(this._group);
  }
}
