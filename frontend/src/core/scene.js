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
    // Saved after model centering — used for micro-sway offset in _loop().
    this._modelBaseX = 0;
    this._modelBaseZ = 0;
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

    // Visible floor plane: warm off-white, just darker than the background, to
    // give the avatar a clear surface to stand on and a visible horizon line.
    const floorVis = new THREE.Mesh(
      new THREE.PlaneGeometry(20, 20),
      new THREE.MeshLambertMaterial({ color: 0xe8e2d6 }),
    );
    floorVis.rotation.x = -Math.PI / 2;
    floorVis.position.y = -0.002;
    floorVis.receiveShadow = true;
    this.scene.add(floorVis);

    if (shadows) {
      const shadowFloor = new THREE.Mesh(
        new THREE.PlaneGeometry(40, 40),
        new THREE.ShadowMaterial({ opacity: 0.22 }),
      );
      shadowFloor.rotation.x = -Math.PI / 2;
      shadowFloor.receiveShadow = true;
      this.scene.add(shadowFloor);
    }

    // Outer soft ambient halo — very wide, very transparent, softens the base.
    const outerDisc = new THREE.Mesh(
      new THREE.CircleGeometry(1.0, 64),
      new THREE.MeshBasicMaterial({
        color: 0x060300,
        transparent: true,
        opacity: 0.08,
        depthWrite: false,
      }),
    );
    outerDisc.rotation.x = -Math.PI / 2;
    outerDisc.position.y = 0.001;
    outerDisc.scale.set(1, 0.45, 1);
    this._groundRoot.add(outerDisc);

    // Inner contact shadow disc: clearly visible dark ellipse directly underfoot.
    const disc = new THREE.Mesh(
      new THREE.CircleGeometry(0.50, 64),
      new THREE.MeshBasicMaterial({
        color: 0x050200,
        transparent: true,
        opacity: shadows ? 0.28 : 0.20,
        depthWrite: false,
      }),
    );
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.002;
    disc.scale.set(1, 0.40, 1);
    this._groundRoot.add(disc);
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
    // Save centered positions as sway base — the micro-sway in _loop() offsets from here.
    this._modelBaseX = model.position.x;
    this._modelBaseZ = model.position.z;

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

    // Continuous micro-sway: sinusoidal offset keeps the avatar always slightly moving.
    // Gives the impression of natural breathing/weight-shifting even during pauses.
    if (this.model) {
      const t = this.clock.elapsedTime;
      this.model.position.x = this._modelBaseX + Math.sin(t * 0.55) * 0.014;
      this.model.position.z = this._modelBaseZ + Math.sin(t * 0.72) * 0.008;
      // Soft-rotate toward camera center when avatar is off to the side — personality.
      const rotTarget = -this._groundRoot.position.x * 0.22;
      this.model.rotation.y += (rotTarget - this.model.rotation.y) * 0.02;
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
