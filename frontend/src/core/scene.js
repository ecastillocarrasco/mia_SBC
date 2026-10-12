/** Escena Three.js de mIA reutilizable.
 * El mundo 3D la usa tal cual; el holograma la reconfigura (fondo oscuro, material GLSL, cámara frontal).
 * V2: contact shadow disc, two-layer animation (base + upper-body gestures), positional wandering.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { inPlace, maskedClip, LOOPING, STATE_ANIMATION } from "./animations.js";

const MODEL_URL = `${import.meta.env.BASE_URL}models/mIA_SBC_V4_84_ANIMACIONES.glb`;
const MODEL_HEIGHT = 2.2;
// Tiny downward push so the feet visually touch the shadow disc.
const GROUND_BIAS = 0.022;

export class MiaScene {
  constructor(container, { background = 0xffffff, shadows = true, fov = 40 } = {}) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = background === null ? null : new THREE.Color(background);
    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.01, 100);
    this.camera.position.set(0, 1.47, 3.88);
    this.target = new THREE.Vector3(0, 1.18, 0);
    this._framingX = 0;
    this._framingGoal = 0;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: background === null });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.04;
    this.renderer.shadowMap.enabled = shadows;
    container.appendChild(this.renderer.domElement);
    this.clock = new THREE.Clock();
    this.mixer = null;
    this.actions = new Map();
    this._frontRating = new Map();
    this.current = null;
    this.model = null;

    // Positional movement: avatar drifts within scene via this root.
    this._groundRoot = new THREE.Object3D();
    this._moveTargetX = 0;
    this._lerpAlpha = 0.02;
    // Saved after model centering — used for micro-sway offset in _loop().
    this._modelBaseX = 0;
    this._modelBaseZ = 0;
    // V4.4: caminar en círculo en esperas muy largas. Movimiento local,
    // con radio pequeño y vuelta a origen progresiva (no afecta al rig).
    this._waitOrbit = null;
    this.scene.add(this._groundRoot);

    // Upper-body gesture overlay layer.
    this._upperActions = new Map();
    this._upperCurrent = null;
    this._upperDoneListeners = new Map();

    // Camera head-tracking (subtle live follow).
    this._headBone = null;
    this._headWorld = new THREE.Vector3();

    // V4.6: soft head/neck aim correction after AnimationMixer has evaluated
    // the original pose. The asset, rig weights and animation tracks remain
    // unchanged. Only the world 3D (shadows=true) gets this correction.
    this._facePose = {
      enabled: Boolean(shadows), pitchDeg: 6, yawDeg: 4,
      neckShare: 0.34, strength: 0.70, maxYawDeg: 17,
    };
    this._faceBones = null;
    this._faceEuler = new THREE.Euler(0, 0, 0, 'YXZ');
    this._faceDelta = new THREE.Quaternion();
    this._faceDesired = new THREE.Quaternion();

    this._lights(shadows);
    this._resize = () => this.resize();
    window.addEventListener("resize", this._resize);
    this.resize();
    this._loop();
  }

  _lights(shadows) {
    // Pure white background: depth comes from physical light, NOT beige floors.
    // HG retains its own dark background and no floor.
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xe3e0dc, shadows ? 1.55 : 2.0));
    const key = new THREE.DirectionalLight(0xffffff, shadows ? 2.4 : 2.3);
    key.position.set(-3.0, 5.5, 5.5);
    key.castShadow = shadows;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.00012;
    key.shadow.normalBias = 0.018;
    key.shadow.radius = 3.3;
    key.shadow.camera.left = -3;
    key.shadow.camera.right = 3;
    key.shadow.camera.top = 5;
    key.shadow.camera.bottom = -3;
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xe5efff, shadows ? 0.72 : 0.3);
    fill.position.set(3, 2.8, 3.0);
    this.scene.add(fill);
    if (!shadows) return;
    const rim = new THREE.DirectionalLight(0xffecd9, 1.15);
    rim.position.set(1.0, 3.8, -2.8);
    this.scene.add(rim);
    // Invisible ground: only the contact shadow is drawn on the white scene.
    const receiver = new THREE.Mesh(
      new THREE.PlaneGeometry(30, 30),
      new THREE.ShadowMaterial({ color: 0x5c5550, opacity: 0.12 }),
    );
    receiver.rotation.x = -Math.PI / 2;
    receiver.position.y = -0.008;
    receiver.receiveShadow = true;
    this.scene.add(receiver);
    // Procedural soft contact patch, transparent at edges; no visible floor.
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 128;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      const grad = ctx.createRadialGradient(64, 64, 6, 64, 64, 63);
      grad.addColorStop(0, 'rgba(38,34,30,.24)');
      grad.addColorStop(.37, 'rgba(60,56,50,.10)');
      grad.addColorStop(1, 'rgba(65,60,52,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, 128, 128);
      const tex = new THREE.CanvasTexture(canvas);
      const contact = new THREE.Mesh(
        new THREE.PlaneGeometry(1.5, .8),
        new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false }),
      );
      contact.rotation.x = -Math.PI / 2;
      contact.position.y = -0.004;
      this._groundRoot.add(contact);
    }
  }

  async load(onProgress) {
    // Bytes del GLB validado mIA V4 (84 clips). Solo se usan como respaldo
    // si el servidor no envia Content-Length. Nunca se inventan porcentajes
    // basados en tiempo: el avance siempre utiliza event.loaded.
    const EXPECTED_BYTES = 39562116;
    const gltf = await new GLTFLoader().loadAsync(MODEL_URL, (event) => {
      const totalBytes = Number(event.total) > 0 ? Number(event.total) : EXPECTED_BYTES;
      const loadedBytes = Math.max(0, Number(event.loaded) || 0);
      const fraction = Math.max(0, Math.min(1, loadedBytes / totalBytes));
      onProgress?.(fraction * 0.94, {
        phase: 'downloading', loadedBytes, totalBytes,
        estimatedTotal: !(Number(event.total) > 0),
      });
    });
    onProgress?.(0.96, { phase: 'processing' });
    const model = gltf.scene;
    model.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.frustumCulled = false; // animated skinned bounds are not always conservative
      }
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

    const neck = model.getObjectByName('smartrig:Neck');
    const head = model.getObjectByName('smartrig:Head');
    if (neck?.isBone && head?.isBone) {
      this._faceBones = [
        { bone: neck, rest: neck.quaternion.clone(), share: this._facePose.neckShare },
        { bone: head, rest: head.quaternion.clone(), share: 1 - this._facePose.neckShare },
      ];
    } else {
      console.warn('[mIA V4.6] Ajuste de mirada desactivado: Head/Neck no encontrados');
    }

    for (const clip of gltf.animations) {
      const base = inPlace(clip);
      this.actions.set(clip.name, this.mixer.clipAction(base));
      // Upper-body gesture actions are generated lazily, without duplicating
      // all 84 clips or modifying the original glTF animation.
    }

    // V4.2: el último tramo de mIA_IDLE tiene un gesto poco natural. Crear
    // una variante solamente en memoria que evita ese final. El original
    // permanece intacto en el GLB y en la biblioteca de 84 acciones.
    const sourceIdle = this.actions.get("mIA_IDLE")?.getClip()
      || this.actions.get("mIA_IDLE_BREATHING")?.getClip();
    if (sourceIdle) {
      const fps = 30;
      const safeUntil = Math.max(2.0, sourceIdle.duration * 0.70);
      const endFrame = Math.floor(Math.min(safeUntil, sourceIdle.duration - 0.35) * fps);
      if (endFrame > 45) {
        const idleSafe = THREE.AnimationUtils.subclip(
          sourceIdle, "mIA_IDLE_SAFE", 0, endFrame, fps,
        );
        if (idleSafe.tracks.length) {
          this.actions.set(idleSafe.name, this.mixer.clipAction(idleSafe));
        }
      }
    }

    // The 84-clip greeting includes a final movement that looks forced.
    // Keep the earlier, validated gesture; drop its last ~2.2 s and blend
    // back to idle BEFORE the safe clip reaches its last keyframe.
    const sourceGreeting = this.actions.get('mIA_SEQ_BIENVENIDA')?.getClip();
    if (sourceGreeting && sourceGreeting.duration > 4.0) {
      const fps = 30;
      const cutTime = Math.max(3.0, Math.min(sourceGreeting.duration * 0.77,
        sourceGreeting.duration - 2.1));
      const safe = THREE.AnimationUtils.subclip(
        sourceGreeting, 'mIA_SEQ_BIENVENIDA_SAFE', 0,
        Math.floor(cutTime * fps), fps,
      );
      if (safe.tracks.length) {
        this.actions.set(safe.name, this.mixer.clipAction(safe));
      }
    }

    this.mixer.addEventListener("finished", (e) => {
      if (this._upperDoneListeners.has(e.action)) {
        this._upperDoneListeners.get(e.action)();
        this._upperDoneListeners.delete(e.action);
      } else if (this.current === e.action) {
        // A previous action may finish while crossfading to a new one.
        this.play("mIA_IDLE_SAFE", { fade: 0.55, loop: true });
      }
    });

    this.play("mIA_IDLE_SAFE", 0);
    onProgress?.(0.99, { phase: 'animations' });
    return [...this.actions.keys()];
  }

  // ── Base animation layer ─────────────────────────────────────────────────

  play(name, settings = {}) {
    const options = typeof settings === "number" ? { fade: settings } : (settings || {});
    const nextName = this.actions.has(name) ? name : (this.actions.has("mIA_IDLE_SAFE") ? "mIA_IDLE_SAFE" : "mIA_IDLE");
    const next = this.actions.get(nextName);
    if (!next) return false;
    const loop = typeof options.loop === "boolean" ? options.loop : LOOPING.has(nextName);
    if (next === this.current && next.isRunning() && !options.restart) return true;
    next.reset();
    next.enabled = true;
    next.setEffectiveWeight(1);
    next.setEffectiveTimeScale(options.timeScale ?? 1);
    next.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1);
    next.clampWhenFinished = options.clamp ?? false;
    next.play();
    const fade = Number.isFinite(Number(options.fade)) ? Math.max(0, options.fade) : 0.38;
    if (this.current && this.current !== next) {
      this.current.crossFadeTo(next, fade, true);
    }
    this.current = next;
    return true;
  }

  /**
   * Check whether a non-locomotion clip rotates the hip noticeably away
   * from its own start pose. Used ONLY when choosing automatic idle/talk
   * gestures; explicit locomotion and presentation clips are never rewritten.
   */
  isFrontFacingClip(name) {
    if (name === "mIA_IDLE_SAFE") return true;
    if (this._frontRating.has(name)) return this._frontRating.get(name);
    const clip = this.actions.get(name)?.getClip();
    const track = clip?.tracks?.find((t) =>
      /(?:hips|root)\.quaternion$/i.test(t.name));
    if (!track || track.values.length < 8) {
      this._frontRating.set(name, true);
      return true;
    }
    const ref = new THREE.Quaternion(...Array.from(track.values.slice(0, 4)));
    const inv = ref.clone().invert();
    const q = new THREE.Quaternion();
    const delta = new THREE.Quaternion();
    const angle = new THREE.Euler(0, 0, 0, "YXZ");
    let maxYaw = 0;
    const samples = Math.min(track.times.length, 150);
    const stride = Math.max(1, Math.floor(track.times.length / samples));
    for (let i = 0; i < track.times.length; i += stride) {
      q.fromArray(track.values, i * 4);
      delta.copy(inv).multiply(q);
      angle.setFromQuaternion(delta, "YXZ");
      maxYaw = Math.max(maxYaw, Math.abs(angle.y));
    }
    const acceptable = maxYaw < THREE.MathUtils.degToRad(36);
    this._frontRating.set(name, acceptable);
    return acceptable;
  }

  /** Non-destructive face-calibration knobs, available for 3D only. */
  configureFacePose(options = {}) {
    for (const key of ['pitchDeg', 'yawDeg', 'strength']) {
      if (Number.isFinite(options[key])) this._facePose[key] = options[key];
    }
    if (typeof options.enabled === 'boolean') this._facePose.enabled = options.enabled;
    this._facePose.pitchDeg = THREE.MathUtils.clamp(this._facePose.pitchDeg, -10, 14);
    this._facePose.yawDeg = THREE.MathUtils.clamp(this._facePose.yawDeg, -12, 12);
    this._facePose.strength = THREE.MathUtils.clamp(this._facePose.strength, 0, 1);
  }

  _adjustFacePose() {
    if (!this._facePose.enabled || !this._faceBones || !this.mixer) return;
    const clip = this.current?.getClip()?.name || '';
    // Walking/turning/dancing must preserve their full authored orientation.
    if (/WALK|RUN|TURN|DANCE|CATWALK|STRUT/i.test(clip)) return;
    const opt = this._facePose;
    const radians = THREE.MathUtils.degToRad;
    const cameraYaw = THREE.MathUtils.clamp(
      Math.atan2(this.camera.position.x - this._groundRoot.position.x,
        this.camera.position.z - this._groundRoot.position.z) * 0.35,
      radians(-8), radians(8),
    );
    for (const { bone, rest, share } of this._faceBones) {
      // Evaluate the LOCAL deviation from this bone's imported rest pose.
      this._faceDelta.copy(rest).invert().multiply(bone.quaternion);
      this._faceEuler.setFromQuaternion(this._faceDelta, 'YXZ');
      const e = this._faceEuler;
      const yawLimit = radians(opt.maxYawDeg);
      const intendedYaw = THREE.MathUtils.clamp(e.y, -yawLimit, yawLimit);
      const intendedPitch = THREE.MathUtils.clamp(e.x, radians(-15), radians(18));
      e.y = THREE.MathUtils.clamp(
        intendedYaw + (radians(opt.yawDeg) + cameraYaw) * share,
        -yawLimit, yawLimit,
      );
      // In the glTF's forward +Z convention, positive local X lowers gaze.
      e.x = THREE.MathUtils.clamp(
        intendedPitch + radians(opt.pitchDeg) * share,
        radians(-15), radians(19),
      );
      this._faceDesired.copy(rest).multiply(this._faceDelta.setFromEuler(e));
      bone.quaternion.slerp(this._faceDesired, opt.strength);
    }
    // Child bones see the modified parent transform on matrixWorld update.
  }

  clipDuration(name) {
    return this.actions.get(name)?.getClip()?.duration ?? 0;
  }

  playState(state) {
    const requested = state === "reposo" ? "mIA_IDLE_SAFE" : (STATE_ANIMATION[state] ?? "mIA_IDLE_SAFE");
    this.play(this.actions.has(requested) ? requested : "mIA_IDLE_SAFE");
  }

  // ── Upper-body gesture overlay ───────────────────────────────────────────

  /** Play an upper-body gesture on top of the current base animation. Auto-clears when done. */
  playGesture(name, { fadeIn = 0.15, fadeOut = 0.2, weight = 0.72, timeScale = 1.0 } = {}) {
    let action = this._upperActions.get(name);
    if (!action && !name.startsWith("mIA_SEQ_") && this.actions.has(name)) {
      const upper = maskedClip(this.actions.get(name).getClip(), "upper");
      if (upper.tracks.length) {
        action = this.mixer.clipAction(upper);
        this._upperActions.set(name, action);
      }
    }
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
  wanderTo(_x, _duration = 2000) {
    // Compatibility: world V4 no longer slides the model independently
    // from skeletal root motion; hologram rotation remains available.
  }

  /** Un paseo breve alrededor del punto habitual, reservado al mundo 3D. */
  startWaitOrbit(seconds = 10) {
    if (!this.model || !this.renderer.shadowMap.enabled) return;
    // Iniciarlo solo cuando volvemos prácticamente a la posición de reposo.
    // Nunca modificar las acciones del GLB ni aplicar root motion doble.
    this._waitOrbit = {
      started: this.clock.elapsedTime,
      duration: Math.max(3, Math.min(13, Number(seconds) || 10)),
    };
  }

  stopWaitOrbit() {
    this._waitOrbit = null;
    // El bucle de render devuelve suavemente las coordenadas a cero.
  }

  _updateWaitOrbit(delta) {
    if (this._waitOrbit) {
      const t = Math.min(1, Math.max(0,
        (this.clock.elapsedTime - this._waitOrbit.started) / this._waitOrbit.duration));
      const angle = t * Math.PI * 2;
      // Suave entrada/salida; paseo reducido para no perder contacto visual.
      const envelope = Math.min(1, t * 7, (1 - t) * 7);
      const radius = 0.23 * Math.max(0, envelope);
      const x = radius * Math.sin(angle);
      const z = radius * (1 - Math.cos(angle));
      // Mantener rostro mayormente frontal (máximo aprox. 14 grados).
      const yaw = Math.sin(angle) * 0.24 * Math.max(0, envelope);
      const factor = 1 - Math.exp(-Math.min(0.1, Math.max(0, delta)) * 5.5);
      this._groundRoot.position.x += (x - this._groundRoot.position.x) * factor;
      this._groundRoot.position.z += (z - this._groundRoot.position.z) * factor;
      this._groundRoot.rotation.y += (yaw - this._groundRoot.rotation.y) * factor;
      if (t >= 1) this.stopWaitOrbit();
    } else {
      // Regresar sin saltos al lugar exacto donde comienza cada respuesta.
      const factor = 1 - Math.exp(-Math.min(0.1, Math.max(0, delta)) * 4);
      this._groundRoot.position.x *= 1 - factor;
      this._groundRoot.position.z *= 1 - factor;
      this._groundRoot.rotation.y *= 1 - factor;
      if (Math.abs(this._groundRoot.position.x) < 0.0001) this._groundRoot.position.x = 0;
      if (Math.abs(this._groundRoot.position.z) < 0.0001) this._groundRoot.position.z = 0;
      if (Math.abs(this._groundRoot.rotation.y) < 0.0001) this._groundRoot.rotation.y = 0;
    }
  }

  setPresentationLayout(active) {
    // Look slightly to the right when results are open: avatar appears left.
    this._presentationActive = Boolean(active);
    if (this.renderer.shadowMap.enabled) this._framingGoal = this._presentationActive && window.innerWidth > 950 ? 1.30 : 0;
  }

  // ── Three.js utilities ───────────────────────────────────────────────────

  /** Applies a material factory to all meshes (used by the hologram world). */
  applyMaterial(factory) {
    this.model?.traverse((o) => {
      if (o.isMesh) o.material = factory(o.material);
    });
  }

  resize() {
    if (this.renderer.shadowMap.enabled) {
      this._framingGoal = this._presentationActive && window.innerWidth > 950 ? 1.30 : 0;
    }
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
    this._adjustFacePose();
    this._updateWaitOrbit(delta);

    // Do not add procedural body translation/rotation here: skeleton IDLE
    // already supplies natural breathing, and procedural offsets caused
    // visible sliding / sudden snaps during crossfades.
    this._framingX += (this._framingGoal - this._framingX) * 0.055;
    this.camera.position.x = this._framingX;
    this.target.x = this._framingX;

    this.onFrame?.(this.clock.elapsedTime);
    this.camera.lookAt(this.target);
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    this.stopWaitOrbit();
    window.removeEventListener("resize", this._resize);
    this.renderer.dispose();
  }
}
