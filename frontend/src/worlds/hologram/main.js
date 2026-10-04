import * as THREE from "three";
import { MiaClient } from "../../core/client.js";
import { bindMicButton } from "../../core/dictation.js";
import { avatarLabel } from "../../core/avatar.js";
import { renderPresentation, renderSources } from "../../core/present.js";
import { MiaScene } from "../../core/scene.js";

// Material de proyección: brillo en los bordes (fresnel) y bandas que suben, aditivo.
function hologramMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(0x5ff2ff) } },
    vertexShader: `
      #include <skinning_pars_vertex>
      varying vec3 vNormal; varying vec3 vView; varying float vY;
      void main() {
        #include <skinbase_vertex>
        #include <begin_vertex>
        #include <beginnormal_vertex>
        #include <skinnormal_vertex>
        #include <skinning_vertex>
        vec4 world = modelMatrix * vec4(transformed, 1.0);
        vY = world.y;
        vNormal = normalize(normalMatrix * objectNormal);
        vec4 mv = viewMatrix * world;
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform float uTime; uniform vec3 uColor;
      varying vec3 vNormal; varying vec3 vView; varying float vY;
      void main() {
        float fresnel = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.2);
        float bands = 0.55 + 0.45 * step(0.5, fract(vY * 18.0 - uTime * 1.6));
        float alpha = clamp(fresnel * 1.4 + 0.12, 0.0, 1.0) * bands;
        gl_FragColor = vec4(uColor * (0.6 + fresnel), alpha);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

const caption = document.getElementById("caption");
const resultEl = document.getElementById("result");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");

const scene = new MiaScene(document.getElementById("canvas-root"), { background: 0x000000, shadows: false, fov: 34 });
scene.camera.position.set(0, 1.15, 5.2);
const client = new MiaClient();
const materials = [];
let busy = false;

scene.onFrame = (t) => {
  for (const m of materials) m.uniforms.uTime.value = t;
  if (scene.model) scene.model.rotation.y = Math.sin(t * 0.25) * 0.12; // leve giro de "proyección"
};

client.addEventListener("avatar", (e) => {
  scene.playState(e.detail.state);
  if (!busy) caption.textContent = avatarLabel(e.detail.state);
});
client.addEventListener("progress", (e) => {
  caption.textContent = e.detail.message || "Consultando…";
});

async function submit(text) {
  if (busy || !text.trim()) return;
  busy = true;
  sendButton.disabled = true;
  resultEl.innerHTML = "";
  caption.textContent = "Pensando…";
  scene.playState("pensando");
  try {
    const result = await client.send(text);
    caption.textContent = result.answer;
    resultEl.innerHTML = (result.presentations || []).map(renderPresentation).join("") + renderSources(result.web_sources);
    await client.speak(result.speech, { onStart: () => scene.playState("hablando") });
    scene.playState(result.avatar_state);
  } catch (error) {
    console.error(error);
    caption.textContent = "No he podido completar la consulta.";
    scene.playState("confundida");
  } finally {
    busy = false;
    sendButton.disabled = false;
    input.focus();
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  submit(text);
});

scene
  .load((p) => {
    caption.textContent = `Iniciando proyección… ${Math.round(p * 100)} %`;
  })
  .then(() => {
    // Bajamos la proyección para que el avatar quede completo dentro del viewport
    // y deje espacio suficiente para el HUD inferior.
    if (scene.model) {
      scene.model.position.y -= 0.8;
    }

    // Si el shader no compila en esta GPU/navegador, mIA no debe quedar invisible:
    // se cambia a un material holográfico simple (sin bandas animadas).
    scene.renderer.debug.onShaderError = () => {
      console.warn("[mIA] shader del holograma no disponible: uso el material de respaldo");
      materials.length = 0;
      scene.applyMaterial(
        () =>
          new THREE.MeshBasicMaterial({
            color: 0x5ff2ff,
            transparent: true,
            opacity: 0.55,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
      );
    };
    scene.applyMaterial(() => {
      const material = hologramMaterial();
      materials.push(material);
      return material;
    });
    scene.playState("saludando");
    caption.textContent = "Hola, soy mIA. ¿En qué puedo ayudarte?";
  })
  .catch((error) => {
    console.error(error);
    caption.textContent = "No se ha podido cargar la proyección.";
  });

bindMicButton(document.getElementById("mic"), {
  onInterim: (text) => {
    input.value = text;
  },
  onFinal: (text) => {
    input.value = "";
    submit(text);
  },
});
