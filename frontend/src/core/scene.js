/** Escena Three.js de mIA reutilizable.
 * El mundo 3D la usa tal cual; el holograma la reconfigura (fondo oscuro, material GLSL, cámara frontal).
 * V2: contact shadow disc, two-layer animation (base + upper-body gestures), positional wandering.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { inPlace, maskedClip, LOOPING, STATE_ANIMATION } from "./animations.js";

const MODEL_URL = "/models/mIA_WEB.glb";
const MODEL_HEIGHT = 2.2;
// Tiny downward push so the feet visually touch the shadow disc.
const GROUND_BIAS = 0.022;

export class MiaScene {
  constructor(container, { background = 0xf4efe6, shadows = true, fov = 40 } = {}) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = background === null ? null : new THREE.Color(background);
    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.01, 100);
    this.camera.position.set(0, 1.2, 5.6);
    this.target = new THREE.Vector3(0, 1.05, 0);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: background === null });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.shadowMap.enabled = shadows;
    container.appendChild(this.renderer.domElement);
    this.clock = new THREE.Clock();
    this.mixer = null;
    this.actions = new Map();
    this.current = null;
    this.model = null;

    // Positional movement: avatar drifts within scene via this root.
    this._groundRoot = new THREE.Object3D();
    this._moveTargetX = 0;
    this._lerpAlpha = 0.02;
    this.scene.add(this._groundRoot);

    // Upper-body gesture overlay layer.
    this._upperActions = new Map();
    this._upperCurrent = null;
    this._upperDoneListeners = new Map();

    // Camera head-tracking (subtle live follow).
    this._headBone = null;
    this._headWorld = new THREE.Vector3();

    this._lights(shadows);
    this._resize = () => this.resize();
    window.addEventListener("resize", this._resize);
    this.resize();
    this._loop();
  }

  _lights(shadows) {
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xe8e2d8, 2.0));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(1.4, 6, 2);
    key.castShadow = shadows;
    key.shadow.mapSize.set(1024, 1024);
    this.scene.add(key);
    if (shadows) {
      const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(40, 40),
        new THREE.ShadowMaterial({ opacity: 0.12 }),
      );
      floor.rotation.x = -Math.PI / 2;
      floor.receiveShadow = true;
      this.scene.add(floor);
    }
    // Elliptical contact shadow disc: grounds the avatar visually even without a floor texture.
    const disc = new THREE.Mesh(
      new THREE.CircleGeometry(0.36, 64),
      new THREE.MeshBasicMaterial({
        color: 0x0a0500,
        transparent: true,
        opacity: shadows ? 0.15 : 0.10,
        depthWrite: false,
      }),
    );
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.001;
    disc.scale.set(1, 0.38, 1); // narrower on Z = elliptical footprint
    this._groundRoot.add(disc); // moves with avatar so it always stays underfoot
  }

  async load(onProgress) {
    const gltf = await new GLTFLoader().loadAsync(MODEL_URL, (event) => {
      if (event.total) onProgress?.(event.loaded / event.total);
    });
    const model = gltf.scene;
    model.traverse((o) => {
      if (o.isMesh) o.castShadow = true;
      // Find the head bone for camera soft-tracking.
      if (!this._headBone && o.isBone && /\bhead\b/i.test(o.name)) this._headBone = o;
    });

    // Scale to desired height, then push feet exactly to y=0.
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    model.scale.setScalar(MODEL_HEIGHT / size.y);
    model.updateMatrixWorld(true);
    const fitted = new THREE.Box3().setFromObject(model);
    const center = fitted.getCenter(new THREE.Vector3());
    model.position.x -= center.x;
    model.position.z -= center.z;
    model.position.y -= fitted.min.y + GROUND_BIAS;

    this._groundRoot.add(model);
    this.model = model;
    this.mixer = new THREE.AnimationMixer(model);

    for (const clip of gltf.animations) {
      const base = inPlace(clip);
      this.actions.set(clip.name, this.mixer.clipAction(base));
      // Pre-build upper-body-only masked version for the gesture layer.
      const upper = maskedClip(base, "upper");
      if (upper.tracks.length > 0) this._upperActions.set(clip.name, this.mixer.clipAction(upper));
    }

    this.mixer.addEventListener("finished", (e) => {
      if (this._upperDoneListeners.has(e.action)) {
        this._upperDoneListeners.get(e.action)();
        this._upperDoneListeners.delete(e.action);
      } else {
        // Base-layer one-shot finished → return to idle.
        this.play("mIA_IDLE");
      }
    });

    this.play("mIA_IDLE", 0);
    return [...this.actions.keys()];
  }

  // ── Base animation layer ─────────────────────────────────────────────────

  play(name, fade = 0.35) {
    const next = this.actions.get(name) ?? this.actions.get("mIA_IDLE");
    if (!next || next === this.current) return;
    const loop = LOOPING.has(name);
    next.reset();
    next.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1);
    next.clampWhenFinished = !loop;
    next.play();
    if (this.current) this.current.crossFadeTo(next, fade, true);
    this.current = next;
  }

  playState(state) {
    this.play(STATE_ANIMATION[state] ?? "mIA_IDLE");
  }

  // ── Upper-body gesture overlay ───────────────────────────────────────────

  /** Play an upper-body gesture on top of the current base animation. Auto-clears when done. */
  playGesture(name, { fadeIn = 0.15, fadeOut = 0.2, weight = 0.72, timeScale = 1.0 } = {}) {
    const action = this._upperActions.get(name);
    if (!action) return;

    // Fade out whatever was playing before.
    if (this._upperCurrent && this._upperCurrent !== action) {
      this._upperCurrent.fadeOut(fadeOut);
      this._upperDoneListeners.delete(this._upperCurrent);
    }

    action.reset();
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.weight = weight;
    action.timeScale = timeScale;
    action.fadeIn(fadeIn);
    action.play();
    this._upperCurrent = action;

    this._upperDoneListeners.set(action, () => {
      action.fadeOut(fadeOut);
      if (this._upperCurrent === action) this._upperCurrent = null;
    });
  }

  /** Fade out the active upper-body gesture immediately. */
  stopGesture(fade = 0.2) {
    if (this._upperCurrent) {
      this._upperCurrent.fadeOut(fade);
      this._upperDoneListeners.delete(this._upperCurrent);
      this._upperCurrent = null;
    }
  }

  // ── Positional movement ──────────────────────────────────────────────────

  /**
   * Smoothly drift the avatar to horizontal position `x` (scene units, ≈ ±0.5 max).
   * `duration` ms controls how fast it arrives (exponential approach).
   */
  wanderTo(x, duration = 2000) {
    this._moveTargetX = x;
    // alpha such that we cover ~95% of the remaining distance in `duration` ms at 60 fps
    const frames = Math.max(30, (duration / 1000) * 60);
    this._lerpAlpha = 1 - Math.pow(0.05, 1 / frames);
  }

  // ── Three.js utilities ───────────────────────────────────────────────────

  /** Applies a material factory to all meshes (used by the hologram world). */
  applyMaterial(factory) {
    this.model?.traverse((o) => {
      if (o.isMesh) o.material = factory(o.material);
    });
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  _loop() {
    this._raf = requestAnimationFrame(() => this._loop());
    const delta = this.clock.getDelta();
    this.mixer?.update(delta);

    // Smooth positional wander.
    const dx = this._moveTargetX - this._groundRoot.position.x;
    if (Math.abs(dx) > 0.0005) {
      this._groundRoot.position.x += dx * this._lerpAlpha;
    }

    // Subtle camera soft-track toward avatar's head — makes the shot feel alive.
    if (this._headBone) {
      this._headBone.getWorldPosition(this._headWorld);
      this.target.x += (this._headWorld.x - this.target.x) * 0.025;
      this.target.y += (this._headWorld.y - this.target.y) * 0.012;
    }

    this.onFrame?.(this.clock.elapsedTime);
    this.camera.lookAt(this.target);
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    window.removeEventListener("resize", this._resize);
    this.renderer.dispose();
  }
}
