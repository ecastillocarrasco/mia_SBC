/**
 * mIA | Spatial Results Breakout V3 - world 3D ONLY.
 *
 * Source of truth remains the existing results DOM in #conversation. No result
 * data is cloned or recalculated here. This module only stages the validated
 * panel in depth, adds a breakout frame behind it and enhances existing KPI /
 * chart blocks so they feel like they emerge from the screen.
 *
 * Escape hatches: ?holo3d=0 (plain layout), ?breakout3d=0 (V1 spatial look).
 */
import * as THREE from 'three';

export function shouldUseSpatialResults({ enabled = true, reducedMotion = false, width = 1440 } = {}) {
  return Boolean(enabled && !reducedMotion && width >= 1100);
}

const CARD_SELECTORS = [
  '.stat-kpis article',
  '.stat-metric-tile',
  '.e360-kpi',
  '.e360x-kpis article',
  '.stat-kpi-cluster article',
  '.mia-kv > div',
  '.e360x-hero',
  '.e360x-action',
];

const SURFACE_SELECTORS = [
  '.stat-chart',
  '.statistical-visuals',
  '.premium-table-shell',
  '.e360x-section',
  '.e360x-complete',
  '.presentation-detail',
  '.mia-results-summary',
  '.mia45-coverage',
];

export class HolographicResults3D {
  constructor({ scene, panel, root = document.body, reducedMotion = false } = {}) {
    this.scene = scene;
    this.panel = panel;
    this.root = root;
    this.reducedMotion = Boolean(reducedMotion);
    const query = new URLSearchParams(window.location.search);
    this.enabled = query.get('holo3d') !== '0';
    this.breakoutEnabled = query.get('breakout3d') !== '0';
    this.hasResult = false;
    this.reading = false;
    this._pendingPointerFrame = 0;
    this._revealFrame = 0;
    this._readingTimer = 0;
    this._pointer = { x: 0, y: 0 };
    this._offset = new THREE.Vector3();
    this._emitterLocation = { x: .2, y: .15 };
    this._portalLocation = { x: 0, y: 0 };
    this._portalSize = { w: 1, h: 1 };
    this._decorated = [];
    this._buildOverlay();
    this._buildEmitter();
    this._buildBreakoutGeometry();

    this._previousFrame = scene.onFrame;
    this._ourFrame = (t) => {
      if (this._previousFrame) this._previousFrame.call(this.scene, t);
      this._frame(t);
    };
    scene.onFrame = this._ourFrame;
    this._onResize = () => this._syncLayout();
    window.addEventListener('resize', this._onResize, { passive: true });
    this._onPointerMove = (e) => this._pointerMove(e);
    this._onPointerLeave = () => this._resetPointer();
    this.panel.addEventListener('pointermove', this._onPointerMove, { passive: true });
    this.panel.addEventListener('pointerleave', this._onPointerLeave);
  }

  _buildOverlay() {
    const head = this.panel.querySelector?.('.panel-head');
    this.toggle = document.createElement('button');
    this.toggle.type = 'button';
    this.toggle.className = 'mia-holo-mode';
    this.toggle.setAttribute('aria-pressed', 'false');
    this.toggle.setAttribute('title', 'Alternar presentación Breakout 3D y lectura frontal');
    this.toggle.textContent = '◫ Modo lectura';
    this.toggle.hidden = true;
    this.toggle.addEventListener('click', () => this.setReading(!this.reading));
    head?.insertBefore?.(this.toggle, head.querySelector?.('#closeResults'));

    this.frame = document.createElement('div');
    this.frame.className = 'mia-breakout-frame';
    this.frame.setAttribute('aria-hidden', 'true');
    this.root.appendChild(this.frame);

    this.portal = document.createElement('div');
    this.portal.className = 'mia-breakout-portal';
    this.portal.setAttribute('aria-hidden', 'true');
    this.root.appendChild(this.portal);

    this.shadow = document.createElement('div');
    this.shadow.className = 'mia-breakout-shadow';
    this.shadow.setAttribute('aria-hidden', 'true');
    this.root.appendChild(this.shadow);

    this.echoes = [];
    for (let i = 0; i < 2; i++) {
      const echo = document.createElement('div');
      echo.className = `mia-holo-echo mia-holo-echo--${i + 1}`;
      echo.setAttribute('aria-hidden', 'true');
      this.root.appendChild(echo);
      this.echoes.push(echo);
    }
    this._syncToggle();
  }

