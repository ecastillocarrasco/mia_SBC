/**
 * mIA holograma V5.1: materiales SOLO para mundo holograma.
 *
 * Three.js, GLB, armature y las 84 acciones son referencias de solo lectura.
 *
 * ?avatar=hybrid    (por defecto en pantalla) rostro + cuerpo cian
 * ?avatar=projection (por defecto en ?fan=1) cara opaca + cuerpo translúcido
 * ?avatar=classic   shader antiguo V4: radiografiado integral, cara difusa
 * ?avatar=natural   material original V5: similar al mundo 3D
 * ?fan=1            negro puro, sin fondo de escenario y mayor luminancia
 * ?glow=1.0         intensidad extra de contorno, entre 0.4 y 1.8
 * ?face=0.72        detalle de textura conservado en el rostro, entre 0.35 y 1
 *
 * El mesh real de mIA tiene UN material para todo el cuerpo: no podemos
 * identificar los polígonos de piel por material. La región facial de la
 * variante híbrida es una máscara ESPACIAL gradual en coordenadas del mundo.
 */

const VALID_MODES = new Set(['hybrid', 'classic', 'natural', 'projection']);

export function resolveHologramMode(search = '') {
  const params = new URLSearchParams(search);
  const fan = params.get('fan') === '1';
  // La salida física usa su propio acabado salvo que se pida comparar otro.
  const defaultMode = fan ? 'projection' : 'hybrid';
  const requested = (params.get('avatar') || defaultMode).toLowerCase();
  return {
    mode: VALID_MODES.has(requested) ? requested : defaultMode,
    fan,
    glow: clampNumber(params.get('glow'), 0.4, 1.8, fan ? 1.22 : 1.0),
    face: clampNumber(params.get('face'), 0.35, 1.0, fan ? 0.96 : 0.72),
  };
}

function clampNumber(source, min, max, fallback) {
  if (source == null || String(source).trim() === '') return fallback;
  const n = Number(source);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
}

