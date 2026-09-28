/** Escena Three.js de mIA reutilizable: el mundo 3D la usa tal cual y el holograma la
 * reconfigura (fondo oscuro, material de proyección, cámara frontal). */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { inPlace, LOOPING, STATE_ANIMATION } from "./animations.js";

const MODEL_URL = "/models/mIA_WEB.glb";
const MODEL_HEIGHT = 2.2;

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
      const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.12 }));
      floor.rotation.x = -Math.PI / 2;
      floor.receiveShadow = true;
      this.scene.add(floor);
    }
  }

  async load(onProgress) {
    const gltf = await new GLTFLoader().loadAsync(MODEL_URL, (event) => {
      if (event.total) onProgress?.(event.loaded / event.total);
    });
    const model = gltf.scene;
    model.traverse((o) => {
      if (o.isMesh) o.castShadow = true;
    });
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    model.scale.setScalar(MODEL_HEIGHT / size.y);
    model.updateMatrixWorld(true);
    const fitted = new THREE.Box3().setFromObject(model);
    const center = fitted.getCenter(new THREE.Vector3());
    model.position.x -= center.x;
    model.position.z -= center.z;
    model.position.y -= fitted.min.y;
    this.scene.add(model);
    this.model = model;
    this.mixer = new THREE.AnimationMixer(model);
    for (const clip of gltf.animations) this.actions.set(clip.name, this.mixer.clipAction(inPlace(clip)));
    this.mixer.addEventListener("finished", () => this.play("mIA_IDLE"));
    this.play("mIA_IDLE", 0);
    return [...this.actions.keys()];
  }

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

  /** Aplica un material a todas las mallas (lo usa el holograma). */
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