  _buildEmitter() {
    this.emitter = new THREE.Group();
    this.emitter.name = 'mIA_SpatialResults_Emitter';
    this.emitter.visible = false;

    const teal = new THREE.MeshBasicMaterial({
      color: 0x138b92, transparent: true, opacity: .34, depthWrite: false,
      depthTest: false, toneMapped: false, side: THREE.DoubleSide,
    });
    const gold = new THREE.MeshBasicMaterial({
      color: 0xb69056, transparent: true, opacity: .28, depthWrite: false,
      depthTest: false, toneMapped: false, side: THREE.DoubleSide,
    });
    this._materials = [teal, gold];
    this._arcs = [];
    for (const [radius, material, rotation] of [[.28, teal, .3], [.38, gold, 2.15]]) {
      const arc = new THREE.Mesh(new THREE.TorusGeometry(radius, .0045, 4, 72, Math.PI * 1.52), material);
      arc.rotation.z = rotation;
      this.emitter.add(arc);
      this._arcs.push(arc);
    }

    const frameMaterial = new THREE.LineBasicMaterial({ color: 0x7ae3ea, transparent: true, opacity: .45, depthTest: false, toneMapped: false });
    const framePoints = [
      new THREE.Vector3(-.62, .42, 0), new THREE.Vector3(.62, .42, 0),
      new THREE.Vector3(.62, .42, 0), new THREE.Vector3(.62, -.42, 0),
      new THREE.Vector3(.62, -.42, 0), new THREE.Vector3(-.62, -.42, 0),
      new THREE.Vector3(-.62, -.42, 0), new THREE.Vector3(-.62, .42, 0),
    ];
    const frameGeometry = new THREE.BufferGeometry().setFromPoints(framePoints);
    this._frameOutline = new THREE.LineSegments(frameGeometry, frameMaterial);
    this._frameOutline.position.set(.24, 0, -.13);
    this.emitter.add(this._frameOutline);
    this._materials.push(frameMaterial);

    const points = [];
    for (let i = 0; i < 42; i++) {
      const a = i * 2.399963229728653;
      const r = .20 + (i % 9) * .026;
      points.push(r * Math.cos(a), r * Math.sin(a), ((i % 7) - 3) * .014);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    this._particles = new THREE.Points(geometry, new THREE.PointsMaterial({
      color: 0x14767f, transparent: true, opacity: .45, size: .019,
      sizeAttenuation: true, depthTest: false, depthWrite: false, toneMapped: false,
    }));
    this.emitter.add(this._particles);
    this.scene.scene.add(this.emitter);
  }

  _buildBreakoutGeometry() {
    // A genuine THREE.BoxGeometry frame, placed in camera coordinates. Its
    // extended edges remain visible OUTSIDE the unmodified HTML panel.
    this.breakout = new THREE.Group();
    this.breakout.name = 'mIA_Breakout3D_DataPortal';
    this.breakout.visible = false;
    this._breakoutMaterials = [
      new THREE.MeshStandardMaterial({ color: 0x0b8b9d, metalness: .26, roughness: .38,
        emissive: 0x0a505d, emissiveIntensity: .12, transparent: true, opacity: .46,
        depthWrite: false }),
      new THREE.MeshStandardMaterial({ color: 0xc5ab77, metalness: .26, roughness: .42,
        emissive: 0x684422, emissiveIntensity: .12, transparent: true, opacity: .40,
        depthWrite: false }),
    ];
    this._breakoutParts = [];
    for (let i = 0; i < 4; i++) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, .045), this._breakoutMaterials[i % 2]);
      mesh.castShadow = false;
      mesh.receiveShadow = false;
      this.breakout.add(mesh);
      this._breakoutParts.push(mesh);
    }
    this._barGroup = new THREE.Group();
    this._barGroup.name = 'mIA_Breakout_DataDrivenBars';
    this.breakout.add(this._barGroup);
    this._barMeshes = [];
    for (let i = 0; i < 5; i++) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
        i === 0 ? this._breakoutMaterials[1] : this._breakoutMaterials[0]);
      mesh.visible = false;
      this._barGroup.add(mesh);
      this._barMeshes.push(mesh);
    }
    this.scene.scene.add(this.breakout);
  }

  _configureBreakoutGeometry() {
    const { w, h } = this._portalSize;
    // Thin architectural frame. The V2 extrusion looked like a heavy box.
    const edge = Math.min(.018, Math.max(.009, w * .006));
    const horizontal = [0, 1];
    for (const index of horizontal) {
      const bar = this._breakoutParts[index];
      bar.scale.set(w + edge * 3, edge, 1);
      bar.position.set(0, index === 0 ? h / 2 + edge : -h / 2 - edge, 0);
    }
    for (let i = 2; i < 4; i++) {
      const bar = this._breakoutParts[i];
      bar.scale.set(edge, h + edge * 2, 1);
      bar.position.set(i === 2 ? -w / 2 - edge : w / 2 + edge, 0, 0);
    }
    // Only actual DOM bars are reflected in WebGL. Never invent metrics.
    const bars = Array.from(this.panel.querySelectorAll?.('.stat-bar-track i') || []).slice(0, 5);
    const satelliteW = Math.max(.14, Math.min(.37, w * .27));
    const gap = .083;
    const baseY = Math.min(h * .30, .30);
    this._barGroup.position.set(-w / 2 - satelliteW - .11, -baseY, .13);
    for (let i = 0; i < this._barMeshes.length; i++) {
      const mesh = this._barMeshes[i];
      let width = NaN;
      if (bars[i]) {
        const raw = bars[i].style?.getPropertyValue?.('--bar') ||
          getComputedStyle(bars[i]).getPropertyValue('--bar');
        width = Number.parseFloat(raw);
      }
      if (!Number.isFinite(width)) { mesh.visible = false; continue; }
      const ratio = Math.min(1, Math.max(0, width / 100));
      const actualW = Math.max(.01, satelliteW * ratio);
      mesh.visible = ratio > 0;
      mesh.scale.set(actualW, .055, .09);
      mesh.position.set((actualW - satelliteW) / 2, i * gap, (i % 2) * .015);
    }
  }

  _decorateRealResults() {
    this._undecorate();
    const seen = new Set();
    const mark = (selector, className, max) => {
      const nodes = Array.from(this.panel.querySelectorAll?.(selector) || []);
      let index = 0;
      for (const node of nodes) {
        if (seen.has(node) || index >= max) continue;
        seen.add(node);
        node.classList.add(className);
        node.style?.setProperty?.('--mia-breakout-order', String(index));
        this._decorated.push(node);
        index++;
      }
    };
    mark(CARD_SELECTORS.join(','), 'mia-breakout-card', 9);
    mark('.stat-chart', 'mia-breakout-chart', 3);
    mark('.mia-presentation, .premium-table-shell, .e360x-section', 'mia-breakout-detail', 2);
  }

  _undecorate() {
    for (const node of this._decorated) {
      node.classList.remove('mia-breakout-card', 'mia-breakout-chart', 'mia-breakout-detail');
      node.style?.removeProperty?.('--mia-breakout-order');
    }
    this._decorated = [];
  }

  _breakoutActive() {
    return this.breakoutEnabled && this.hasResult && this._canDisplay() && !this.reading;
  }

  _clearReadingTimer() {
    if (this._readingTimer) clearTimeout(this._readingTimer);
    this._readingTimer = 0;
  }

  _canDisplay() {
    return shouldUseSpatialResults({ enabled: this.enabled, reducedMotion: this.reducedMotion, width: window.innerWidth });
  }

  _syncToggle() {
    this.toggle.hidden = !this.hasResult || !this.enabled || this.reducedMotion || window.innerWidth < 1100;
    this.toggle.setAttribute('aria-pressed', String(this.reading));
    this.toggle.textContent = this.reading ? '✦ Vista Breakout' : '◫ Modo lectura';
    this.toggle.setAttribute('aria-label', this.reading
      ? 'Activar presentación Breakout 3D' : 'Mostrar resultados en modo lectura frontal');
  }

  _syncLayout() {
    const active = this.hasResult && this._canDisplay() && !this.reading;
    const breakout = active && this.breakoutEnabled;
    this.root.classList.toggle('mia-holo-active', active);
    this.root.classList.toggle('mia-holo-reading', this.hasResult && !active);
    this.root.classList.toggle('mia-breakout-active', breakout);
    this.emitter.visible = active;
    this.breakout.visible = breakout;
    this._syncToggle();
    if (!active) { this._resetPointer(); return; }

    const vh = window.innerHeight;
    const vw = window.innerWidth;
    const style = getComputedStyle(this.panel);
    let rect;
    if (breakout) {
      // Content-sized but bounded stage. V2 extended beyond the right/top edge
      // and left a huge empty rectangle on single-record employee views.
      const view = this.panel.querySelector?.('.conversation');
      const measured = Number(view?.scrollHeight) || 0;
      const headHeight = Number(this.panel.querySelector?.('.panel-head')?.offsetHeight) || 42;
      const rows = Number(this.panel.querySelectorAll?.('table tbody tr')?.length) || 0;
      const maxH = Math.max(340, vh - 122);
      const compact = measured > 0 && measured + headHeight + 58 <= maxH - 70;
      const height = Math.min(maxH, Math.max(390, measured ? measured + headHeight + 58 : Number(this.panel.offsetHeight) || 590));
      const width = Math.min(860, Math.max(550, vw - 645));
      const right = 46;
      const top = Math.max(50, Math.round((vh - height) * .46));
      rect = { width, height, left: vw - right - width, top };
      this.root.classList.toggle('mia-breakout-compact', compact && rows <= 8);
      this.root.style.setProperty('--mia-breakout-panel-width', `${width}px`);
      this.root.style.setProperty('--mia-breakout-panel-height', `${height}px`);
      this.root.style.setProperty('--mia-breakout-panel-top', `${top}px`);
      this.root.style.setProperty('--mia-breakout-panel-right', `${right}px`);
    } else {
      this.root.classList.remove('mia-breakout-compact');
      rect = {
        width: this.panel.offsetWidth, height: this.panel.offsetHeight,
        left: vw - (parseFloat(style.right) || 0) - this.panel.offsetWidth,
        top: parseFloat(style.top) || 0,
      };
    }
    this.root.style.setProperty('--mia-holo-left', `${rect.left.toFixed(1)}px`);
    this.root.style.setProperty('--mia-holo-top', `${rect.top.toFixed(1)}px`);
    this.root.style.setProperty('--mia-holo-width', `${rect.width.toFixed(1)}px`);
    this.root.style.setProperty('--mia-holo-height', `${rect.height.toFixed(1)}px`);

    const depth = 2.65;
    const camera = this.scene.camera;
    const worldHalfH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * depth;
    const worldHalfW = worldHalfH * camera.aspect;
    const pxX = Math.max(120, rect.left - 36);
    const pxY = Math.max(80, Math.min(vh * .65, rect.top + rect.height * .35));
    this._emitterLocation.x = (pxX / vw * 2 - 1) * worldHalfW;
    this._emitterLocation.y = (1 - pxY / vh * 2) * worldHalfH;
    this._portalLocation.x = ((rect.left + rect.width / 2) / vw * 2 - 1) * worldHalfW;
    this._portalLocation.y = (1 - (rect.top + rect.height / 2) / vh * 2) * worldHalfH;
    this._portalSize.w = rect.width / vw * 2 * worldHalfW;
    this._portalSize.h = rect.height / vh * 2 * worldHalfH;
    if (breakout) this._configureBreakoutGeometry();
  }

  prepare() {
    this._clearReadingTimer();
    this.hasResult = true;
    this.reading = false;
    this._undecorate();
    this.root.classList.add('mia-holo-preparing');
    this._syncLayout();
  }

  reveal() {
    if (!this.hasResult) return;
    this._decorateRealResults();
    this._syncLayout();
    if (this._revealFrame) cancelAnimationFrame(this._revealFrame);
    this._revealFrame = requestAnimationFrame(() => {
      this._revealFrame = requestAnimationFrame(() => {
        this._revealFrame = 0;
        this.root.classList.remove('mia-holo-preparing');
        if (this.root.classList.contains('mia-holo-active')) {
          this.panel.classList.add('mia-holo-materialize');
        }
        // A long data table moves to a legible, completely frontal plane
        // after the entrance; user may reactivate 3D with the mode button.
        const rows = this.panel.querySelectorAll?.('table tbody tr')?.length || 0;
        if (this._breakoutActive() && rows > 12) {
          this._readingTimer = setTimeout(() => {
            this._readingTimer = 0;
            if (this.hasResult && !this.reading) this.setReading(true);
          }, 2600);
        }
      });
    });
  }

  setReading(reading) {
    this._clearReadingTimer();
    this.reading = Boolean(reading);
    if (this._revealFrame) cancelAnimationFrame(this._revealFrame);
    this._revealFrame = 0;
    this.root.classList.remove('mia-holo-preparing');
    this.panel.classList.remove('mia-holo-materialize');
    this._syncLayout();
  }

  reset() {
    this._clearReadingTimer();
    this._undecorate();
    this.hasResult = false;
    this.reading = false;
    if (this._revealFrame) cancelAnimationFrame(this._revealFrame);
    this._revealFrame = 0;
    this.panel.classList.remove('mia-holo-materialize');
    this.root.classList.remove('mia-holo-active', 'mia-holo-reading', 'mia-holo-preparing', 'mia-breakout-active', 'mia-breakout-compact');
    this.emitter.visible = false;
    this._resetPointer();
    this._syncToggle();
  }

  _pointerMove(event) {
    if (!this.hasResult || this.reading || !this._canDisplay()) return;
    const rect = this.panel.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width - .5) * 2;
    const y = ((event.clientY - rect.top) / rect.height - .5) * 2;
    this._pointer.x = Math.max(-1, Math.min(1, x));
    this._pointer.y = Math.max(-1, Math.min(1, y));
    if (this._pendingPointerFrame) return;
    this._pendingPointerFrame = requestAnimationFrame(() => {
      this._pendingPointerFrame = 0;
      this.root.style.setProperty('--mia-holo-rot-y', `${(-7.8 + this._pointer.x * 2.2).toFixed(2)}deg`);
      this.root.style.setProperty('--mia-holo-rot-x', `${(2.2 - this._pointer.y * 1.3).toFixed(2)}deg`);
      this.root.style.setProperty('--mia-breakout-skew', `${(this._pointer.x * 8).toFixed(2)}px`);
    });
  }

  _resetPointer() {
    if (this._pendingPointerFrame) cancelAnimationFrame(this._pendingPointerFrame);
    this._pendingPointerFrame = 0;
    this.root.style.removeProperty('--mia-holo-rot-y');
    this.root.style.removeProperty('--mia-holo-rot-x');
    this.root.style.removeProperty('--mia-breakout-skew');
  }

  _frame(time) {
    if (!this.emitter.visible) return;
    const camera = this.scene.camera;
    this._offset.set(this._emitterLocation.x, this._emitterLocation.y, -2.65).applyQuaternion(camera.quaternion);
    this.emitter.position.copy(camera.position).add(this._offset);
    this.emitter.quaternion.copy(camera.quaternion);
    this._arcs[0].rotation.z = time * .16 + .3;
    this._arcs[1].rotation.z = -time * .12 + 2.15;
    this._particles.rotation.z = time * .035;
    this._frameOutline.rotation.z = Math.sin(time * .55) * .04;
    this.emitter.scale.setScalar(.97 + .035 * Math.sin(time * 1.2));
    if (this.breakout.visible) {
      this._offset.set(this._portalLocation.x, this._portalLocation.y, -2.65)
        .applyQuaternion(camera.quaternion);
      this.breakout.position.copy(camera.position).add(this._offset);
      this.breakout.quaternion.copy(camera.quaternion);
      // Small parallax uses the existing scene clock. No secondary RAF loop.
      this.breakout.rotation.y = -.045 + Math.sin(time * .55) * .008;
      this._barGroup.rotation.y = -.11;
    }
  }

  destroy() {
    this.reset();
    if (this.scene.onFrame === this._ourFrame) this.scene.onFrame = this._previousFrame;
    window.removeEventListener('resize', this._onResize);
    this.panel.removeEventListener('pointermove', this._onPointerMove);
    this.panel.removeEventListener('pointerleave', this._onPointerLeave);
    this.toggle.remove();
    this.frame.remove();
    this.portal.remove();
    this.shadow.remove();
    this.echoes.forEach((node) => node.remove());
    this.breakout.parent?.remove(this.breakout);
    this.breakout.traverse((obj) => obj.geometry?.dispose?.());
    this._breakoutMaterials.forEach((material) => material.dispose());
    this.emitter.parent?.remove(this.emitter);
    this.emitter.traverse((obj) => obj.geometry?.dispose?.());
    this._materials.forEach((m) => m.dispose?.());
    this._particles.material.dispose();
  }
}