// Reproduce el efecto GLSL original para realizar comparaciones fieles.
function classicHologramMaterial(THREE, uniforms) {
  const mat = new THREE.ShaderMaterial({
    uniforms,
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
        float edge = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
        float scan = 0.75 + 0.25 * step(0.5, fract(vY * 18.0 - uTime * 1.35));
        float alpha = clamp(0.18 + edge * 0.83, 0.0, 0.92) * scan;
        gl_FragColor = vec4(uColor * (0.72 + edge * 0.95), alpha);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  return mat;
}

/**
 * Conserva el shader estándar de Three.js (incluye skinning, mapas y luces)
 * y modifica exclusivamente el color final y la transparencia con un fresnel.
 * No contiene glsl chunks propietarios ni cambia la geometría.
 */
export function installHybridShader(material, THREE, options, shaders) {
  if (!material || material.isShaderMaterial || typeof material.clone !== 'function') {
    return material;
  }
  const meshMat = material.clone();
  meshMat.transparent = true;
  meshMat.depthWrite = true;  // priorizar rostro frontal frente a superficies traseras
  meshMat.depthTest = true;
  meshMat.side = THREE.FrontSide;
  meshMat.blending = THREE.NormalBlending;
  meshMat.opacity = 1;
  meshMat.toneMapped = true;
  if ('metalness' in meshMat) meshMat.metalness = 0.02;
  if ('roughness' in meshMat) meshMat.roughness = 0.78;
  if (meshMat.emissive) {
    meshMat.emissive.set(0x07313a);
    meshMat.emissiveIntensity = 0.22;
  }
  if (meshMat.map) meshMat.map.colorSpace = THREE.SRGBColorSpace;
  if (typeof meshMat.customProgramCacheKey === 'function') {
    const originalKey = meshMat.customProgramCacheKey.bind(meshMat);
    meshMat.customProgramCacheKey = () => originalKey() + '|mia-hg51-hybrid';
  }

  meshMat.onBeforeCompile = (shader) => {
    const vCommon = '#include <common>';
    const vProject = '#include <project_vertex>';
    const fCommon = '#include <common>';
    const fOpaque = '#include <opaque_fragment>';
    if (!shader.vertexShader.includes(vProject) || !shader.fragmentShader.includes(fOpaque)) {
      console.warn('[mIA HG V5.1] Shader inesperado: se conserva material original');
      return;
    }
    shader.uniforms.uHgTime = { value: 0 };
    shader.uniforms.uHgGlow = { value: options.glow * (options.fan ? 1.14 : 1) };
    shader.uniforms.uHgFacePreserve = { value: options.face };
    shader.uniforms.uHgBodyOpacity = { value: options.fan ? 0.74 : 0.50 };
    shader.uniforms.uHgOpaqueFace = { value: options.mode === 'projection' ? 1.0 : 0.99 };

    shader.vertexShader = shader.vertexShader.replace(vCommon, `${vCommon}
      varying vec3 vHgWorld;
      varying vec3 vHgViewNormal;
      varying vec3 vHgViewDirection;
    `);
    shader.vertexShader = shader.vertexShader.replace(vProject, `${vProject}
      // transformed incluye la deformación del esqueleto y de los morph targets.
      vHgWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
      vHgViewNormal = normalize(transformedNormal);
      vHgViewDirection = normalize(-mvPosition.xyz);
    `);

    shader.fragmentShader = shader.fragmentShader.replace(fCommon, `${fCommon}
      varying vec3 vHgWorld;
      varying vec3 vHgViewNormal;
      varying vec3 vHgViewDirection;
      uniform float uHgTime;
      uniform float uHgGlow;
      uniform float uHgFacePreserve;
      uniform float uHgBodyOpacity;
      uniform float uHgOpaqueFace;
    `);
    shader.fragmentShader = shader.fragmentShader.replace(fOpaque, `${fOpaque}
      // El GLB contiene una sola malla/material: máscara geométrica suave para cara.
      vec3 hgN = normalize(vHgViewNormal);
      vec3 hgV = normalize(vHgViewDirection);
      float hgFront = clamp(abs(dot(hgN, hgV)), 0.0, 1.0);
      float hgRim = pow(1.0 - hgFront, 2.0);
      float hgHeadY = smoothstep(1.67, 1.89, vHgWorld.y);
      float hgHeadX = 1.0 - smoothstep(0.17, 0.39, abs(vHgWorld.x));
      float hgFaceMask = clamp(hgHeadY * hgHeadX * smoothstep(0.06, 0.59, hgFront), 0.0, 1.0);
      float hgScan = pow(0.5 + 0.5 * sin(vHgWorld.y * 88.0 - uHgTime * 2.0), 9.0);
      float hgWave = 0.5 + 0.5 * sin(vHgWorld.y * 13.0 - uHgTime * 1.4);
      vec3 hgSource = max(gl_FragColor.rgb, vec3(0.0));
      float hgLuma = dot(hgSource, vec3(0.2126, 0.7152, 0.0722));
      // Cuerpo = textura desaturada + radiografía cian + halo de Fresnel.
      vec3 hgCyan = vec3(0.015, 0.67, 0.83);
      vec3 hgBody = hgCyan * (0.19 + 0.62 * min(hgLuma, 1.4))
        + vec3(0.04, 0.49, 0.72) * (
            hgRim * 0.80 * uHgGlow + hgScan * 0.12 + hgWave * 0.035);
      // Rostro mantiene el detalle de sus texturas: ojos, boca, nariz y mejillas.
      vec3 hgFace = mix(
        vec3(0.05, 0.48, 0.62) * (0.28 + hgLuma),
        hgSource * vec3(0.76, 1.02, 1.13),
        uHgFacePreserve
      ) + vec3(0.00, 0.19, 0.24) * hgRim * uHgGlow;
      gl_FragColor.rgb = mix(hgBody, hgFace, hgFaceMask);
      float hgBodyAlpha = min(0.93,
        uHgBodyOpacity + hgRim * 0.25 * uHgGlow + hgScan * 0.045);
      // Cara opaca de verdad en modo proyeccion para retener pupilas y labios.
      gl_FragColor.a = mix(hgBodyAlpha, uHgOpaqueFace, hgFaceMask);
    `);
    shaders.add(shader);
    meshMat.userData.hgShader = shader;
  };
  meshMat.needsUpdate = true;
  return meshMat;
}

export function installHologramStyle(scene, THREE, search = '') {
  const options = resolveHologramMode(search);
  const shaders = new Set();
  const classicUniforms = [];
  const cache = new WeakMap();
  let meshes = 0;
  if (typeof document !== 'undefined') {
    document.body.classList.remove('hg-avatar-natural', 'hg-avatar-classic', 'hg-avatar-hybrid', 'hg-avatar-projection');
    document.body.classList.add(`hg-avatar-${options.mode}`);
  }
  if (options.fan) {
    scene.scene.background = new THREE.Color(0x000000); // negro absoluto, sin disco de color
  }

  function convert(original) {
    if (!original) return original;
    if (cache.has(original)) return cache.get(original);
    let next;
    if (options.mode === 'natural') {
      next = original;
    } else if (options.mode === 'classic') {
      const uniforms = {
        uTime: { value: 0 }, uColor: { value: new THREE.Color(0x71e9f1) },
      };
      classicUniforms.push(uniforms);
      next = classicHologramMaterial(THREE, uniforms);
    } else {
      next = installHybridShader(original, THREE, options, shaders);
    }
    cache.set(original, next);
    return next;
  }

  scene.model?.traverse((obj) => {
    if (!obj.isMesh) return;
    obj.material = Array.isArray(obj.material)
      ? obj.material.map(convert) : convert(obj.material);
    meshes += 1;
  });
  console.info(`[mIA HG V5.1] Visual: ${options.mode}; fan=${options.fan}; mallas=${meshes}`);

  return {
    ...options, meshes,
    tick(time) {
      for (const shader of shaders) shader.uniforms.uHgTime.value = time;
      for (const item of classicUniforms) item.uTime.value = time;
    },
    dispose() { shaders.clear(); classicUniforms.length = 0; },
  };
}
