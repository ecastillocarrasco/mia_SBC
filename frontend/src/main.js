import './style.css'
import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import {
  isEmployee360Payload,
  buildEmployee360Presentation,
  renderEmployee360PresentationHtml
} from './core/employee360-presentation.js'
import { AvatarController } from './core/avatar-controller.js'

console.log('### mIA FRONTEND V15.1 - GROUND + CHOREOGRAPHY + PRESENTATION + MOBILE ###')

// =======================================================
// CONFIGURACIÓN
// =======================================================

const MIA_API_BASE =
  'http://127.0.0.1:5001'

const MIA_CHAT_STREAM_URL =
  `${MIA_API_BASE}/api/mia/chat/stream`

const MIA_CHAT_URL =
  `${MIA_API_BASE}/api/mia/chat`

const MIA_LANGUAGE =
  'es-ES'

const MIA_GROUND_OFFSET =
  -0.50

// Mantiene la escala visual de la V14 aprobada.
// El movimiento de mIA se realiza desde groundRoot y nunca modifica Y.
const MIA_MODEL_HEIGHT =
  2.2

const MIA_PRESENTATION_VERSION =
  '15.1'

// =======================================================
// ESCENA
// =======================================================

const scene =
  new THREE.Scene()

scene.background =
  new THREE.Color(
    0xffffff
  )

// =======================================================
// CÁMARA
// =======================================================

const camera =
  new THREE.PerspectiveCamera(
    40,
    window.innerWidth /
      window.innerHeight,
    0.01,
    100
  )

const CAMERA_BASE = {
  x: 0,
  y: 1.58,
  z: 5.0
}

const cameraTarget =
  new THREE.Vector3(
    0,
    1.50,
    0
  )

const desiredCameraPosition =
  new THREE.Vector3(
    CAMERA_BASE.x,
    CAMERA_BASE.y,
    CAMERA_BASE.z
  )

const desiredCameraTarget =
  new THREE.Vector3(
    0,
    1.50,
    0
  )

camera.position.copy(
  desiredCameraPosition
)

camera.lookAt(
  cameraTarget
)

// =======================================================
// RENDERER
// =======================================================

const renderer =
  new THREE.WebGLRenderer({
    antialias: true
  })

renderer.setPixelRatio(
  Math.min(
    window.devicePixelRatio,
    2
  )
)

renderer.setSize(
  window.innerWidth,
  window.innerHeight
)

renderer.shadowMap.enabled =
  true

renderer.outputColorSpace =
  THREE.SRGBColorSpace

renderer.toneMapping =
  THREE.ACESFilmicToneMapping

renderer.toneMappingExposure =
  1.08

document.body.appendChild(
  renderer.domElement
)

// =======================================================
// ILUMINACIÓN
// =======================================================

const hemisphere =
  new THREE.HemisphereLight(
    0xffffff,
    0xeae8e6,
    2.1
  )

scene.add(
  hemisphere
)

const keyLight =
  new THREE.DirectionalLight(
    0xffffff,
    2.7
  )

keyLight.position.set(
  1.2,
  6,
  1.5
)

keyLight.castShadow =
  true

keyLight.shadow.mapSize.set(
  2048,
  2048
)

keyLight.shadow.camera.left =
  -5

keyLight.shadow.camera.right =
  5

keyLight.shadow.camera.top =
  5

keyLight.shadow.camera.bottom =
  -5

keyLight.shadow.bias =
  -0.00012

scene.add(
  keyLight
)

const fillLight =
  new THREE.DirectionalLight(
    0xffffff,
    1.1
  )

fillLight.position.set(
  -3,
  3,
  2
)

scene.add(
  fillLight
)

// =======================================================
// SUELO
// =======================================================

const floor =
  new THREE.Mesh(
    new THREE.PlaneGeometry(
      200,
      200
    ),
    new THREE.ShadowMaterial({
      color: 0x777777,
      opacity: 0.07
    })
  )

floor.rotation.x =
  -Math.PI / 2

floor.position.y =
  0

floor.receiveShadow =
  true

scene.add(
  floor
)

// =======================================================
// SOMBRA CONTACTO
// =======================================================

const contactShadow =
  new THREE.Mesh(
    new THREE.CircleGeometry(
      0.34,
      64
    ),
    new THREE.MeshBasicMaterial({
      color: 0x8f8f8f,
      transparent: true,
      opacity: 0.11,
      depthWrite: false
    })
  )

contactShadow.rotation.x =
  -Math.PI / 2

contactShadow.position.y =
  0.006

contactShadow.scale.set(
  1.6,
  0.72,
  1
)

scene.add(
  contactShadow
)

// =======================================================
// VARIABLES
// =======================================================

const clock =
  new THREE.Clock()

let mia =
  null

let mixer =
  null

let currentAction =
  null

let currentActionName =
  null

let avatarController =
  null

const actions =
  new Map()

const upperBodyActions =
  new Map()

let currentUpperBodyAction =
  null

let currentUpperBodyCleanup =
  null

let conversationContext =
  {}

let queryInProgress =
  false

let pendingQuickAction =
  null

let listening =
  false

let recognition =
  null

let interactionUI =
  null

let textComposer =
  null

let textInput =
  null

let micButton =
  null

let keyboardButton =
  null

let liveStatus =
  null

let answerCard =
  null

let liveStatusTimer =
  null

let startupGreetingDone =
  false

// =======================================================
// V15.1 · GROUND / MOTION / PRESENTATION
// =======================================================

let groundRoot =
  null

let miaMotion =
  null

let loadingChoreography =
  null

let lastPresentationType =
  'text'

let lastQueryDurationMs =
  0

let lastSubmittedQuery =
  ''

const MIA_HOME = {
  x: 0,
  z: 0
}

const TECHNICAL_FIELD_RE =
  /(^id$|^_id$|(^|_)id$|^intent$|query_?summary|selection_?context|conversation_?context|context$|handler|function|funcion|endpoint|route|debug|trace|stack|token|secret|odata|etag|metadata|internal|backend|avatar_?state|status_?code|http|sql|sharepoint_?field|raw|payload)/i

const FRIENDLY_LABELS = {
  nombre: 'Nombre',
  name: 'Nombre',
  displayname: 'Nombre',
  fullname: 'Nombre',
  nombrecompleto: 'Nombre',
  apellidos: 'Apellidos',
  puesto: 'Puesto',
  cargo: 'Puesto',
  jobtitle: 'Puesto',
  departamento: 'Departamento',
  department: 'Departamento',
  area: 'Área',
  responsable: 'Responsable',
  manager: 'Responsable',
  email: 'Correo electrónico',
  mail: 'Correo electrónico',
  correo: 'Correo electrónico',
  telefono: 'Teléfono',
  phone: 'Teléfono',
  movil: 'Móvil',
  mobile: 'Móvil',
  fecha: 'Fecha',
  date: 'Fecha',
  inicio: 'Inicio',
  fin: 'Fin',
  desde: 'Desde',
  hasta: 'Hasta',
  total: 'Total',
  count: 'Total',
  cantidad: 'Total',
  numero: 'Número',
  empleados: 'Empleados',
  personas: 'Personas',
  presentes: 'Presentes',
  ausentes: 'Ausentes',
  vacaciones: 'Vacaciones',
  saldo: 'Saldo',
  dias: 'Días',
  horas: 'Horas',
  turno: 'Turno',
  tipo: 'Tipo',
  estado: 'Estado',
  antiguedad: 'Antigüedad',
  fechaincorporacion: 'Fecha de incorporación',
  employeenumber: 'N.º empleado',
  numeropersonatrabajadora: 'N.º empleado',
  numsap: 'N.º empleado'
}

// =======================================================
// ESTADOS
// =======================================================

const MIA_STATE = {
  IDLE:
    'IDLE',

  LISTENING:
    'ESCUCHANDO',

  THINKING:
    'CONSULTANDO',

  PRESENTING:
    'RESULTADO',

  TALKING:
    'EXPLICANDO',

  ERROR:
    'NO ENCONTRADO'
}

let miaState =
  MIA_STATE.IDLE

function setState(
  state
) {

  miaState =
    state

  console.log(
    '[mIA STATE]',
    state
  )

  const label =
    document.querySelector(
      '.mia-state'
    )

  if (label) {

    label.textContent =
      state
  }
}

// =======================================================
// ROOT MOTION
// =======================================================

function sanitizeClip(
  originalClip
) {

  const clip =
    originalClip.clone()

  clip.tracks =
    clip.tracks.map(
      track => {

        const name =
          track.name
            .toLowerCase()

        const isRootPosition =
          name.endsWith(
            '.position'
          ) &&
          (
            name.includes(
              'hips'
            ) ||
            name.includes(
              'root'
            )
          )

        if (
          !isRootPosition
        ) {

          return track
        }

        const cleanTrack =
          track.clone()

        const values =
          cleanTrack.values

        if (
          values.length <
          3
        ) {

          return cleanTrack
        }

        const x0 =
          values[0]

        const y0 =
          values[1]

        const z0 =
          values[2]

        for (
          let i = 0;
          i < values.length;
          i += 3
        ) {

          values[i] =
            x0

          values[i + 1] =
            y0

          values[i + 2] =
            z0
        }

        return cleanTrack
      }
    )

  clip.resetDuration()

  return clip
}

// =======================================================
// AVATAR V2 · CAPA SUPERIOR
// =======================================================

const UPPER_BODY_TRACK_TOKENS = [
  'spine',
  'neck',
  'head',
  'shoulder',
  'arm',
  'forearm',
  'hand',
  'thumb',
  'index',
  'middle',
  'ring',
  'pinky'
]

function buildUpperBodyClip(
  cleanClip
) {

  const tracks =
    cleanClip.tracks
      .filter(
        track => {

          const trackName =
            track.name
              .toLowerCase()

          return UPPER_BODY_TRACK_TOKENS
            .some(
              token =>
                trackName.includes(
                  token
                )
            )
        }
      )
      .map(
        track =>
          track.clone()
      )

  if (!tracks.length) {
    return null
  }

  const clip =
    new THREE.AnimationClip(
      `${cleanClip.name}__UPPER`,
      cleanClip.duration,
      tracks
    )

  clip.resetDuration()

  return clip
}

function stopUpperBodyGesture(
  fade = 0.16
) {

  if (
    currentUpperBodyCleanup
  ) {

    const cleanup =
      currentUpperBodyCleanup

    currentUpperBodyCleanup =
      null

    cleanup(
      false,
      fade
    )

    return
  }

  const action =
    currentUpperBodyAction

  if (!action) {
    return
  }

  currentUpperBodyAction =
    null

  try {
    action.fadeOut(fade)
  } catch (_) {
    action.stop()
    return
  }

  window.setTimeout(
    () => {
      try {
        action.stop()
      } catch (_) {
        // La capa ya puede haber sido detenida por otro cambio de estado.
      }
    },
    Math.max(
      40,
      Math.round(
        fade * 1000
      ) + 30
    )
  )
}

function playUpperBodyGesture(
  name,
  {
    fadeIn = 0.16,
    fadeOut = 0.2,
    weight = 0.72,
    timeScale = 1
  } = {}
) {

  return new Promise(
    resolve => {

      const action =
        upperBodyActions.get(
          name
        )

      if (!action || !mixer) {
        resolve(false)
        return
      }

      stopUpperBodyGesture(
        Math.min(
          fadeOut,
          0.12
        )
      )

      action.stop()
      action.reset()
      action.enabled = true
      action.setEffectiveWeight(
        Math.max(
          0.1,
          Math.min(
            Number(weight) || 0.72,
            1
          )
        )
      )
      action.setEffectiveTimeScale(
        Number(timeScale) || 1
      )
      action.setLoop(
        THREE.LoopOnce,
        1
      )
      action.clampWhenFinished =
        false

      currentUpperBodyAction =
        action

      let settled =
        false

      let safetyTimer =
        null

      const finish =
        (
          completed = true,
          finalFade = fadeOut
        ) => {

          if (settled) {
            return
          }

          settled =
            true

          mixer.removeEventListener(
            'finished',
            onFinished
          )

          if (safetyTimer) {
            window.clearTimeout(
              safetyTimer
            )
          }

          if (
            currentUpperBodyAction ===
              action
          ) {
            currentUpperBodyAction =
              null
          }

          if (
            currentUpperBodyCleanup ===
              cleanup
          ) {
            currentUpperBodyCleanup =
              null
          }

          try {
            action.fadeOut(
              finalFade
            )
          } catch (_) {
            action.stop()
            resolve(completed)
            return
          }

          window.setTimeout(
            () => {
              try {
                action.stop()
              } catch (_) {
                // Sin efecto si ya se ha cambiado de gesto.
              }
            },
            Math.max(
              40,
              Math.round(
                finalFade * 1000
              ) + 30
            )
          )

          resolve(completed)
        }

      const cleanup =
        (
          completed = false,
          finalFade = fadeOut
        ) =>
          finish(
            completed,
            finalFade
          )

      const onFinished =
        event => {

          if (
            event.action !==
              action
          ) {
            return
          }

          finish(true)
        }

      currentUpperBodyCleanup =
        cleanup

      mixer.addEventListener(
        'finished',
        onFinished
      )

      action.play()
      action.fadeIn(fadeIn)

      const durationMs =
        Math.max(
          700,
          Math.ceil(
            (
              action.getClip().duration /
                Math.max(
                  0.1,
                  Math.abs(
                    Number(timeScale) || 1
                  )
                ) +
              finalFadePadding(fadeOut)
            ) * 1000
          )
        )

      safetyTimer =
        window.setTimeout(
          () =>
            finish(true),
          durationMs
        )
    }
  )
}

function finalFadePadding(
  fadeOut
) {
  return Math.max(
    0.35,
    Number(fadeOut) || 0.2
  ) + 0.25
}

// =======================================================
// LOOPS
// =======================================================

const LOOPING_ANIMATIONS =
  new Set([
    'mIA_IDLE',
    'mIA_IDLE_HAPPY',
    'mIA_IDLE_STANDING',
    'mIA_TALK',
    'mIA_WALK',
    'mIA_WALK_ALT',
    'mIA_STRUT_WALK',
    'mIA_WALK_BACK',
    'mIA_LOOK_AROUND',
    'mIA_LOOK_AROUND_ALT'
  ])

// =======================================================
// UTILIDADES
// =======================================================

function sleep(
  ms
) {

  return new Promise(
    resolve =>
      setTimeout(
        resolve,
        ms
      )
  )
}

// =======================================================
// ANIMACIONES
// =======================================================

function playAnimation(
  name,
  {
    fade = 0.45,
    loop = null,
    clamp = true
  } = {}
) {

  return new Promise(
    resolve => {

      const next =
        actions.get(
          name
        )

      if (!next) {

        console.warn(
          'Animación no encontrada:',
          name
        )

        resolve()

        return
      }

      const shouldLoop =
        loop !== null
          ? loop
          : LOOPING_ANIMATIONS
              .has(name)

      if (
        currentAction ===
          next &&
        shouldLoop
      ) {

        resolve()

        return
      }

      next.reset()

      next.enabled =
        true

      next.setEffectiveWeight(
        1
      )

      next.setEffectiveTimeScale(
        1
      )

      if (
        shouldLoop
      ) {

        next.setLoop(
          THREE.LoopRepeat,
          Infinity
        )

        next.clampWhenFinished =
          false

      } else {

        next.setLoop(
          THREE.LoopOnce,
          1
        )

        next.clampWhenFinished =
          clamp
      }

      next.play()

      if (
        currentAction &&
        currentAction !==
          next
      ) {

        currentAction
          .crossFadeTo(
            next,
            fade,
            true
          )
      }

      currentAction =
        next

      currentActionName =
        name

      if (
        shouldLoop
      ) {

        resolve()

        return
      }

      const onFinished =
        event => {

          if (
            event.action !==
            next
          ) {

            return
          }

          mixer
            .removeEventListener(
              'finished',
              onFinished
            )

          resolve()
        }

      mixer
        .addEventListener(
          'finished',
          onFinished
        )
    }
  )
}

// =======================================================
// IDLE
// =======================================================

async function goIdle(
  fade = 0.55
) {

  setState(
    MIA_STATE.IDLE
  )

  if (
    avatarController
  ) {

    await avatarController.enter(
      'idle',
      { fade }
    )

    return
  }

  await playAnimation(
    'mIA_IDLE',
    {
      fade,
      loop: true
    }
  )
}

// =======================================================
// SALUDO INICIAL
// =======================================================

function getStartupGreeting() {

  const hour =
    new Date()
      .getHours()

  if (
    hour >= 6 &&
    hour < 14
  ) {

    return {
      short:
        'Buenos días',

      full:
        'Buenos días. Soy mIA. ¿En qué puedo ayudarte?'
    }
  }

  if (
    hour >= 14 &&
    hour < 21
  ) {

    return {
      short:
        'Buenas tardes',

      full:
        'Buenas tardes. Soy mIA. ¿En qué puedo ayudarte?'
    }
  }

  return {
    short:
      'Buenas noches',

    full:
      'Buenas noches. Soy mIA. ¿En qué puedo ayudarte?'
  }
}

async function runStartupGreeting() {

  if (
    startupGreetingDone ||
    !mia ||
    !mixer
  ) {

    return
  }

  startupGreetingDone =
    true

  const greeting =
    getStartupGreeting()

  console.log(
    '[mIA GREETING]',
    greeting.full
  )

  setState(
    MIA_STATE.TALKING
  )

  setLiveStatus(
    greeting.full
  )

  let greetingAnimation =
    'mIA_YES'

  if (
    actions.has(
      'mIA_GREET'
    )
  ) {

    greetingAnimation =
      'mIA_GREET'

  } else if (
    actions.has(
      'mIA_WAVE'
    )
  ) {

    greetingAnimation =
      'mIA_WAVE'
  }

  await playAnimation(
    greetingAnimation,
    {
      fade: 0.35,
      loop: false
    }
  )

  await speakAnswer(
    greeting.full,
    {
      allowSilentFallback:
        true
    }
  )

  await goIdle(
    0.45
  )

  setLiveStatus(
    greeting.full,
    4200
  )
}

// =======================================================
// CÁMARA · V15.1
// =======================================================

function isMobileViewport() {

  return window.matchMedia(
    '(max-width: 760px)'
  ).matches
}

function isCompactLandscape() {

  return (
    window.innerWidth >
      window.innerHeight &&
    window.innerHeight < 560
  )
}

function applyResponsive3DProfile() {

  const mobile =
    isMobileViewport()

  const compactLandscape =
    isCompactLandscape()

  if (compactLandscape) {

    camera.fov = 52

    CAMERA_BASE.x = 0
    CAMERA_BASE.y = 1.42
    CAMERA_BASE.z = 7.45

  } else if (mobile) {

    camera.fov = 49

    CAMERA_BASE.x = 0
    CAMERA_BASE.y = 1.46
    CAMERA_BASE.z = 7.15

  } else if (
    window.innerWidth < 1100
  ) {

    camera.fov = 43

    CAMERA_BASE.x = 0
    CAMERA_BASE.y = 1.52
    CAMERA_BASE.z = 5.85

  } else {

    // Encuadre a nivel de pecho-cara: mIA frontal, no de cuerpo entero.
    camera.fov = 40

    CAMERA_BASE.x = 0
    CAMERA_BASE.y = 1.58
    CAMERA_BASE.z = 5.0
  }

  camera.aspect =
    window.innerWidth /
    window.innerHeight

  camera.updateProjectionMatrix()

  renderer.setPixelRatio(
    Math.min(
      window.devicePixelRatio,
      mobile ? 1.5 : 2
    )
  )

  renderer.setSize(
    window.innerWidth,
    window.innerHeight
  )
}

function updateCameraTracking() {

  if (!mia) {

    return
  }

  const rootPosition =
    groundRoot
      ? groundRoot.position
      : mia.position

  const miaX =
    rootPosition.x

  const miaZ =
    rootPosition.z

  const presenting =
    miaState ===
      MIA_STATE.PRESENTING ||
    miaState ===
      MIA_STATE.TALKING

  const followX =
    presenting
      ? 0.30
      : 0.13

  // Cuando mIA avanza hacia el usuario, la cámara la acompaña
  // sólo parcialmente. Se mantiene el efecto de acercamiento,
  // pero sin un salto de encuadre.
  const followZ =
    presenting
      ? 0.16
      : 0.10

  desiredCameraPosition.set(
    CAMERA_BASE.x +
      miaX * followX,

    CAMERA_BASE.y,

    CAMERA_BASE.z +
      miaZ * followZ
  )

  desiredCameraTarget.set(
    miaX * 0.38,
    isMobileViewport()
      ? 1.38
      : 1.50,
    miaZ * 0.18
  )

  camera.position.lerp(
    desiredCameraPosition,
    0.045
  )

  cameraTarget.lerp(
    desiredCameraTarget,
    0.055
  )

  camera.lookAt(
    cameraTarget
  )
}

// =======================================================
// SOMBRA · SIEMPRE EN EL SUELO
// =======================================================

function updateContactShadow() {

  if (!mia) {

    return
  }

  const rootPosition =
    groundRoot
      ? groundRoot.position
      : mia.position

  contactShadow.position.x =
    rootPosition.x

  contactShadow.position.z =
    rootPosition.z +
    0.03

  contactShadow.position.y =
    0.006
}

function updateVisualViewportVars() {

  const vv =
    window.visualViewport

  let keyboardOffset =
    0

  if (vv) {

    keyboardOffset =
      Math.max(
        0,
        window.innerHeight -
          vv.height -
          vv.offsetTop
      )

    document.documentElement.style.setProperty(
      '--mia-viewport-height',
      `${vv.height}px`
    )
  }

  document.documentElement.style.setProperty(
    '--mia-keyboard-offset',
    `${keyboardOffset}px`
  )
}

// =======================================================
// UI INTERACCIÓN
// =======================================================

function createInteractionUI() {

  if (
    interactionUI
  ) {

    return
  }

  const ui =
    document.createElement(
      'div'
    )

  ui.className =
    'mia-interaction'

  ui.innerHTML = `
    <div
      class="mia-live-status"
      aria-live="polite"
    ></div>

    <div class="mia-composer">

      <input
        class="mia-query-input"
        type="text"
        autocomplete="off"
        placeholder="Pregunta a mIA..."
        aria-label="Pregunta a mIA"
      />

      <button
        class="mia-send"
        type="button"
        aria-label="Enviar consulta"
      >
        →
      </button>

    </div>

    <div class="mia-input-controls">

      <button
        class="mia-mic"
        type="button"
        aria-label="Hablar con mIA"
      >
        <span class="mia-mic-dot"></span>
        <span>Hablar</span>
      </button>

      <button
        class="mia-keyboard"
        type="button"
        aria-label="Escribir a mIA"
      >
        Aa
      </button>

    </div>
  `

  document.body.appendChild(
    ui
  )

  interactionUI =
    ui

  liveStatus =
    ui.querySelector(
      '.mia-live-status'
    )

  textComposer =
    ui.querySelector(
      '.mia-composer'
    )

  textInput =
    ui.querySelector(
      '.mia-query-input'
    )

  micButton =
    ui.querySelector(
      '.mia-mic'
    )

  keyboardButton =
    ui.querySelector(
      '.mia-keyboard'
    )

  const sendButton =
    ui.querySelector(
      '.mia-send'
    )

  keyboardButton
    .addEventListener(
      'click',
      openTextComposer
    )

  micButton
    .addEventListener(
      'click',
      toggleVoiceInput
    )

  sendButton
    .addEventListener(
      'click',
      submitTextComposer
    )

  textInput
    .addEventListener(
      'keydown',
      event => {

        if (
          event.key ===
          'Enter'
        ) {

          event.preventDefault()

          submitTextComposer()
        }

        if (
          event.key ===
          'Escape'
        ) {

          closeTextComposer()
        }
      }
    )

  window.addEventListener(
    'keydown',
    event => {

      if (
        queryInProgress ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey
      ) {

        return
      }

      const target =
        event.target

      const editing =
        target instanceof
          HTMLInputElement ||
        target instanceof
          HTMLTextAreaElement ||
        target instanceof
          HTMLSelectElement

      if (
        editing
      ) {

        return
      }

      if (
        event.key.length ===
        1
      ) {

        openTextComposer()

        textInput.value +=
          event.key

        event.preventDefault()
      }
    }
  )

  setupSpeechRecognition()
}

// =======================================================
// TEXTO
// =======================================================

function openTextComposer() {

  if (
    queryInProgress ||
    !textComposer
  ) {

    return
  }

  stopVoiceInput(
    false
  )

  textComposer
    .classList
    .add(
      'visible'
    )

  keyboardButton
    ?.classList
    .add(
      'active'
    )

  requestAnimationFrame(
    () => {

      textInput
        ?.focus()
    }
  )
}

function closeTextComposer(
  clear = false
) {

  if (
    !textComposer
  ) {

    return
  }

  textComposer
    .classList
    .remove(
      'visible'
    )

  keyboardButton
    ?.classList
    .remove(
      'active'
    )

  if (
    clear &&
    textInput
  ) {

    textInput.value =
      ''
  }

  textInput
    ?.blur()
}

function submitTextComposer() {

  const value =
    String(
      textInput?.value ||
      ''
    )
      .trim()

  if (!value) {

    return
  }

  closeTextComposer(
    true
  )

  submitQuery(
    value,
    'text'
  )
}

// =======================================================
// VOZ
// =======================================================

function setupSpeechRecognition() {

  const Recognition =
    window
      .SpeechRecognition ||
    window
      .webkitSpeechRecognition

  if (
    !Recognition
  ) {

    console.warn(
      'SpeechRecognition no disponible'
    )

    if (
      micButton
    ) {

      micButton.disabled =
        true

      micButton.title =
        'Reconocimiento de voz no disponible en este navegador'
    }

    return
  }

  recognition =
    new Recognition()

  recognition.lang =
    MIA_LANGUAGE

  recognition.continuous =
    false

  recognition.interimResults =
    true

  recognition.maxAlternatives =
    1

  recognition
    .addEventListener(
      'start',
      () => {

        listening =
          true

        micButton
          ?.classList
          .add(
            'listening'
          )

        setLiveStatus(
          'Escuchando…'
        )
      }
    )

  recognition
    .addEventListener(
      'result',
      event => {

        let finalText =
          ''

        let interimText =
          ''

        for (
          let i =
            event.resultIndex;
          i <
            event.results.length;
          i++
        ) {

          const transcript =
            event
              .results[i][0]
              .transcript

          if (
            event
              .results[i]
              .isFinal
          ) {

            finalText +=
              transcript

          } else {

            interimText +=
              transcript
          }
        }

        if (
          interimText
        ) {

          setLiveStatus(
            interimText
          )
        }

        if (
          finalText.trim()
        ) {

          stopVoiceInput(
            false
          )

          submitQuery(
            finalText.trim(),
            'voice'
          )
        }
      }
    )

  recognition
    .addEventListener(
      'error',
      event => {

        console.warn(
          'SpeechRecognition:',
          event.error
        )

        stopVoiceInput(
          false
        )

        if (
          event.error !==
          'no-speech'
        ) {

          setLiveStatus(
            'No he podido escucharte bien.',
            2500
          )
        }
      }
    )

  recognition
    .addEventListener(
      'end',
      () => {

        listening =
          false

        micButton
          ?.classList
          .remove(
            'listening'
          )
      }
    )
}

function toggleVoiceInput() {

  if (
    queryInProgress ||
    !recognition
  ) {

    return
  }

  if (
    listening
  ) {

    stopVoiceInput()

    return
  }

  closeTextComposer()

  try {

    recognition.start()

  } catch (
    error
  ) {

    console.warn(
      'No se pudo iniciar el micrófono:',
      error
    )
  }
}

function stopVoiceInput(
  clearStatus = true
) {

  if (
    recognition &&
    listening
  ) {

    try {

      recognition.stop()

    } catch {}
  }

  listening =
    false

  micButton
    ?.classList
    .remove(
      'listening'
    )

  if (
    clearStatus
  ) {

    setLiveStatus(
      ''
    )
  }
}

// =======================================================
// ESTADO TEMPORAL
// =======================================================

function setLiveStatus(
  message,
  autoHide = 0
) {

  if (
    !liveStatus
  ) {

    return
  }

  clearTimeout(
    liveStatusTimer
  )

  liveStatus.textContent =
    message ||
    ''

  liveStatus
    .classList
    .toggle(
      'visible',
      Boolean(
        message
      )
    )

  if (
    message &&
    autoHide > 0
  ) {

    liveStatusTimer =
      setTimeout(
        () => {

          setLiveStatus(
            ''
          )
        },
        autoHide
      )
  }
}

// =======================================================
// STREAM BACKEND
// =======================================================

async function requestBackendStream(
  text
) {

  const response =
    await fetch(
      MIA_CHAT_STREAM_URL,
      {
        method:
          'POST',

        headers: {
          'Content-Type':
            'application/json'
        },

        body:
          JSON.stringify({
            message:
              text,

            context:
              conversationContext
          })
      }
    )

  if (
    !response.ok
  ) {

    throw new Error(
      `Stream HTTP ${
        response.status
      }`
    )
  }

  if (
    !response.body
  ) {

    throw new Error(
      'Stream sin body'
    )
  }

  const reader =
    response.body
      .getReader()

  const decoder =
    new TextDecoder(
      'utf-8'
    )

  let buffer =
    ''

  let finalPayload =
    null

  while (
    true
  ) {

    const {
      value,
      done
    } =
      await reader
        .read()

    if (
      done
    ) {

      break
    }

    buffer +=
      decoder.decode(
        value,
        {
          stream: true
        }
      )

    const lines =
      buffer.split(
        /\r?\n/
      )

    buffer =
      lines.pop() ||
      ''

    for (
      const rawLine
      of lines
    ) {

      const line =
        rawLine
          .trim()

      if (!line) {

        continue
      }

      let event

      try {

        event =
          JSON.parse(
            line
          )

      } catch (
        error
      ) {

        console.warn(
          '[mIA STREAM] JSON inválido:',
          line,
          error
        )

        continue
      }

      console.log(
        '[mIA STREAM]',
        event
      )

      if (
        event.type ===
        'progress'
      ) {

        handleBackendProgress(
          event
        )

        continue
      }

      if (
        event.type ===
        'heartbeat'
      ) {

        continue
      }

      if (
        event.type ===
        'result'
      ) {

        finalPayload =
          event.payload ||
          event.data ||
          event.result ||
          {}

        return finalPayload
      }
    }
  }

  if (
    buffer.trim()
  ) {

    try {

      const event =
        JSON.parse(
          buffer.trim()
        )

      if (
        event.type ===
        'result'
      ) {

        finalPayload =
          event.payload ||
          event.data ||
          event.result ||
          {}
      }

    } catch {}
  }

  if (
    !finalPayload
  ) {

    throw new Error(
      'El stream terminó sin result'
    )
  }

  return finalPayload
}

// =======================================================
// FALLBACK BACKEND NORMAL
// =======================================================

async function requestBackendNormal(
  text
) {

  console.warn(
    '[mIA] Fallback /api/mia/chat'
  )

  setLiveStatus(
    'Terminando la consulta…'
  )

  const response =
    await fetch(
      MIA_CHAT_URL,
      {
        method:
          'POST',

        headers: {
          'Content-Type':
            'application/json'
        },

        body:
          JSON.stringify({
            message:
              text,

            context:
              conversationContext
          })
      }
    )

  if (
    !response.ok
  ) {

    throw new Error(
      `Chat HTTP ${
        response.status
      }`
    )
  }

  return await response
    .json()
}

// =======================================================
// V15.1 · MOTOR DE MOVIMIENTO SOBRE EL SUELO
// =======================================================

function easeInOutCubic(t) {

  return t < 0.5
    ? 4 * t * t * t
    : 1 - Math.pow(
        -2 * t + 2,
        3
      ) / 2
}

function startGroundMotion(
  targetX,
  targetZ,
  duration = 900
) {

  if (!groundRoot) {

    return Promise.resolve()
  }

  if (
    miaMotion &&
    typeof miaMotion.resolve ===
      'function'
  ) {

    miaMotion.resolve()
  }

  const startX =
    groundRoot.position.x

  const startZ =
    groundRoot.position.z

  let resolveMotion

  const promise =
    new Promise(
      resolve => {

        resolveMotion =
          resolve
      }
    )

  miaMotion = {
    startTime:
      performance.now(),

    duration:
      Math.max(
        180,
        duration
      ),

    startX,
    startZ,
    targetX,
    targetZ,
    promise,
    resolve:
      resolveMotion
  }

  return promise
}

function updateGroundMotion(
  now
) {

  if (
    !groundRoot ||
    !miaMotion
  ) {

    return
  }

  const elapsed =
    now -
    miaMotion.startTime

  const progress =
    Math.min(
      1,
      elapsed /
        miaMotion.duration
    )

  const eased =
    easeInOutCubic(
      progress
    )

  groundRoot.position.x =
    THREE.MathUtils.lerp(
      miaMotion.startX,
      miaMotion.targetX,
      eased
    )

  groundRoot.position.z =
    THREE.MathUtils.lerp(
      miaMotion.startZ,
      miaMotion.targetZ,
      eased
    )

  // El root nunca se despega del suelo.
  groundRoot.position.y =
    0

  if (
    progress >= 1
  ) {

    const finished =
      miaMotion

    miaMotion =
      null

    finished.resolve()
  }
}

function getWalkAnimation() {

  if (
    actions.has(
      'mIA_STRUT_WALK'
    )
  ) {

    return 'mIA_STRUT_WALK'
  }

  if (
    actions.has(
      'mIA_WALK'
    )
  ) {

    return 'mIA_WALK'
  }

  return 'mIA_WALK_ALT'
}

async function walkMiaTo(
  x,
  z,
  {
    duration = 850,
    finishIdle = true
  } = {}
) {

  if (!groundRoot) {

    return
  }

  const distance =
    Math.hypot(
      x - groundRoot.position.x,
      z - groundRoot.position.z
    )

  if (
    distance < 0.025
  ) {

    return
  }

  const walkAnimation =
    getWalkAnimation()

  playAnimation(
    walkAnimation,
    {
      fade: 0.34,
      loop: true
    }
  )

  await startGroundMotion(
    x,
    z,
    Math.max(
      420,
      duration
    )
  )

  if (finishIdle) {

    await goIdle(
      0.34
    )
  }
}

async function waitForCurrentMotion() {

  const activeMotion =
    miaMotion

  if (
    activeMotion?.promise
  ) {

    await activeMotion.promise
  }
}

async function returnMiaHome(
  {
    duration = 720,
    finishIdle = true
  } = {}
) {

  if (!groundRoot) {

    return
  }

  await waitForCurrentMotion()

  await walkMiaTo(
    MIA_HOME.x,
    MIA_HOME.z,
    {
      duration,
      finishIdle
    }
  )
}

function miaIsAwayFromHome() {

  if (!groundRoot) {

    return false
  }

  return (
    Math.abs(
      groundRoot.position.x -
      MIA_HOME.x
    ) > 0.04 ||
    Math.abs(
      groundRoot.position.z -
      MIA_HOME.z
    ) > 0.04
  )
}

async function performLoadingWalk(
  controller
) {

  if (
    !groundRoot ||
    controller.cancelled
  ) {

    return
  }

  const mobile =
    isMobileViewport()

  const side =
    mobile
      ? -0.16
      : -0.38

  const forward =
    mobile
      ? 0.18
      : 0.34

  await walkMiaTo(
    side,
    forward,
    {
      duration:
        mobile
          ? 720
          : 980,
      finishIdle:
        false
    }
  )

  if (
    controller.cancelled
  ) {

    await returnMiaHome({
      duration: 620
    })

    return
  }

  if (
    actions.has(
      'mIA_LOOK_AROUND_ALT'
    )
  ) {

    playAnimation(
      'mIA_LOOK_AROUND_ALT',
      {
        fade: 0.3,
        loop: false
      }
    )
  }

  await sleep(
    520
  )

  await returnMiaHome({
    duration:
      mobile
        ? 650
        : 880,
    finishIdle:
      false
  })

  if (
    !controller.cancelled
  ) {

    playAnimation(
      'mIA_THINK',
      {
        fade: 0.32,
        loop: true
      }
    )
  }
}

// =======================================================
// V15.1 · COREOGRAFÍA DE ESPERA
// =======================================================

function scheduleLoadingStage(
  controller,
  delay,
  callback
) {

  const timer =
    setTimeout(
      async () => {

        if (
          controller.cancelled
        ) {

          return
        }

        try {

          await callback()

        } catch (
          error
        ) {

          console.warn(
            '[mIA CHOREOGRAPHY]',
            error
          )
        }
      },
      delay
    )

  controller.timers.push(
    timer
  )
}

function startLoadingChoreography() {

  cancelLoadingChoreography()

  const controller = {
    cancelled: false,
    timers: [],
    startedAt:
      performance.now(),
    backendState: ''
  }

  loadingChoreography =
    controller

  // Una respuesta realmente rápida no necesita hacer pensar a mIA.
  scheduleLoadingStage(
    controller,
    700,
    async () => {

      setState(
        MIA_STATE.THINKING
      )

      if (
        avatarController
      ) {

        avatarController.enter(
          'thinking',
          {
            query:
              lastSubmittedQuery,
            fade: 0.34
          }
        )

      } else {

        playAnimation(
          'mIA_THINK',
          {
            fade: 0.34,
            loop: true
          }
        )
      }
    }
  )

  scheduleLoadingStage(
    controller,
    2300,
    async () => {

      const look =
        actions.has(
          'mIA_LOOK_AROUND'
        )
          ? 'mIA_LOOK_AROUND'
          : 'mIA_THINK'

      await playAnimation(
        look,
        {
          fade: 0.32,
          loop:
            look ===
            'mIA_THINK'
        }
      )

      if (
        !controller.cancelled
      ) {

        playAnimation(
          'mIA_THINK',
          {
            fade: 0.3,
            loop: true
          }
        )
      }
    }
  )

  scheduleLoadingStage(
    controller,
    4300,
    async () => {

      await performLoadingWalk(
        controller
      )
    }
  )

  scheduleLoadingStage(
    controller,
    9000,
    async () => {

      if (
        actions.has(
          'mIA_LOOK_AROUND_ALT'
        )
      ) {

        playAnimation(
          'mIA_LOOK_AROUND_ALT',
          {
            fade: 0.3,
            loop: false
          }
        )
      }
    }
  )

  return controller
}

function cancelLoadingChoreography() {

  if (
    !loadingChoreography
  ) {

    return
  }

  loadingChoreography.cancelled =
    true

  loadingChoreography.timers
    .forEach(
      timer =>
        clearTimeout(
          timer
        )
    )

  loadingChoreography.timers =
    []

  loadingChoreography =
    null
}

async function ensureMiaReadyForPresentation() {

  await waitForCurrentMotion()

  if (
    miaIsAwayFromHome()
  ) {

    await returnMiaHome({
      duration: 650,
      finishIdle: false
    })
  }
}

// =======================================================
// CONSULTA
// =======================================================

async function submitQuery(
  text,
  source = 'voice'
) {

  const query =
    String(
      text ||
      ''
    )
      .trim()

  if (
    queryInProgress ||
    !query
  ) {

    return
  }

  lastSubmittedQuery =
    query

  queryInProgress =
    true

  hideBackendResult()

  closeTextComposer(
    true
  )

  stopVoiceInput(
    false
  )

  if (micButton) {
    micButton.disabled = true
  }

  if (keyboardButton) {
    keyboardButton.disabled = true
  }

  const startedAt =
    performance.now()

  console.log(
    '[mIA QUERY]',
    {
      text: query,
      source,
      context:
        conversationContext
    }
  )

  try {

    setState(
      MIA_STATE.LISTENING
    )

    setLiveStatus(
      source === 'voice'
        ? 'Te he escuchado.'
        : 'He recibido tu consulta.'
    )

    // mIA confirma que ha entendido. El AvatarController elige
    // una variante disponible sin bloquear la llamada al backend.
    if (
      avatarController
    ) {

      avatarController.enter(
        'listening',
        { query }
      )

    } else {

      playAnimation(
        'mIA_YES',
        {
          fade: 0.28,
          loop: false
        }
      )
    }

    const choreography =
      startLoadingChoreography()

    let payload =
      null

    try {

      payload =
        await requestBackendStream(
          query
        )

    } catch (
      streamError
    ) {

      console.warn(
        '[mIA] Falló stream:',
        streamError
      )

      payload =
        await requestBackendNormal(
          query
        )
    }

    choreography.cancelled =
      true

    cancelLoadingChoreography()

    lastQueryDurationMs =
      performance.now() -
      startedAt

    console.log(
      '[mIA PAYLOAD FINAL]',
      payload,
      `(${Math.round(lastQueryDurationMs)} ms)`
    )

    if (
      !payload ||
      typeof payload !==
        'object'
    ) {

      throw new Error(
        'Respuesta backend vacía'
      )
    }

    await ensureMiaReadyForPresentation()

    await handleBackendResult(
      payload
    )

  } catch (
    error
  ) {

    cancelLoadingChoreography()

    console.error(
      '[mIA ERROR CONSULTA]',
      error
    )

    setState(
      MIA_STATE.ERROR
    )

    setLiveStatus(
      'No he podido completar la consulta.',
      4000
    )

    await ensureMiaReadyForPresentation()

    if (
      actions.has(
        'mIA_SHRUG'
      )
    ) {

      await playAnimation(
        'mIA_SHRUG',
        {
          fade: 0.35,
          loop: false
        }
      )
    }

    await goIdle(
      0.5
    )

  } finally {

    queryInProgress =
      false

    if (micButton) {
      micButton.disabled = false
    }

    if (keyboardButton) {
      keyboardButton.disabled = false
    }

    const queuedAction =
      pendingQuickAction

    pendingQuickAction =
      null

    if (queuedAction) {
      window.setTimeout(
        () => {
          if (!queryInProgress) {
            submitQuery(
              queuedAction,
              'action'
            )
          }
        },
        0
      )
    }
  }
}

// =======================================================
// PROGRESO
// =======================================================

function handleBackendProgress(
  event
) {

  console.log(
    '[mIA PROGRESS]',
    event
  )

  const message =
    event.message ||
    event.detail ||
    event.text ||
    ''

  if (message) {

    setLiveStatus(
      cleanUserFacingText(
        message
      )
    )
  }

  if (
    loadingChoreography
  ) {

    loadingChoreography.backendState =
      String(
        event.state ||
        event.avatar_state ||
        ''
      )
  }
}

// =======================================================
// GUARDIA CONVERSACIONAL
// =======================================================

function isSimpleConversationQuery(
  text
) {

  const normalized =
    String(text || '')
      .trim()
      .toLowerCase()
      .replace(/[¿?¡!.,;:]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  if (!normalized) {
    return false
  }

  const simplePatterns = [
    /^(hola|buenas|buenos dias|buenas tardes|buenas noches)( mia)?$/,
    /^(hola|buenas) mia$/,
    /^(gracias|muchas gracias|gracias mia|muchas gracias mia)$/,
    /^(adios|hasta luego|nos vemos|hasta pronto)( mia)?$/,
    /^(que tal|como estas|como va)( mia)?$/,
    /^(quien eres|que eres|que puedes hacer)( mia)?$/
  ]

  return simplePatterns.some(
    pattern =>
      pattern.test(normalized)
  )
}

function presentationHasStructuredData(
  presentation
) {

  return Boolean(
    presentation?.cards?.length ||
    presentation?.table?.rows?.length ||
    presentation?.visualizations?.length ||
    presentation?.insights?.length ||
    presentation?.actions?.length ||
    presentation?.type === 'scalar' ||
    presentation?.type === 'employee360' ||
    presentation?.type === 'person' ||
    presentation?.type === 'department' ||
    presentation?.type === 'analytics' ||
    presentation?.type === 'comparison' ||
    presentation?.type === 'list' ||
    presentation?.type === 'shifts' ||
    presentation?.type === 'document'
  )
}

function shouldUseVoiceOnly(
  presentation
) {

  if (
    !isSimpleConversationQuery(
      lastSubmittedQuery
    )
  ) {
    return false
  }

  return !presentationHasStructuredData(
    presentation
  ) || presentation.type === 'text'
}

// =======================================================
// RESULTADO FINAL
// =======================================================

async function handleBackendResult(
  payload
) {

  console.log(
    '[mIA RESULT]',
    payload
  )

  if (
    payload.context &&
    typeof payload.context ===
      'object'
  ) {

    conversationContext =
      payload.context
  }

  const answer =
    cleanUserFacingText(
      String(
        payload.answer ||
        payload.response ||
        payload.message ||
        'He terminado la consulta.'
      )
        .trim()
    )

  const isError =
    payload.status ===
      'error' ||
    payload.error ===
      true

  if (isError) {

    setLiveStatus(
      answer,
      4500
    )

    if (
      actions.has(
        'mIA_SHRUG'
      )
    ) {

      await playAnimation(
        'mIA_SHRUG',
        {
          fade: 0.4,
          loop: false
        }
      )
    }

    await goIdle()

    return
  }

  const presentation =
    normalizePresentation(
      payload
    )

  if (
    shouldUseVoiceOnly(
      presentation
    )
  ) {

    lastPresentationType =
      'text'

    hideBackendResult()

    setState(
      MIA_STATE.TALKING
    )

    if (
      avatarController
    ) {

      avatarController.enter(
        'speaking',
        {
          query:
            lastSubmittedQuery,
          answer,
          presentationType:
            'text',
          fade: 0.32
        }
      )

    } else if (
      actions.has(
        'mIA_TALK'
      )
    ) {

      playAnimation(
        'mIA_TALK',
        {
          fade: 0.32,
          loop: true
        }
      )
    }

    setLiveStatus('')

    await speakAnswer(
      answer
    )

    await goIdle(
      0.5
    )

    return
  }

  lastPresentationType =
    presentation.type

  await preparePresentationPosition(
    presentation.type
  )

  setLiveStatus(
    'Ya lo tengo.'
  )

  setState(
    MIA_STATE.PRESENTING
  )

  const presentationAnimation =
    getPresentationAnimation(
      presentation.type
    )

  if (
    avatarController
  ) {

    avatarController.enter(
      'presenting',
      {
        query:
          lastSubmittedQuery,
        answer,
        presentationType:
          presentation.type,
        preferredAnimation:
          presentationAnimation,
        fade: 0.38
      }
    )

  } else {

    playAnimation(
      presentationAnimation,
      {
        fade: 0.38,
        loop: false
      }
    )
  }

  // El resultado aparece mientras el gesto está vivo,
  // no cuando ya ha terminado toda la animación.
  await sleep(
    presentation.type ===
      'scalar'
      ? 120
      : 260
  )

  showBackendResultV151(
    presentation
  )

  await sleep(
    presentation.type ===
      'scalar'
      ? 180
      : 360
  )

  setState(
    MIA_STATE.TALKING
  )

  if (
    avatarController
  ) {

    avatarController.enter(
      'speaking',
      {
        query:
          lastSubmittedQuery,
        answer,
        presentationType:
          presentation.type,
        fade: 0.38
      }
    )

  } else {

    playAnimation(
      'mIA_TALK',
      {
        fade: 0.38,
        loop: true
      }
    )
  }

  setLiveStatus('')

  await speakAnswer(
    answer
  )

  await goIdle(
    0.55
  )
}

// =======================================================
// VOZ DE mIA
// ElevenLabs + fallback Web Speech
// =======================================================

let miaVoiceAudio = null
let miaVoiceObjectUrl = null
let miaVoiceAbortController = null


function stopMiaVoicePlayback() {

  // Cancelamos una petición TTS pendiente
  if (
    miaVoiceAbortController
  ) {

    try {
      miaVoiceAbortController.abort()
    } catch {}

    miaVoiceAbortController = null
  }

  // Paramos audio ElevenLabs actual
  if (
    miaVoiceAudio
  ) {

    try {
      miaVoiceAudio.pause()
      miaVoiceAudio.currentTime = 0
    } catch {}

    miaVoiceAudio = null
  }

  // Liberamos URL temporal
  if (
    miaVoiceObjectUrl
  ) {

    try {
      URL.revokeObjectURL(
        miaVoiceObjectUrl
      )
    } catch {}

    miaVoiceObjectUrl = null
  }

  // Cancelamos también el fallback del navegador
  if (
    'speechSynthesis'
    in window
  ) {

    try {
      window
        .speechSynthesis
        .cancel()
    } catch {}
  }
}


async function speakAnswer(
  text,
  {
    allowSilentFallback =
      false
  } = {}
) {

  const speechText =
    String(
      text || ''
    ).trim()

  if (
    !speechText
  ) {

    return
  }

  stopMiaVoicePlayback()

  // =====================================================
  // 1. VOZ PRINCIPAL: ElevenLabs
  // =====================================================

  try {

    const controller =
      new AbortController()

    miaVoiceAbortController =
      controller

    const response =
      await fetch(
        '/api/mia/voice',
        {
          method:
            'POST',

          headers: {
            'Content-Type':
              'application/json; charset=utf-8',

            'Accept':
              'audio/mpeg'
          },

          body:
            JSON.stringify({
              text:
                speechText,

              locale:
                MIA_LANGUAGE ||
                'es-ES'
            }),

          signal:
            controller.signal
        }
      )

    if (
      !response.ok
    ) {

      throw new Error(
        `ElevenLabs HTTP ${response.status}`
      )
    }

    const audioBlob =
      await response.blob()

    miaVoiceAbortController =
      null

    miaVoiceObjectUrl =
      URL.createObjectURL(
        audioBlob
      )

    const audio =
      new Audio(
        miaVoiceObjectUrl
      )

    miaVoiceAudio =
      audio

    audio.preload =
      'auto'

    audio.volume =
      1

    await new Promise(
      async (
        resolve,
        reject
      ) => {

        let finished =
          false

        const finish =
          () => {

            if (
              finished
            ) {

              return
            }

            finished =
              true

            if (
              miaVoiceAudio ===
              audio
            ) {

              miaVoiceAudio =
                null
            }

            if (
              miaVoiceObjectUrl
            ) {

              try {

                URL
                  .revokeObjectURL(
                    miaVoiceObjectUrl
                  )

              } catch {}

              miaVoiceObjectUrl =
                null
            }

            resolve()
          }


        const fail =
          () => {

            if (
              finished
            ) {

              return
            }

            finished =
              true

            if (
              miaVoiceAudio ===
              audio
            ) {

              miaVoiceAudio =
                null
            }

            reject(
              new Error(
                'No se pudo reproducir el audio de ElevenLabs.'
              )
            )
          }


        audio.addEventListener(
          'ended',
          finish,
          {
            once: true
          }
        )

        audio.addEventListener(
          'error',
          fail,
          {
            once: true
          }
        )

        try {

          await audio.play()

        } catch (
          error
        ) {

          fail()
        }


        // Protección adicional:
        // si el navegador no dispara correctamente ended/error,
        // no dejamos bloqueado el flujo del avatar.
        if (
          allowSilentFallback
        ) {

          const estimatedDuration =
            Math.max(
              4000,
              Math.min(
                60000,
                speechText.length *
                  75
              )
            )

          setTimeout(
            finish,
            estimatedDuration
          )
        }
      }
    )

    return

  } catch (
    error
  ) {

    miaVoiceAbortController =
      null

    // Si se abortó porque empezó otra respuesta,
    // no lanzamos la voz fallback.
    if (
      error?.name ===
      'AbortError'
    ) {

      return
    }

    console.warn(
      '[mIA Voice] ElevenLabs no disponible. Uso fallback del navegador.',
      error
    )
  }


  // =====================================================
  // 2. FALLBACK: Web Speech del navegador
  // =====================================================

  await speakAnswerBrowserFallback(
    speechText,
    {
      allowSilentFallback
    }
  )
}


// =======================================================
// FALLBACK DE VOZ DEL NAVEGADOR
// =======================================================

function speakAnswerBrowserFallback(
  text,
  {
    allowSilentFallback =
      false
  } = {}
) {

  return new Promise(
    resolve => {

      if (
        !text ||
        !(
          'speechSynthesis'
          in window
        )
      ) {

        resolve()

        return
      }

      window
        .speechSynthesis
        .cancel()

      const utterance =
        new SpeechSynthesisUtterance(
          text
        )

      utterance.lang =
        MIA_LANGUAGE

      utterance.rate =
        1.0

      utterance.pitch =
        1.02

      utterance.volume =
        1

      let finished =
        false

      const finish =
        () => {

          if (
            finished
          ) {

            return
          }

          finished =
            true

          resolve()
        }

      utterance
        .addEventListener(
          'end',
          finish
        )

      utterance
        .addEventListener(
          'error',
          finish
        )

      try {

        window
          .speechSynthesis
          .speak(
            utterance
          )

        if (
          allowSilentFallback
        ) {

          setTimeout(
            finish,
            1800
          )
        }

      } catch {

        finish()
      }
    }
  )
}
// =======================================================
// TARJETA PREMIUM
// =======================================================

function ensureBackendResultCard() {

  if (
    answerCard
  ) {

    return
  }

  answerCard =
    document.createElement(
      'section'
    )

  answerCard.className =
    'mia-backend-result'

  document.body.appendChild(
    answerCard
  )
}

// =======================================================
// MOSTRAR RESULTADO
// =======================================================

function showBackendResult(
  payload
) {

  ensureBackendResultCard()

  const data =
    payload.data &&
    typeof payload.data ===
      'object'
      ? payload.data
      : {}

  const answer =
    String(
      payload.answer ||
      payload.response ||
      payload.message ||
      ''
    )

  const cards =
    getResultCards(
      data
    )

  const table =
    getResultTable(
      data
    )

  const sources =
    Array.isArray(
      payload.sources
    )
      ? payload.sources
      : []

  const actionsResult =
    Array.isArray(
      payload.actions
    )
      ? payload.actions
      : []

  const visualizations =
    Array.isArray(
      payload.visualizations
    )
      ? payload.visualizations
      : []

  const dataQuality =
    payload.data_quality &&
    typeof payload.data_quality ===
      'object'
      ? payload.data_quality
      : null

  const querySummary =
    data.query_summary ||
    data.querySummary ||
    ''

  answerCard.innerHTML = `
    <div class="result-shell">

      <header class="result-premium-header">

        <div class="result-title-block">

          <div class="result-kicker">
            <span class="result-status-dot"></span>
            RESULTADO mIA
          </div>

          <h2>
            ${escapeHtml(
              getResultTitle(
                payload,
                table
              )
            )}
          </h2>

          ${
            querySummary
              ? `
                <p class="result-query-summary">
                  ${escapeHtml(
                    querySummary
                  )}
                </p>
              `
              : ''
          }

        </div>

        <button
          class="backend-result-close"
          type="button"
          aria-label="Cerrar resultado"
        >
          ×
        </button>

      </header>

      <section class="result-answer-panel">

        <div class="result-answer-icon">
          mIA
        </div>

        <div class="result-answer-copy">

          <span>
            RESUMEN
          </span>

          <p>
            ${escapeHtml(
              answer
            )}
          </p>

        </div>

      </section>

      ${
        cards.length
          ? `
            <section class="result-kpis">

              ${cards
                .map(
                  card => `
                    <article class="result-kpi">

                      <span>
                        ${escapeHtml(
                          card.label
                        )}
                      </span>

                      <div>

                        <strong>
                          ${escapeHtml(
                            card.value
                          )}
                        </strong>

                        ${
                          card.unit
                            ? `
                              <small>
                                ${escapeHtml(
                                  card.unit
                                )}
                              </small>
                            `
                            : ''
                        }

                      </div>

                    </article>
                  `
                )
                .join('')}

            </section>
          `
          : ''
      }

      ${
        table &&
        Array.isArray(
          table.rows
        ) &&
        table.rows.length
          ? `
            <section class="result-table-section">

              <div class="result-section-heading">

                <div>

                  <span>
                    LISTADO
                  </span>

                  <h3>
                    ${escapeHtml(
                      table.title ||
                      'Detalle'
                    )}
                  </h3>

                </div>

                <div class="result-count">

                  ${escapeHtml(
                    String(
                      table.total ??
                      table.rows.length
                    )
                  )}

                  ${
                    Number(
                      table.total ??
                      table.rows.length
                    ) === 1
                      ? 'registro'
                      : 'registros'
                  }

                </div>

              </div>

              ${renderResultTable(
                table
              )}

            </section>
          `
          : ''
      }

      ${
        visualizations.length
          ? renderVisualizations(
              visualizations
            )
          : ''
      }

      ${
        dataQuality ||
        sources.length
          ? `
            <section class="result-meta">

              ${
                dataQuality
                  ? renderDataQuality(
                      dataQuality
                    )
                  : ''
              }

              ${
                sources.length
                  ? `
                    <div class="result-sources">

                      <span class="result-meta-label">
                        FUENTES
                      </span>

                      <div class="result-source-tags">

                        ${sources
                          .map(
                            source => `
                              <span>
                                ${escapeHtml(
                                  typeof source ===
                                    'string'
                                    ? source
                                    : source.name ||
                                      source.title ||
                                      'Fuente'
                                )}
                              </span>
                            `
                          )
                          .join('')}

                      </div>

                    </div>
                  `
                  : ''
              }

            </section>
          `
          : ''
      }

      ${
        actionsResult.length
          ? `
            <footer class="result-actions">

              ${actionsResult
                .slice(
                  0,
                  4
                )
                .map(
                  (
                    action,
                    index
                  ) => `
                    <a
                      class="${
                        index === 0
                          ? 'result-action-primary'
                          : 'result-action-secondary'
                      }"
                      href="${escapeHtml(
                        absolutizeBackendUrl(
                          action.url ||
                          '#'
                        )
                      )}"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      ${escapeHtml(
                        action.label ||
                        action.title ||
                        'Abrir'
                      )}
                    </a>
                  `
                )
                .join('')}

            </footer>
          `
          : ''
      }

    </div>
  `

  answerCard
    .querySelector(
      '.backend-result-close'
    )
    ?.addEventListener(
      'click',
      hideBackendResult
    )

  requestAnimationFrame(
    () => {

      answerCard
        .classList
        .add(
          'visible'
        )

      bindResultTableSearch()
    }
  )
}

// =======================================================
// TITULO
// =======================================================

function getResultTitle(
  payload,
  table
) {

  if (
    table?.title
  ) {

    return table.title
  }

  const intent =
    String(
      payload.intent ||
      ''
    )

  const titles = {

    vacaciones_personas_vigentes:
      'Personas de vacaciones',

    vacaciones_solicitudes:
      'Solicitudes de vacaciones',

    empleados_plan:
      'Plantilla',

    cohorte_cruce_turnos:
      'Turnos',

    cohorte_cruce_vacaciones:
      'Vacaciones',

    cohorte_cruce_saldos:
      'Saldos de vacaciones',

    analitica_departamento_dia_v1029:
      'Análisis del departamento'
  }

  return (
    titles[intent] ||
    humanizeKey(
      intent
    ) ||
    'Resultado'
  )
}

// =======================================================
// CARDS
// =======================================================

function getResultCards(
  data
) {

  if (
    Array.isArray(
      data.cards
    )
  ) {

    return data.cards
      .slice(
        0,
        8
      )
      .map(
        card => ({
          label:
            String(
              card.label ||
              card.title ||
              ''
            ),

          value:
            String(
              card.value ??
              card.total ??
              ''
            ),

          unit:
            String(
              card.unit ||
              ''
            )
        })
      )
  }

  return buildResultSummary(
    data
  )
    .slice(
      0,
      6
    )
    .map(
      item => ({
        label:
          item.label,

        value:
          item.value,

        unit:
          ''
      })
    )
}

// =======================================================
// TABLAS
// =======================================================

function getResultTable(
  data
) {

  if (
    data.table &&
    typeof data.table ===
      'object' &&
    Array.isArray(
      data.table.rows
    )
  ) {

    return normalizeTable(
      data.table
    )
  }

  if (
    Array.isArray(
      data.resultado
    )
  ) {

    return tableFromRows(
      data.resultado,
      'Detalle'
    )
  }

  for (
    const [
      key,
      value
    ]
    of Object.entries(
      data
    )
  ) {

    if (
      Array.isArray(
        value
      ) &&
      value.length &&
      value.every(
        row =>
          row &&
          typeof row ===
            'object' &&
          !Array.isArray(
            row
          )
      )
    ) {

      return tableFromRows(
        value,
        humanizeKey(
          key
        )
      )
    }
  }

  return null
}

function normalizeTable(
  table
) {

  const rows =
    Array.isArray(
      table.rows
    )
      ? table.rows
      : []

  let columns =
    Array.isArray(
      table.columns
    )
      ? table.columns
      : []

  if (
    !columns.length &&
    rows.length
  ) {

    columns =
      Object.keys(
        rows[0]
      )
  }

  return {
    title:
      table.title ||
      'Detalle',

    columns,

    rows,

    total:
      table.total ??
      rows.length,

    searchable:
      Boolean(
        table.searchable
      ) ||
      rows.length >
        8
  }
}

function tableFromRows(
  rows,
  title
) {

  if (
    !rows.length
  ) {

    return null
  }

  return {
    title,

    columns:
      Object.keys(
        rows[0]
      ),

    rows,

    total:
      rows.length,

    searchable:
      rows.length >
      8
  }
}

// =======================================================
// RENDER TABLA
// =======================================================

function renderResultTable(
  table
) {

  const columns =
    table.columns ||
    []

  const rows =
    table.rows ||
    []

  const visibleRows =
    rows.slice(
      0,
      100
    )

  return `
    <div class="premium-table-wrap">

      ${
        table.searchable
          ? `
            <div class="result-table-tools">

              <div class="result-table-search-shell">

                <span>
                  ⌕
                </span>

                <input
                  class="result-table-search"
                  type="search"
                  placeholder="Buscar en el resultado..."
                />

              </div>

            </div>
          `
          : ''
      }

      <div class="result-table-scroll">

        <table class="premium-result-table">

          <thead>

            <tr>

              ${columns
                .map(
                  column => `
                    <th>
                      ${escapeHtml(
                        getColumnLabel(
                          column
                        )
                      )}
                    </th>
                  `
                )
                .join('')}

            </tr>

          </thead>

          <tbody>

            ${visibleRows
              .map(
                row => `
                  <tr
                    data-search="${escapeHtml(
                      Object.values(
                        row
                      )
                        .map(
                          value =>
                            formatCellValue(
                              value
                            )
                        )
                        .join(
                          ' '
                        )
                        .toLowerCase()
                    )}"
                  >

                    ${columns
                      .map(
                        column => {

                          const key =
                            typeof column ===
                              'string'
                              ? column
                              : column.key ||
                                column.name ||
                                column.field

                          return `
                            <td>
                              ${renderCell(
                                row?.[
                                  key
                                ]
                              )}
                            </td>
                          `
                        }
                      )
                      .join('')}

                  </tr>
                `
              )
              .join('')}

          </tbody>

        </table>

      </div>

      ${
        rows.length >
        100
          ? `
            <div class="result-table-note">
              Se muestran los primeros 100 de
              ${escapeHtml(
                String(
                  rows.length
                )
              )}
              registros.
            </div>
          `
          : ''
      }

    </div>
  `
}

// =======================================================
// BUSCADOR
// =======================================================

function bindResultTableSearch() {

  if (
    !answerCard
  ) {

    return
  }

  const search =
    answerCard
      .querySelector(
        '.result-table-search'
      )

  if (!search) {

    return
  }

  search
    .addEventListener(
      'input',
      () => {

        const query =
          search.value
            .trim()
            .toLowerCase()

        answerCard
          .querySelectorAll(
            '.premium-result-table tbody tr'
          )
          .forEach(
            row => {

              const haystack =
                row.dataset.search ||
                ''

              row.hidden =
                Boolean(
                  query
                ) &&
                !haystack.includes(
                  query
                )
            }
          )
      }
    )
}

// =======================================================
// CELDAS
// =======================================================

function renderCell(
  value
) {

  if (
    value ===
      null ||
    value ===
      undefined ||
    value ===
      ''
  ) {

    return `
      <span class="cell-empty">
        —
      </span>
    `
  }

  if (
    typeof value ===
    'boolean'
  ) {

    return `
      <span
        class="cell-status ${
          value
            ? 'positive'
            : 'neutral'
        }"
      >
        ${
          value
            ? 'Sí'
            : 'No'
        }
      </span>
    `
  }

  return escapeHtml(
    formatCellValue(
      value
    )
  )
}

function formatCellValue(
  value
) {

  if (
    value ===
      null ||
    value ===
      undefined
  ) {

    return ''
  }

  if (
    Array.isArray(
      value
    )
  ) {

    return value
      .map(
        formatCellValue
      )
      .filter(
        Boolean
      )
      .join(
        ', '
      )
  }

  if (
    typeof value ===
    'object'
  ) {

    return Object
      .values(
        value
      )
      .map(
        formatCellValue
      )
      .filter(
        Boolean
      )
      .join(
        ' · '
      )
  }

  return String(
    value
  )
}

function getColumnLabel(
  column
) {

  if (
    typeof column ===
    'string'
  ) {

    return humanizeKey(
      column
    )
  }

  if (
    column &&
    typeof column ===
      'object'
  ) {

    return (
      column.label ||
      column.title ||
      column.name ||
      column.key ||
      column.field ||
      ''
    )
  }

  return String(
    column ??
    ''
  )
}

// =======================================================
// V16 · DATA-FIRST ANALYTICS (sin dependencias nuevas)
// =======================================================

function normalizeMetricLabel(
  label
) {

  const source =
    cleanUserFacingText(
      String(label || '')
    )

  if (
    /personas?\s+con\s+n[oó]minas?\s+sin\s+leer/i
      .test(source)
  ) {
    return 'Nóminas sin leer'
  }

  if (
    /n[oó]minas?.*sin\s+leer/i
      .test(source)
  ) {
    return 'Nóminas sin leer'
  }

  return source
}

function isIndicatorRecord(
  row
) {

  if (
    !row ||
    typeof row !== 'object' ||
    Array.isArray(row)
  ) {
    return false
  }

  const keys =
    Object.keys(row)
      .map(
        key =>
          normalizeFieldKey(key)
      )

  const hasLabel =
    keys.some(
      key =>
        /^(indicador|label|nombre|metrica|metric|kpi|concepto|titulo|title)$/.test(key)
    )

  const hasValue =
    keys.some(
      key =>
        /^(valor|value|total|count|cantidad|numero|dato)$/.test(key)
    )

  return hasLabel && hasValue
}

function parseComparisonNumber(
  raw
) {

  const text =
    String(raw ?? '')
      .trim()
      .replace(',', '.')

  if (
    !text ||
    !/^-?\d+(?:\.\d+)?(?:\s*(?:%|d[ií]as?|horas?|h))?$/i.test(text)
  ) {
    return null
  }

  const match =
    text.match(/-?\d+(?:\.\d+)?/)

  if (!match) {
    return null
  }

  const value =
    Number(match[0])

  return Number.isFinite(value)
    ? value
    : null
}

function getComparisonIndicatorMatrixFromRows(
  rows
) {

  if (
    !Array.isArray(rows) ||
    rows.length < 2 ||
    !rows.every(
      row =>
        row &&
        typeof row === 'object' &&
        !Array.isArray(row)
    )
  ) {
    return null
  }

  const keys =
    [...new Set(
      rows.flatMap(
        row =>
          Object.keys(row)
      )
    )]

  const labelKey =
    keys.find(
      key =>
        /^(indicador|metrica|metric|kpi|concepto|titulo|title)$/i
          .test(
            normalizeFieldKey(key)
          )
    )

  if (!labelKey) {
    return null
  }

  const seriesKeys =
    keys
      .filter(
        key =>
          key !== labelKey &&
          !isTechnicalField(key)
      )
      .filter(
        key => {
          const numericValues =
            rows
              .map(
                row => {
                  return parseComparisonNumber(
                    row?.[key]
                  )
                }
              )
              .filter(value => value !== null)

          return numericValues.length >=
            Math.min(2, rows.length)
        }
      )

  if (seriesKeys.length < 2) {
    return null
  }

  return {
    labelKey,
    seriesKeys:
      seriesKeys.slice(0, 4),
    rows
  }
}

function getComparisonIndicatorMatrix(
  presentationOrData,
  explicitTable = null
) {

  const data =
    presentationOrData?.data ||
    presentationOrData ||
    {}

  const table =
    presentationOrData?.table ||
    explicitTable

  const candidates = [
    data?.turnos,
    data?.indicadores,
    data?.comparativa,
    table?.rows
  ]

  for (const rows of candidates) {
    const matrix =
      getComparisonIndicatorMatrixFromRows(
        rows
      )

    if (matrix) {
      return matrix
    }
  }

  return null
}

function isEmployee360Request(
  query
) {

  return /(?:ficha\s+(?:completa\s+)?360|360\s+(?:de\s+)?(?:empleado|empleada|persona|ficha)|employee\s*360|employee360)/i
    .test(
      String(query || '')
    )
}

function hasEmployee360DataShape(
  data
) {

  const root =
    data?.employee360 &&
    typeof data.employee360 === 'object'
      ? data.employee360
      : data

  return Boolean(
    root &&
    typeof root === 'object' &&
    (
      root.empleado ||
      root.persona ||
      root.datos_laborales ||
      root.turnos_inteligentes ||
      root.vacaciones_inteligentes ||
      root.saldo_vacaciones ||
      root.nominas ||
      root.documentos_firmados
    )
  )
}

function isOperationalIndicatorRows(
  rows
) {

  return Boolean(
    Array.isArray(rows) &&
    rows.length >= 2 &&
    rows.filter(isIndicatorRecord).length >=
      Math.min(2, rows.length)
  )
}

function readIndicatorRecord(
  row
) {

  const entries =
    Object.entries(row || {})

  const labelEntry =
    entries.find(
      ([key]) =>
        /^(indicador|label|nombre|metrica|metric|kpi|concepto|titulo|title)$/i
          .test(
            normalizeFieldKey(key)
          )
    )

  const valueEntry =
    entries.find(
      ([key]) =>
        /^(valor|value|total|count|cantidad|numero|dato)$/i
          .test(
            normalizeFieldKey(key)
          )
    )

  if (
    !labelEntry ||
    !valueEntry
  ) {
    return null
  }

  const rawValue =
    valueEntry[1]

  const numeric =
    Number(
      String(rawValue)
        .replace(',', '.')
        .replace(/[^0-9.-]/g, '')
    )

  return {
    label:
      normalizeMetricLabel(
        labelEntry[1]
      ),
    value:
      Number.isFinite(numeric)
        ? numeric
        : rawValue,
    rawValue
  }
}

function getOperationalIndicators(
  presentation
) {

  const candidates = [
    presentation?.data?.turnos,
    presentation?.data?.indicadores,
    presentation?.data?.kpis,
    presentation?.table?.rows
  ]

  for (
    const rows of candidates
  ) {

    if (
      !isOperationalIndicatorRows(rows)
    ) {
      continue
    }

    const normalized =
      rows
        .map(readIndicatorRecord)
        .filter(Boolean)

    if (normalized.length) {
      return normalized
    }
  }

  return []
}

function findOperationalMetric(
  indicators,
  pattern
) {

  return indicators.find(
    item =>
      pattern.test(
        item.label
      )
  )
}

function renderOperationalOverview(
  presentation
) {

  const indicators =
    getOperationalIndicators(
      presentation
    )

  if (!indicators.length) {
    return ''
  }

  const featuredPatterns = [
    /plantilla\s+activa/i,
    /trabajando\s+hoy/i,
    /de\s+baja\s+hoy|baja\s+hoy/i,
    /de\s+vacaciones\s+hoy|vacaciones\s+hoy/i
  ]

  const featured =
    featuredPatterns
      .map(
        pattern =>
          findOperationalMetric(
            indicators,
            pattern
          )
      )
      .filter(Boolean)

  const today =
    indicators.filter(
      item =>
        /trabajando\s+hoy|baja\s+hoy|vacaciones\s+hoy/i
          .test(item.label) &&
        Number.isFinite(
          Number(item.value)
        )
    )

  const featuredLabels =
    new Set(
      featured.map(
        item =>
          item.label
      )
    )

  const secondary =
    indicators.filter(
      item =>
        !featuredLabels.has(
          item.label
        )
    )

  const maxToday =
    Math.max(
      1,
      ...today.map(
        item =>
          Number(item.value) || 0
      )
    )

  return `
    <section class="v16-operational reveal-item">
      <div class="v151-section-title">
        <div>
          <span>RESUMEN OPERATIVO</span>
          <h3>Situación actual</h3>
        </div>
      </div>

      ${featured.length ? `
        <div class="v16-operational-kpis">
          ${featured.map(item => `
            <article>
              <strong>${escapeHtml(formatPresentationValue(item.value))}</strong>
              <span>${escapeHtml(item.label)}</span>
            </article>
          `).join('')}
        </div>
      ` : ''}

      ${today.length ? `
        <div class="v16-operational-bars">
          ${today.map(item => {
            const value = Number(item.value) || 0
            const width = Math.max(3, (value / maxToday) * 100)
            return `
              <div class="v16-op-row">
                <div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(formatPresentationValue(value))}</strong></div>
                <i><b style="width:${width}%"></b></i>
              </div>
            `
          }).join('')}
        </div>
      ` : ''}

      ${secondary.length ? `
        <div class="v16-secondary-kpis">
          ${secondary.slice(0, 8).map(item => `
            <article>
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(formatPresentationValue(item.value))}</strong>
            </article>
          `).join('')}
        </div>
      ` : ''}
    </section>
  `
}

function isComparisonPeopleMetric(
  label
) {

  const text =
    String(label || '')
      .toLowerCase()

  if (
    /horas?|saldo|d[ií]as?|n[oó]minas?|documentos?|edad|porcentaje|%/.test(text)
  ) {
    return false
  }

  return /plantilla|trabajando|descans|sin turno|baja|vacaciones|ausent|ett|permiso|asuntos propios/.test(text)
}

function renderComparisonPeopleBars(
  rows
) {

  const peopleRows =
    rows
      .filter(row =>
        isComparisonPeopleMetric(
          row.label
        ) &&
        row.values.some(item =>
          item.value !== null
        )
      )
      .slice(0, 7)

  if (peopleRows.length < 2) {
    return ''
  }

  return `
    <section class="v162-compare-chart">
      <header>
        <div>
          <span>GRÁFICA DE BARRAS</span>
          <h4>Personas por situación</h4>
        </div>
        <small>Comparación relativa por indicador</small>
      </header>
      <div class="v162-compare-bars">
        ${peopleRows.map(row => {
          const max = Math.max(
            1,
            ...row.values.map(item => Math.max(0, Number(item.value) || 0))
          )

          return `
            <article>
              <h5>${escapeHtml(row.label)}</h5>
              ${row.values.map((item, index) => {
                const value = Math.max(0, Number(item.value) || 0)
                const width = Math.max(value > 0 ? 3 : 0, (value / max) * 100)
                return `
                  <div class="v162-chart-series series-${index + 1}">
                    <div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(formatPresentationValue(item.raw ?? value))}</strong></div>
                    <i><b style="width:${width}%"></b></i>
                  </div>
                `
              }).join('')}
            </article>
          `
        }).join('')}
      </div>
    </section>
  `
}

function renderComparisonActivityDonuts(
  rows,
  series
) {

  const workforce =
    rows.find(row =>
      /plantilla(?:\s+activa)?/i.test(
        row.label
      )
    )

  const working =
    rows.find(row =>
      /trabajando(?:\s+hoy)?/i.test(
        row.label
      )
    )

  if (!workforce || !working) {
    return ''
  }

  const donuts =
    series
      .map((item, index) => {
        const workforceMetric = workforce.values.find(value => value.key === item.key)
        const workingMetric = working.values.find(value => value.key === item.key)
        const total = Number(workforceMetric?.value)
        const active = Number(workingMetric?.value)

        if (
          !Number.isFinite(total) ||
          total <= 0 ||
          !Number.isFinite(active)
        ) {
          return ''
        }

        const safeActive = Math.max(0, Math.min(total, active))
        const percent = Math.max(0, Math.min(100, (safeActive / total) * 100))
        const rest = Math.max(0, total - safeActive)
        const angle = percent * 3.6

        return `
          <article class="v162-donut-card series-${index + 1}">
            <div class="v162-donut-ring" style="--v162-angle:${angle}deg">
              <div><strong>${escapeHtml(percent.toLocaleString('es-ES', { maximumFractionDigits: 1 }))}%</strong><span>trabajando</span></div>
            </div>
            <div class="v162-donut-copy">
              <h5>${escapeHtml(item.label)}</h5>
              <p><strong>${escapeHtml(formatPresentationValue(safeActive))}</strong> trabajando · ${escapeHtml(formatPresentationValue(rest))} resto</p>
              <small>Plantilla ${escapeHtml(formatPresentationValue(total))}</small>
            </div>
          </article>
        `
      })
      .filter(Boolean)

  if (!donuts.length) {
    return ''
  }

  return `
    <section class="v162-activity-share">
      <header>
        <span>GRÁFICA DE DISTRIBUCIÓN</span>
        <h4>Actividad sobre plantilla</h4>
      </header>
      <div>${donuts.join('')}</div>
    </section>
  `
}

function renderComparisonIndicatorMatrix(
  presentation
) {

  const matrix =
    getComparisonIndicatorMatrix(
      presentation
    )

  if (!matrix) {
    return ''
  }

  const series =
    matrix.seriesKeys.map(
      key => ({
        key,
        label:
          normalizeMetricLabel(
            friendlyLabel(key) ||
            humanizeKey(key)
          )
      })
    )

  const rows =
    matrix.rows
      .slice(0, 14)
      .map(
        row => {
          const values =
            series.map(
              item => {
                const raw =
                  row?.[item.key]

                const number =
                  parseComparisonNumber(
                    raw
                  )

                return {
                  ...item,
                  raw,
                  value: number
                }
              }
            )

          return {
            label:
              normalizeMetricLabel(
                row?.[matrix.labelKey]
              ),
            values
          }
        }
      )
      .filter(
        row =>
          row.label &&
          row.values.some(
            item =>
              item.value !== null
          )
      )

  if (!rows.length) {
    return ''
  }

  return `
    <section class="v16-comparison-matrix reveal-item">
      <div class="v151-section-title">
        <div>
          <span>COMPARATIVA</span>
          <h3>Indicadores por departamento</h3>
        </div>
      </div>
      <div class="v16-comparison-legend">
        ${series.map(item => `<span>${escapeHtml(item.label)}</span>`).join('')}
      </div>
      <div class="v162-comparison-dashboard">
        ${renderComparisonPeopleBars(rows)}
        ${renderComparisonActivityDonuts(rows, series)}
      </div>
      <div class="v16-comparison-grid">
        ${rows.map(row => {
          const max = Math.max(
            1,
            ...row.values.map(
              item =>
                Math.max(0, Number(item.value) || 0)
            )
          )

          return `
            <article class="v16-comparison-row">
              <h4>${escapeHtml(row.label)}</h4>
              <div>
                ${row.values.map((item, index) => {
                  const value = Number(item.value) || 0
                  const width = Math.max(2, (Math.max(0, value) / max) * 100)
                  return `
                    <div class="v16-comparison-series series-${index + 1}">
                      <div class="v16-comparison-value">
                        <span>${escapeHtml(item.label)}</span>
                        <strong>${escapeHtml(formatPresentationValue(item.raw ?? value))}</strong>
                      </div>
                      <i><b style="width:${width}%"></b></i>
                    </div>
                  `
                }).join('')}
              </div>
            </article>
          `
        }).join('')}
      </div>
    </section>
  `
}

function parseMetricList(
  source
) {

  return String(source || '')
    .split(/\s*[·|]\s*/)
    .map(
      token => {
        const match =
          token
            .trim()
            .match(/^(.+?)\s+(-?\d+(?:[.,]\d+)?)(?:\s*([%a-záéíóúñ]+))?$/i)

        if (!match) {
          return null
        }

        return {
          label:
            normalizeMetricLabel(
              match[1]
                .replace(/_/g, ' ')
                .trim()
            ),
          value:
            Number(
              match[2]
                .replace(',', '.')
            ),
          unit:
            match[3] || ''
        }
      }
    )
    .filter(Boolean)
}

function extractStructuredAnalytics(
  presentation
) {

  const lines = []

  if (
    Array.isArray(
      presentation?.insights
    )
  ) {
    lines.push(
      ...presentation.insights.map(
        item =>
          typeof item === 'string'
            ? item
            : item?.text || item?.message || item?.title || ''
      )
    )
  }

  if (
    presentation?.answer
  ) {
    lines.push(
      ...String(presentation.answer)
        .replace(/\*\*/g, '')
        .split(/\n+/)
    )
  }

  const result = {
    jobs: [],
    today: [],
    vacations: [],
    context: [],
    consumed: new Set()
  }

  lines
    .map(
      line =>
        cleanUserFacingText(
          String(line || '')
            .replace(/^\s*[✦•*-]+\s*/, '')
            .trim()
        )
    )
    .filter(Boolean)
    .forEach(
      line => {
        let match = null

        if (
          (match = line.match(/^por\s+puesto\s*:\s*(.+)$/i))
        ) {
          result.jobs =
            parseMetricList(
              match[1]
            )
          result.consumed.add(line)
          return
        }

        if (
          (match = line.match(/^hoy\s*:\s*(.+)$/i))
        ) {
          result.today =
            parseMetricList(
              match[1]
            )
          result.consumed.add(line)
          return
        }

        if (
          (match = line.match(/^vacaciones\s*:\s*(.+)$/i))
        ) {
          result.vacations =
            parseMetricList(
              match[1]
            )
          result.consumed.add(line)
          return
        }

        if (
          !/^claves$|^lo\s+m[aá]s\s+relevante$/i
            .test(line) &&
          line.length <= 260
        ) {
          result.context.push(line)
        }
      }
    )

  return result
}

function renderHorizontalDataBars(
  title,
  data,
  limit = 12
) {

  if (!data.length) {
    return ''
  }

  const sorted =
    [...data]
      .sort(
        (a, b) =>
          Number(b.value) - Number(a.value)
      )
      .slice(0, limit)

  const max =
    Math.max(
      1,
      ...sorted.map(
        item =>
          Number(item.value) || 0
      )
    )

  return `
    <section class="v16-data-block reveal-item">
      <div class="v151-section-title">
        <div>
          <span>ANÁLISIS</span>
          <h3>${escapeHtml(title)}</h3>
        </div>
      </div>
      <div class="v16-data-bars">
        ${sorted.map(item => {
          const value = Number(item.value) || 0
          const width = Math.max(3, (value / max) * 100)
          return `
            <div class="v16-data-row">
              <div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(formatPresentationValue(value))}</strong></div>
              <i><b style="width:${width}%"></b></i>
            </div>
          `
        }).join('')}
      </div>
    </section>
  `
}

function renderTodayDistribution(
  data
) {

  if (!data.length) {
    return ''
  }

  const positive =
    data.filter(
      item =>
        Number(item.value) >= 0
    )

  const total =
    positive.reduce(
      (sum, item) =>
        sum + (Number(item.value) || 0),
      0
    )

  if (!total) {
    return ''
  }

  const palette = [
    '#284f86',
    '#c89a4a',
    '#df6847',
    '#6c2f2b',
    '#3f8d72',
    '#8d7b70'
  ]

  let angle = 0
  const stops = []

  positive.forEach(
    (item, index) => {
      const next =
        angle +
        (Number(item.value) || 0) /
          total * 360
      stops.push(
        `${palette[index % palette.length]} ${angle.toFixed(1)}deg ${next.toFixed(1)}deg`
      )
      angle = next
    }
  )

  return `
    <section class="v16-data-block v16-today reveal-item">
      <div class="v151-section-title">
        <div>
          <span>SITUACIÓN</span>
          <h3>Hoy</h3>
        </div>
      </div>
      <div class="v16-donut-layout">
        <div class="v16-donut" style="background:conic-gradient(${stops.join(',')})">
          <div><strong>${escapeHtml(String(total))}</strong><span>situaciones</span></div>
        </div>
        <div class="v16-donut-legend">
          ${positive.map((item, index) => `
            <div>
              <i style="background:${palette[index % palette.length]}"></i>
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(formatPresentationValue(item.value))}</strong>
            </div>
          `).join('')}
        </div>
      </div>
    </section>
  `
}

function renderVacationMetrics(
  data
) {

  if (!data.length) {
    return ''
  }

  return `
    <section class="v16-data-block reveal-item">
      <div class="v151-section-title">
        <div>
          <span>VACACIONES</span>
          <h3>Indicadores</h3>
        </div>
      </div>
      <div class="v16-vacation-kpis">
        ${data.map(item => `
          <article>
            <strong>${escapeHtml(formatPresentationValue(item.value))}${item.unit ? `<small> ${escapeHtml(item.unit)}</small>` : ''}</strong>
            <span>${escapeHtml(item.label)}</span>
          </article>
        `).join('')}
      </div>
    </section>
  `
}

function getAutoComparisonVisuals(
  presentation
) {

  const table =
    presentation?.table

  if (
    !table?.rows?.length ||
    table.rows.length < 2 ||
    !Array.isArray(table.columns)
  ) {
    return ''
  }

  const numericColumns =
    table.columns.filter(
      column => {
        const values =
          table.rows
            .slice(0, 20)
            .map(
              row =>
                Number(
                  String(row?.[column.key] ?? '')
                    .replace(',', '.')
                )
            )
            .filter(Number.isFinite)

        return values.length >=
          Math.min(2, table.rows.length)
      }
    )

  const labelColumn =
    table.columns.find(
      column =>
        !numericColumns.includes(column)
    ) || table.columns[0]

  if (!numericColumns.length) {
    return ''
  }

  return numericColumns
    .slice(0, 2)
    .map(
      column => {
        const data =
          table.rows
            .slice(0, 12)
            .map(
              (row, index) => ({
                label:
                  formatPresentationValue(
                    row?.[labelColumn.key],
                    labelColumn.key
                  ) || `Dato ${index + 1}`,
                value:
                  Number(
                    String(row?.[column.key] ?? 0)
                      .replace(',', '.')
                  ) || 0
              })
            )

        return renderHorizontalDataBars(
          column.label || 'Comparativa',
          data,
          12
        )
      }
    )
    .join('')
}

function renderDataFirstAnalytics(
  presentation
) {

  const structured =
    extractStructuredAnalytics(
      presentation
    )

  const hasStructured =
    structured.jobs.length ||
    structured.today.length ||
    structured.vacations.length

  const operational =
    renderOperationalOverview(
      presentation
    )

  const directComparison =
    renderComparisonIndicatorMatrix(
      presentation
    )

  const comparisonCharts =
    directComparison ||
    (
      ['comparison', 'department', 'analytics']
        .includes(presentation.type)
        ? getAutoComparisonVisuals(
            presentation
          )
        : ''
    )

  if (
    !hasStructured &&
    !operational &&
    !comparisonCharts
  ) {
    return ''
  }

  const context =
    structured.context
      .filter(
        text =>
          !/por\s+puesto\s*:|^hoy\s*:|^vacaciones\s*:/i
            .test(text)
      )
      .slice(0, 2)

  return `
    <div class="v16-data-first">
      ${context.length ? `<p class="v16-context-note reveal-item">${escapeHtml(context.join(' '))}</p>` : ''}
      ${operational}
      ${renderHorizontalDataBars('Distribución por puesto', structured.jobs)}
      ${renderTodayDistribution(structured.today)}
      ${renderVacationMetrics(structured.vacations)}
      ${comparisonCharts}
    </div>
  `
}

function compactAnalyticsAnswer(
  presentation
) {

  const source =
    String(
      presentation?.answer || ''
    )
      .replace(/\*\*/g, '')
      .replace(/(^|\n)\s*(CLAVES|Lo más relevante)\s*/gi, ' ')
      .replace(/(^|\n)\s*[✦•*-]\s*(Por puesto|Hoy|Vacaciones)\s*:[^\n]*/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  if (!source) {
    return ''
  }

  const sentences =
    source.match(/[^.!?]+[.!?]?/g) ||
    [source]

  const compact =
    sentences
      .slice(0, 2)
      .join(' ')
      .trim()

  return compact.length > 300
    ? `${compact.slice(0, 297).trim()}…`
    : compact
}

// =======================================================
// VISUALIZACIONES
// =======================================================

function renderVisualizations(
  visualizations
) {

  const supported =
    visualizations.filter(
      viz =>
        viz &&
        viz.type ===
          'bars' &&
        Array.isArray(
          viz.data
        )
    )

  if (
    !supported.length
  ) {

    return ''
  }

  return supported
    .slice(
      0,
      2
    )
    .map(
      viz => {

        const max =
          Math.max(
            1,
            ...viz.data.map(
              item =>
                Number(
                  item.value
                ) ||
                0
            )
          )

        return `
          <section class="result-chart-section">

            <div class="result-section-heading">

              <div>

                <span>
                  VISUALIZACIÓN
                </span>

                <h3>
                  ${escapeHtml(
                    viz.title ||
                    'Distribución'
                  )}
                </h3>

              </div>

            </div>

            <div class="result-bars">

              ${viz.data
                .slice(
                  0,
                  12
                )
                .map(
                  item => {

                    const value =
                      Number(
                        item.value
                      ) ||
                      0

                    const width =
                      Math.max(
                        3,
                        (
                          value /
                          max
                        ) *
                          100
                      )

                    return `
                      <div class="result-bar-row">

                        <div class="result-bar-label">

                          <span>
                            ${escapeHtml(
                              item.label ||
                              ''
                            )}
                          </span>

                          <strong>
                            ${escapeHtml(
                              String(
                                value
                              )
                            )}
                          </strong>

                        </div>

                        <div class="result-bar-track">

                          <i
                            style="width:${width}%"
                          ></i>

                        </div>

                      </div>
                    `
                  }
                )
                .join('')}

            </div>

          </section>
        `
      }
    )
    .join('')
}

// =======================================================
// CALIDAD
// =======================================================

function renderDataQuality(
  quality
) {

  const state =
    String(
      quality.estado ||
      quality.status ||
      'Información validada'
    )

  const warning =
    state
      .toLowerCase()
      .includes(
        'observ'
      )

  return `
    <div class="result-quality">

      <span class="result-meta-label">
        CALIDAD DEL DATO
      </span>

      <div
        class="quality-pill ${
          warning
            ? 'warning'
            : 'ok'
        }"
      >

        <span></span>

        ${escapeHtml(
          humanizeKey(
            state
          )
        )}

      </div>

    </div>
  `
}

// =======================================================
// RESUMEN FALLBACK
// =======================================================

function buildResultSummary(
  data
) {

  const ignored =
    new Set([
      'rows',
      'items',
      'table',
      'cards',
      'resultado',
      'empleados',
      'personas',
      'turnos',
      'selection_context',
      'auditoria',
      'alertas_calidad'
    ])

  const result =
    []

  for (
    const [
      key,
      value
    ]
    of Object.entries(
      data
    )
  ) {

    if (
      result.length >=
        6 ||
      ignored.has(
        key
      )
    ) {

      continue
    }

    if (
      value ===
        null ||
      value ===
        undefined ||
      typeof value ===
        'object'
    ) {

      continue
    }

    result.push({
      label:
        humanizeKey(
          key
        ),

      value:
        String(
          value
        )
    })
  }

  return result
}

// =======================================================
// AUXILIARES
// =======================================================

function hideBackendResult() {

  if (!answerCard) {

    return
  }

  answerCard.classList.remove(
    'staged'
  )

  answerCard.classList.add(
    'closing'
  )

  answerCard.classList.remove(
    'visible'
  )

  setTimeout(
    () => {

      answerCard
        ?.classList
        .remove(
          'closing'
        )
    },
    520
  )

  if (
    !queryInProgress &&
    miaIsAwayFromHome()
  ) {

    returnMiaHome({
      duration: 650
    })
  }
}

function humanizeKey(
  key
) {

  return String(
    key ||
    ''
  )
    .replaceAll(
      '_',
      ' '
    )
    .replace(
      /\b\w/g,
      char =>
        char.toUpperCase()
    )
}

function escapeHtml(
  value
) {

  return String(
    value ??
    ''
  )
    .replaceAll(
      '&',
      '&amp;'
    )
    .replaceAll(
      '<',
      '&lt;'
    )
    .replaceAll(
      '>',
      '&gt;'
    )
    .replaceAll(
      '"',
      '&quot;'
    )
    .replaceAll(
      "'",
      '&#039;'
    )
}

function absolutizeBackendUrl(
  url
) {

  if (
    !url ||
    url ===
      '#'
  ) {

    return '#'
  }

  if (
    /^https?:\/\//i
      .test(
        url
      )
  ) {

    return url
  }

  return (
    `${MIA_API_BASE}` +
    `${url.startsWith(
      '/'
    )
      ? ''
      : '/'
    }${url}`
  )
}

// =======================================================
// V15.1 · PRESENTATION ENGINE
// =======================================================

function cleanUserFacingText(
  value
) {

  return String(
    value ?? ''
  )
    .split(/\r?\n/)
    .filter(
      line =>
        !/^\s*(intent|selection_context|query_summary|handler|function|endpoint|debug|trace|payload)\s*[:=]/i
          .test(line)
    )
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function normalizeFieldKey(
  key
) {

  return String(
    key ?? ''
  )
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]/g, '')
    .toLowerCase()
}

function isTechnicalField(
  key,
  label = ''
) {

  const raw =
    `${key || ''} ${label || ''}`

  return TECHNICAL_FIELD_RE
    .test(raw)
}

function friendlyLabel(
  key,
  explicitLabel = ''
) {

  const explicit =
    cleanUserFacingText(
      explicitLabel
    )

  if (
    explicit &&
    !isTechnicalField(
      key,
      explicit
    )
  ) {

    return explicit
  }

  const normalized =
    normalizeFieldKey(
      key
    )

  if (
    FRIENDLY_LABELS[
      normalized
    ]
  ) {

    return FRIENDLY_LABELS[
      normalized
    ]
  }

  const human =
    String(
      key || ''
    )
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/[_\-.]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  if (
    !human ||
    isTechnicalField(
      key,
      human
    )
  ) {

    return ''
  }

  return human
    .replace(
      /\b\w/g,
      char =>
        char.toUpperCase()
    )
}

function isRenderablePrimitive(
  value
) {

  return (
    value !== null &&
    value !== undefined &&
    value !== '' &&
    (
      typeof value ===
        'string' ||
      typeof value ===
        'number' ||
      typeof value ===
        'boolean'
    )
  )
}

function extractSafePrimitiveEntries(
  object,
  limit = 24
) {

  if (
    !object ||
    typeof object !==
      'object' ||
    Array.isArray(object)
  ) {

    return []
  }

  const entries =
    []

  for (
    const [key, value]
    of Object.entries(
      object
    )
  ) {

    if (
      entries.length >=
        limit ||
      isTechnicalField(key) ||
      !isRenderablePrimitive(value)
    ) {

      continue
    }

    const label =
      friendlyLabel(key)

    if (!label) {

      continue
    }

    entries.push({
      key,
      label,
      value:
        formatPresentationValue(
          value,
          key
        )
    })
  }

  return entries
}

function formatPresentationValue(
  value,
  key = ''
) {

  if (
    value === null ||
    value === undefined ||
    value === ''
  ) {

    return '—'
  }

  if (
    typeof value ===
      'boolean'
  ) {

    return value
      ? 'Sí'
      : 'No'
  }

  if (
    typeof value ===
      'number'
  ) {

    return new Intl.NumberFormat(
      'es-ES',
      {
        maximumFractionDigits: 2
      }
    ).format(value)
  }

  const text =
    cleanUserFacingText(value)

  // ISO date → dd/mm/yyyy when it is genuinely a date.
  if (
    /fecha|date|inicio|fin|desde|hasta/i
      .test(key) &&
    /^\d{4}-\d{2}-\d{2}/
      .test(text)
  ) {

    const date =
      new Date(text)

    if (
      !Number.isNaN(
        date.getTime()
      )
    ) {

      return new Intl.DateTimeFormat(
        'es-ES'
      ).format(date)
    }
  }

  return text
}

function getRawTable(
  data
) {

  if (
    data?.table &&
    typeof data.table ===
      'object' &&
    Array.isArray(
      data.table.rows
    )
  ) {

    return data.table
  }

  const preferredArrays = [
    'resultado',
    'resultados',
    'personas',
    'empleados',
    'items',
    'rows',
    'solicitudes'
  ]

  for (
    const key
    of preferredArrays
  ) {

    if (
      Array.isArray(
        data?.[key]
      ) &&
      data[key].length &&
      data[key].every(
        item =>
          item &&
          typeof item ===
            'object' &&
          !Array.isArray(item)
      )
    ) {

      return {
        title:
          friendlyLabel(key) ||
          'Detalle',
        rows:
          data[key],
        columns: [],
        total:
          data[key].length,
        searchable:
          data[key].length > 6
      }
    }
  }

  for (
    const [key, value]
    of Object.entries(
      data || {}
    )
  ) {

    if (
      isTechnicalField(key) ||
      !Array.isArray(value) ||
      !value.length ||
      !value.every(
        item =>
          item &&
          typeof item ===
            'object' &&
          !Array.isArray(item)
      )
    ) {

      continue
    }

    return {
      title:
        friendlyLabel(key) ||
        'Detalle',
      rows: value,
      columns: [],
      total: value.length,
      searchable:
        value.length > 6
    }
  }

  return null
}

function normalizeFriendlyTable(
  rawTable
) {

  if (
    !rawTable ||
    !Array.isArray(
      rawTable.rows
    ) ||
    !rawTable.rows.length
  ) {

    return null
  }

  const rows =
    rawTable.rows

  let rawColumns =
    Array.isArray(
      rawTable.columns
    ) &&
    rawTable.columns.length
      ? rawTable.columns
      : Object.keys(
          rows[0] || {}
        )

  const columns =
    rawColumns
      .map(
        column => {

          if (
            typeof column ===
              'string'
          ) {

            const label =
              friendlyLabel(
                column
              )

            return label
              ? {
                  key: column,
                  label
                }
              : null
          }

          const key =
            column?.key ||
            column?.field ||
            column?.name ||
            column?.id ||
            ''

          const label =
            friendlyLabel(
              key,
              column?.label ||
              column?.title ||
              column?.name ||
              ''
            )

          return (
            key &&
            label
          )
            ? {
                key,
                label
              }
            : null
        }
      )
      .filter(Boolean)

  if (!columns.length) {

    return null
  }

  return {
    title:
      cleanUserFacingText(
        rawTable.title ||
        'Detalle'
      ),
    columns,
    rows,
    total:
      rawTable.total ??
      rows.length,
    searchable:
      Boolean(
        rawTable.searchable
      ) ||
      rows.length > 6
  }
}

function normalizeFriendlyCards(
  data
) {

  if (
    !Array.isArray(
      data?.cards
    )
  ) {

    return []
  }

  return data.cards
    .map(
      card => {

        const label =
          friendlyLabel(
            card?.key ||
            card?.name ||
            card?.label ||
            '',
            card?.label ||
            card?.title ||
            ''
          )

        const value =
          card?.value ??
          card?.total ??
          card?.count

        if (
          !label ||
          value === null ||
          value === undefined ||
          typeof value ===
            'object'
        ) {

          return null
        }

        return {
          label,
          value:
            formatPresentationValue(
              value,
              card?.key ||
              card?.label ||
              ''
            ),
          unit:
            cleanUserFacingText(
              card?.unit ||
              ''
            )
        }
      }
    )
    .filter(Boolean)
    .slice(0, 10)
}

function extractScalar(
  data,
  cards,
  answer
) {

  if (
    cards.length === 1
  ) {

    return cards[0]
  }

  const primitives =
    extractSafePrimitiveEntries(
      data,
      12
    )

  const preferred =
    primitives.find(
      item =>
        /^(total|cantidad|numero|empleados|personas|fecha|nombre|puesto|responsable|maximo|minimo|saldo)$/i
          .test(
            normalizeFieldKey(
              item.key
            )
          )
    )

  if (preferred) {

    return preferred
  }

  if (
    primitives.length === 1
  ) {

    return primitives[0]
  }

  const numberMatch =
    String(answer || '')
      .match(/\b\d+(?:[.,]\d+)?\b/)

  if (numberMatch) {

    return {
      label: 'Resultado',
      value:
        numberMatch[0],
      unit: ''
    }
  }

  return null
}

function findFirstValue(
  object,
  aliases
) {

  if (
    !object ||
    typeof object !==
      'object'
  ) {

    return ''
  }

  const normalizedAliases =
    aliases.map(
      normalizeFieldKey
    )

  for (
    const [key, value]
    of Object.entries(object)
  ) {

    if (
      normalizedAliases.includes(
        normalizeFieldKey(key)
      ) &&
      isRenderablePrimitive(value)
    ) {

      return formatPresentationValue(
        value,
        key
      )
    }
  }

  return ''
}

function guessPersonNameFromAnswer(
  answer
) {

  const text =
    cleanUserFacingText(
      String(answer || '')
        .replace(/\*\*/g, '')
    )

  const match =
    text.match(
      /^([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñüÜ'’-]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñüÜ'’-]+){1,4})\s+(?:es|trabaja|est[aá]|tiene)\b/
    )

  return match?.[1] || ''
}

function extractPersonAnswerDetails(
  answer
) {

  const text =
    cleanUserFacingText(
      String(answer || '')
        .replace(/\*\*/g, '')
    )

  if (!text) {
    return []
  }

  const details = []
  const seen = new Set()

  const add = (
    label,
    value
  ) => {
    const cleanValue =
      cleanUserFacingText(
        value
      )

    if (
      !label ||
      !cleanValue ||
      seen.has(label)
    ) {
      return
    }

    seen.add(label)
    details.push({
      key: label,
      label,
      value: cleanValue
    })
  }

  let match = null

  match =
    text.match(/\b(?:tiene\s+)?(\d{1,3})\s+a[nñ]os\b/i)
  if (match) {
    add('Edad', `${match[1]} años`)
  }

  match =
    text.match(/\b(?:email|correo(?:\s+electr[oó]nico)?)\s+(?:es\s+)?([^\s,;]+@[^\s,;]+)/i)
  if (match) {
    add('Correo electrónico', match[1])
  }

  match =
    text.match(/\b(?:tel[eé]fono|m[oó]vil)\s+(?:es\s+)?([+\d][\d\s-]{6,})/i)
  if (match) {
    add('Teléfono', match[1].trim().replace(/[.,;]+$/, ''))
  }

  match =
    text.match(/saldo\s+(?:actual\s+)?de\s+vacaciones\s+(?:es\s+)?(-?\d+(?:[.,]\d+)?)\s*d[ií]as?/i)
  if (match) {
    add('Saldo de vacaciones', `${match[1]} días`)
  }

  match =
    text.match(/(?:con|de)\s+(\d+(?:[.,]\d+)?)\s*d[ií]as?\s+en\s+total/i)
  if (match) {
    add('Vacaciones totales', `${match[1]} días`)
  }

  match =
    text.match(/\b(\d+)\s+n[oó]minas?\s+(?:no\s+le[ií]das?|sin\s+leer)/i)
  if (match) {
    add('Nóminas sin leer', match[1])
  }

  match =
    text.match(/\b(\d+)\s+documentos?\s+firmados?/i)
  if (match) {
    add('Documentos firmados', match[1])
  }

  if (/\bhoy\s+descansa\b/i.test(text)) {
    add('Situación hoy', 'Descanso')
  } else if (/\bhoy\s+(?:est[aá]\s+)?trabajando\b|\bhoy\s+trabaja\b/i.test(text)) {
    add('Situación hoy', 'Trabajando')
  } else if (/\bhoy\s+est[aá]\s+de\s+vacaciones\b/i.test(text)) {
    add('Situación hoy', 'Vacaciones')
  } else if (/\bhoy\s+est[aá]\s+de\s+baja\b/i.test(text)) {
    add('Situación hoy', 'Baja')
  }

  return details
}

function mergePersonDetailEntries(
  ...groups
) {

  const result = []
  const seen = new Set()

  groups
    .flat()
    .filter(Boolean)
    .forEach(
      item => {
        const label =
          cleanUserFacingText(
            item?.label ||
            item?.key ||
            ''
          )

        const value =
          cleanUserFacingText(
            item?.value ?? ''
          )

        const normalized =
          normalizeFieldKey(label)

        if (
          !label ||
          !value ||
          !normalized ||
          seen.has(normalized)
        ) {
          return
        }

        seen.add(normalized)
        result.push({
          ...item,
          label,
          value
        })
      }
    )

  return result.slice(0, 36)
}

function normalizeSources(
  sources
) {

  if (
    !Array.isArray(sources)
  ) {

    return []
  }

  return sources
    .map(
      source =>
        cleanUserFacingText(
          typeof source ===
            'string'
            ? source
            : source?.title ||
              source?.name ||
              source?.label ||
              ''
        )
    )
    .filter(
      source =>
        source &&
        !TECHNICAL_FIELD_RE
          .test(source)
    )
    .slice(0, 8)
}

function normalizeActions(
  actionsList
) {

  if (
    !Array.isArray(
      actionsList
    )
  ) {

    return []
  }

  return actionsList
    .map(
      action => {

        const label =
          cleanUserFacingText(
            action?.label ||
            action?.title ||
            ''
          )

        const url =
          action?.url ||
          action?.href ||
          ''

        if (
          !label ||
          !url
        ) {

          return null
        }

        return {
          label,
          url:
            absolutizeBackendUrl(
              url
            )
        }
      }
    )
    .filter(Boolean)
    .slice(0, 4)
}

function classifyPresentation(
  payload,
  data,
  cards,
  table,
  scalar
) {

  const intent =
    String(
      payload.intent ||
      ''
    )
      .toLowerCase()

  const answer =
    String(
      payload.answer ||
      ''
    )
      .toLowerCase()

  const haystack =
    `${intent} ${answer}`

  if (
    isEmployee360Payload(
      payload,
      data
    ) ||
    (
      isEmployee360Request(
        lastSubmittedQuery
      ) &&
      hasEmployee360DataShape(
        data
      )
    )
  ) {

    return 'employee360'
  }

  const comparisonMatrix =
    getComparisonIndicatorMatrix(
      data,
      table
    )

  if (comparisonMatrix) {
    return 'comparison'
  }

  const visualizations =
    Array.isArray(
      payload.visualizations
    )
      ? payload.visualizations
      : []

  const actionsList =
    Array.isArray(
      payload.actions
    )
      ? payload.actions
      : []

  if (
    actionsList.some(
      action =>
        /excel|pdf|document|descarg|export/i
          .test(
            `${action?.label || ''} ${action?.title || ''}`
          )
    ) &&
    !table &&
    !visualizations.length
  ) {

    return 'document'
  }

  if (
    /compar|versus|vs\b/i
      .test(haystack) ||
    data?.comparison ||
    data?.comparativa
  ) {

    return 'comparison'
  }

  const operationalRows =
    isOperationalIndicatorRows(
      data?.turnos
    ) ||
    isOperationalIndicatorRows(
      table?.rows
    )

  if (
    operationalRows
  ) {

    return 'analytics'
  }

  if (
    /turno|shift/i
      .test(haystack) ||
    Array.isArray(
      data?.turnos
    )
  ) {

    return 'shifts'
  }

  const candidateRow =
    table?.rows?.length === 1
      ? table.rows[0]
      : data

  const personName =
    findFirstValue(
      candidateRow,
      [
        'nombre',
        'displayName',
        'fullName',
        'nombreCompleto'
      ]
    ) ||
    guessPersonNameFromAnswer(
      payload.answer ||
      payload.response ||
      payload.message ||
      ''
    )

  const personRole =
    findFirstValue(
      candidateRow,
      [
        'puesto',
        'cargo',
        'jobTitle'
      ]
    )

  if (
    /emplead|persona|trabajador|ficha/i
      .test(
        `${haystack} ${lastSubmittedQuery}`
      ) &&
    personName &&
    (
      personRole ||
      table?.rows?.length === 1 ||
      /ficha/i.test(lastSubmittedQuery)
    )
  ) {

    return 'person'
  }

  if (
    /departament|analitica|análisis|analisis|estadistic/i
      .test(haystack) &&
    (
      cards.length >= 2 ||
      visualizations.length ||
      table
    )
  ) {

    return 'department'
  }

  if (
    visualizations.length ||
    cards.length >= 3
  ) {

    return 'analytics'
  }

  if (
    table?.rows?.length > 1
  ) {

    return 'list'
  }

  if (
    scalar &&
    !table
  ) {

    return 'scalar'
  }

  if (
    table?.rows?.length === 1 &&
    personName
  ) {

    return 'person'
  }

  return 'text'
}

function derivePresentationTitle(
  type,
  data,
  table,
  scalar
) {

  if (
    type === 'scalar' &&
    scalar?.label &&
    scalar.label !==
      'Resultado'
  ) {

    return scalar.label
  }

  if (
    type === 'employee360'
  ) {

    const employee360 =
      buildEmployee360Presentation(
        data
      )

    return (
      employee360?.hero?.title ||
      'Ficha completa de empleado'
    )
  }

  if (
    type === 'person'
  ) {

    const source =
      table?.rows?.[0] ||
      data

    return (
      findFirstValue(
        source,
        [
          'nombre',
          'displayName',
          'fullName',
          'nombreCompleto'
        ]
      ) ||
      'Ficha de empleado'
    )
  }

  if (
    type === 'department'
  ) {

    const department =
      findFirstValue(
        data,
        [
          'departamento',
          'department',
          'area'
        ]
      )

    return department
      ? `Departamento · ${department}`
      : 'Análisis del departamento'
  }

  if (
    type === 'shifts'
  ) {

    return 'Turnos'
  }

  if (
    type === 'comparison'
  ) {

    return 'Comparativa'
  }

  if (
    type === 'analytics'
  ) {

    return 'Análisis'
  }

  if (
    type === 'document'
  ) {

    return 'Documento preparado'
  }

  if (
    table?.title &&
    !TECHNICAL_FIELD_RE
      .test(table.title)
  ) {

    return cleanUserFacingText(
      table.title
    )
  }

  if (
    type === 'list'
  ) {

    return 'Resultados'
  }

  return 'Resultado'
}

function normalizePresentation(
  payload
) {

  const data =
    payload.data &&
    typeof payload.data ===
      'object'
      ? payload.data
      : {}

  const answer =
    cleanUserFacingText(
      payload.answer ||
      payload.response ||
      payload.message ||
      ''
    )

  const cards =
    normalizeFriendlyCards(
      data
    )

  const table =
    normalizeFriendlyTable(
      getRawTable(
        data
      )
    )

  const scalar =
    extractScalar(
      data,
      cards,
      answer
    )

  const type =
    classifyPresentation(
      payload,
      data,
      cards,
      table,
      scalar
    )

  const employee360Presentation =
    type === 'employee360'
      ? buildEmployee360Presentation(
          data
        )
      : null

  const rowForPerson =
    table?.rows?.length === 1
      ? table.rows[0]
      : data

  const derivedTitle =
    derivePresentationTitle(
      type,
      data,
      table,
      scalar
    )

  const title =
    type === 'person' &&
    derivedTitle === 'Ficha de empleado'
      ? (
          guessPersonNameFromAnswer(
            answer
          ) ||
          derivedTitle
        )
      : derivedTitle

  const personEntries =
    mergePersonDetailEntries(
      extractSafePrimitiveEntries(
        rowForPerson,
        30
      ),
      extractSafePrimitiveEntries(
        data,
        30
      ),
      extractPersonAnswerDetails(
        answer
      )
    )

  return {
    type,
    employee360Presentation,
    title,
    answer,
    data,
    cards,
    table,
    scalar,
    personEntries,
    safeEntries:
      extractSafePrimitiveEntries(
        data,
        20
      ),
    visualizations:
      Array.isArray(
        payload.visualizations
      )
        ? payload.visualizations
        : [],
    insights:
      Array.isArray(
        data.insights
      )
        ? data.insights
        : Array.isArray(
            payload.insights
          )
          ? payload.insights
          : [],
    quality:
      payload.data_quality ||
      data.data_quality ||
      data.calidad ||
      null,
    sources:
      normalizeSources(
        payload.sources
      ),
    actions:
      normalizeActions(
        payload.actions
      ),
    responseTime:
      lastQueryDurationMs
  }
}

function getPresentationAnimation(
  type
) {

  const preferred = {
    scalar:
      'mIA_YES',
    employee360:
      'mIA_POINT',
    person:
      'mIA_POINT',
    department:
      'mIA_POINT',
    analytics:
      'mIA_POINT',
    list:
      'mIA_POINT',
    shifts:
      'mIA_LOOK_AROUND',
    comparison:
      'mIA_AGREE',
    document:
      'mIA_CLAP',
    text:
      'mIA_TALK'
  }

  const selected =
    preferred[type] ||
    'mIA_POINT'

  return actions.has(selected)
    ? selected
    : actions.has(
        'mIA_POINT'
      )
      ? 'mIA_POINT'
      : 'mIA_YES'
}

async function preparePresentationPosition(
  type
) {

  if (
    !groundRoot ||
    isMobileViewport()
  ) {

    if (
      miaIsAwayFromHome()
    ) {

      await returnMiaHome({
        duration: 600,
        finishIdle: false
      })
    }

    return
  }

  const complex =
    [
      'employee360',
      'person',
      'department',
      'analytics',
      'list',
      'shifts',
      'comparison'
    ].includes(type)

  if (!complex) {

    return
  }

  // mIA deja espacio visual al resultado sin desaparecer de escena.
  await walkMiaTo(
    -0.52,
    0.18,
    {
      duration: 620,
      finishIdle: false
    }
  )
}

function renderPresentationHeader(
  presentation
) {

  return `
    <header class="v151-header reveal-item">
      <div>
        <div class="v151-eyebrow">
          <span></span>
          mIA
        </div>
        <h2>${escapeHtml(presentation.title)}</h2>
        ${
          presentation.responseTime > 0
            ? `<p class="v151-response-time">Respuesta en ${escapeHtml(formatResponseTime(presentation.responseTime))}</p>`
            : ''
        }
      </div>
      <button class="backend-result-close" type="button" aria-label="Cerrar resultado">×</button>
    </header>
  `
}

function formatResponseTime(
  ms
) {

  if (
    ms < 1000
  ) {

    return `${Math.max(1, Math.round(ms))} ms`
  }

  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0).replace('.', ',')} s`
}

function renderAnswerSummary(
  presentation
) {

  if (
    !presentation.answer ||
    presentation.type ===
      'scalar'
  ) {

    return ''
  }

  const dataFirst =
    ['analytics', 'department', 'comparison']
      .includes(
        presentation.type
      )

  const answer =
    dataFirst
      ? compactAnalyticsAnswer(
          presentation
        )
      : presentation.answer

  if (!answer) {
    return ''
  }

  return `
    <section class="v151-summary reveal-item${dataFirst ? ' v16-summary-compact' : ''}">
      <div class="v151-summary-mark">mIA</div>
      <p>${escapeHtml(answer)}</p>
    </section>
  `
}

function renderFriendlyKpis(
  cards
) {

  if (!cards.length) {

    return ''
  }

  return `
    <section class="v151-kpis reveal-item">
      ${cards.map(card => `
        <article class="v151-kpi">
          <span>${escapeHtml(card.label)}</span>
          <div>
            <strong>${escapeHtml(card.value)}</strong>
            ${card.unit ? `<small>${escapeHtml(card.unit)}</small>` : ''}
          </div>
        </article>
      `).join('')}
    </section>
  `
}

function renderScalarPresentation(
  presentation
) {

  const scalar =
    presentation.scalar ||
    {
      label:
        presentation.title,
      value:
        presentation.answer,
      unit: ''
    }

  return `
    <div class="v151-scalar-card">
      <button class="backend-result-close scalar-close" type="button" aria-label="Cerrar resultado">×</button>
      <div class="v151-scalar-kicker reveal-item">${escapeHtml(scalar.label || presentation.title)}</div>
      <div class="v151-scalar-value reveal-item">
        <strong>${escapeHtml(scalar.value)}</strong>
        ${scalar.unit ? `<span>${escapeHtml(scalar.unit)}</span>` : ''}
      </div>
      ${presentation.answer ? `<p class="v151-scalar-answer reveal-item">${escapeHtml(presentation.answer)}</p>` : ''}
    </div>
  `
}

function renderPersonPresentation(
  presentation
) {

  const entries =
    presentation.personEntries

  const name =
    entries.find(
      item =>
        item.label ===
          'Nombre'
    )?.value ||
    presentation.title

  const role =
    entries.find(
      item =>
        item.label ===
          'Puesto'
    )?.value ||
    ''

  const department =
    entries.find(
      item =>
        item.label ===
          'Departamento'
    )?.value ||
    ''

  const initials =
    String(name)
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(
        part =>
          part[0]
      )
      .join('')
      .toUpperCase()

  const hiddenLabels =
    new Set([
      'Nombre',
      'Puesto',
      'Departamento'
    ])

  const details =
    entries.filter(
      item =>
        !hiddenLabels.has(
          item.label
        )
    )

  return `
    ${renderPresentationHeader(presentation)}
    <section class="v151-person-hero reveal-item">
      <div class="v151-person-avatar">${escapeHtml(initials || 'mIA')}</div>
      <div class="v151-person-heading">
        <h3>${escapeHtml(name)}</h3>
        ${role ? `<p>${escapeHtml(role)}</p>` : ''}
        ${department ? `<span>${escapeHtml(department)}</span>` : ''}
      </div>
    </section>
    ${renderAnswerSummary(presentation)}
    ${details.length ? `
      <section class="v151-info-grid reveal-item">
        ${details.map(item => `
          <article>
            <span>${escapeHtml(item.label)}</span>
            <strong>${escapeHtml(item.value)}</strong>
          </article>
        `).join('')}
      </section>
    ` : ''}
    ${renderFriendlyKpis(presentation.cards)}
    ${renderFriendlyVisualizations(presentation.visualizations)}
    ${renderInsights(presentation.insights)}
    ${renderCollapsedFriendlyTable(presentation.table)}
    ${renderFriendlyQuality(presentation.quality)}
    ${renderSourcesAndActions(presentation)}
  `
}

function renderFriendlyTable(
  table
) {

  if (!table) {

    return ''
  }

  const rows =
    table.rows.slice(
      0,
      100
    )

  return `
    <section class="v151-table-section reveal-item">
      <div class="v151-section-title">
        <div>
          <span>DETALLE</span>
          <h3>${escapeHtml(table.title || 'Resultados')}</h3>
        </div>
        <strong>${escapeHtml(String(table.total ?? table.rows.length))} ${Number(table.total ?? table.rows.length) === 1 ? 'registro' : 'registros'}</strong>
      </div>
      <div class="premium-table-wrap">
        ${table.searchable ? `
          <div class="result-table-tools">
            <div class="result-table-search-shell">
              <span>⌕</span>
              <input class="result-table-search" type="search" placeholder="Buscar en los resultados..." />
            </div>
          </div>
        ` : ''}
        <div class="result-table-scroll">
          <table class="premium-result-table">
            <thead>
              <tr>${table.columns.map(column => `<th>${escapeHtml(column.label)}</th>`).join('')}</tr>
            </thead>
            <tbody>
              ${rows.map((row, rowIndex) => {
                const searchText = table.columns.map(column => formatPresentationValue(row?.[column.key], column.key)).join(' ').toLowerCase()
                return `<tr data-result-row="${rowIndex}" data-search="${escapeHtml(searchText)}">${table.columns.map(column => `<td>${escapeHtml(formatPresentationValue(row?.[column.key], column.key))}</td>`).join('')}</tr>`
              }).join('')}
            </tbody>
          </table>
        </div>
        <div class="v151-mobile-list">
          ${rows.map((row, rowIndex) => {
            const searchText = table.columns.map(column => formatPresentationValue(row?.[column.key], column.key)).join(' ').toLowerCase()
            return `<article class="v151-mobile-row" data-result-row="${rowIndex}" data-search="${escapeHtml(searchText)}">${table.columns.map(column => `<div><span>${escapeHtml(column.label)}</span><strong>${escapeHtml(formatPresentationValue(row?.[column.key], column.key))}</strong></div>`).join('')}</article>`
          }).join('')}
        </div>
      </div>
      ${table.rows.length > 100 ? `<p class="result-table-note">Se muestran los primeros 100 de ${escapeHtml(String(table.rows.length))} registros.</p>` : ''}
    </section>
  `
}

function renderFriendlyVisualizations(
  visualizations
) {

  if (
    !Array.isArray(
      visualizations
    ) ||
    !visualizations.length
  ) {

    return ''
  }

  const sections =
    []

  for (
    const viz
    of visualizations.slice(0, 3)
  ) {

    const data =
      Array.isArray(viz?.data)
        ? viz.data
        : []

    if (!data.length) {

      continue
    }

    const values =
      data.map(
        item =>
          Number(
            item?.value ??
            item?.total ??
            item?.count ??
            0
          ) || 0
      )

    const max =
      Math.max(
        1,
        ...values
      )

    sections.push(`
      <section class="v151-chart reveal-item">
        <div class="v151-section-title">
          <div>
            <span>VISUALIZACIÓN</span>
            <h3>${escapeHtml(cleanUserFacingText(viz?.title || 'Distribución'))}</h3>
          </div>
        </div>
        <div class="v151-bars">
          ${data.slice(0, 12).map((item, index) => {
            const label = cleanUserFacingText(item?.label || item?.name || `Dato ${index + 1}`)
            const value = values[index]
            const width = Math.max(3, (value / max) * 100)
            return `<div class="v151-bar"><div><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatPresentationValue(value))}</strong></div><i><b style="width:${width}%"></b></i></div>`
          }).join('')}
        </div>
      </section>
    `)
  }

  return sections.join('')
}

function renderInsights(
  insights
) {

  if (
    !Array.isArray(insights) ||
    !insights.length
  ) {

    return ''
  }

  const clean =
    insights
      .map(
        insight =>
          cleanUserFacingText(
            typeof insight ===
              'string'
              ? insight
              : insight?.text ||
                insight?.message ||
                insight?.title ||
                ''
          )
      )
      .filter(Boolean)
      .slice(0, 6)

  if (!clean.length) {

    return ''
  }

  return `
    <section class="v151-insights reveal-item">
      <div class="v151-section-title"><div><span>CLAVES</span><h3>Lo más relevante</h3></div></div>
      <div class="v151-insight-list">
        ${clean.map(text => `<div><span>✦</span><p>${escapeHtml(text)}</p></div>`).join('')}
      </div>
    </section>
  `
}

function renderFriendlyQuality(
  quality
) {

  if (
    !quality
  ) {

    return ''
  }

  const entries =
    typeof quality ===
      'object'
      ? extractSafePrimitiveEntries(
          quality,
          8
        )
      : []

  const text =
    typeof quality ===
      'string'
      ? cleanUserFacingText(
          quality
        )
      : ''

  if (
    !entries.length &&
    !text
  ) {

    return ''
  }

  return `
    <details class="v151-quality reveal-item">
      <summary>Calidad del dato</summary>
      ${text ? `<p>${escapeHtml(text)}</p>` : ''}
      ${entries.length ? `<div>${entries.map(item => `<span><b>${escapeHtml(item.label)}:</b> ${escapeHtml(item.value)}</span>`).join('')}</div>` : ''}
    </details>
  `
}

function renderSourcesAndActions(
  presentation
) {

  const sources =
    presentation.sources

  const actionsList =
    presentation.actions

  if (
    !sources.length &&
    !actionsList.length
  ) {

    return ''
  }

  return `
    <footer class="v151-footer reveal-item">
      ${sources.length ? `
        <details class="v151-sources">
          <summary>Fuentes consultadas</summary>
          <div>${sources.map(source => `<span>${escapeHtml(source)}</span>`).join('')}</div>
        </details>
      ` : '<span></span>'}
      ${actionsList.length ? `
        <div class="v151-actions">
          ${actionsList.map((action, index) => `<a class="${index === 0 ? 'primary' : ''}" href="${escapeHtml(action.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(action.label)}</a>`).join('')}
        </div>
      ` : ''}
    </footer>
  `
}

function renderPresentationExtras(
  presentation
) {

  return `
    ${renderFriendlyKpis(presentation.cards)}
    ${renderFriendlyVisualizations(presentation.visualizations)}
    ${renderInsights(presentation.insights)}
    ${renderFriendlyTable(presentation.table)}
    ${renderFriendlyQuality(presentation.quality)}
    ${renderSourcesAndActions(presentation)}
  `
}

function renderShiftPresentation(
  presentation
) {

  const shifts =
    Array.isArray(
      presentation.data?.turnos
    )
      ? presentation.data.turnos
      : presentation.table?.rows ||
        []

  const cards =
    shifts
      .slice(0, 24)
      .map(
        shift => {

          const entries =
            extractSafePrimitiveEntries(
              shift,
              10
            )

          const title =
            entries.find(
              item =>
                item.label === 'Nombre'
            )?.value ||
            entries.find(
              item =>
                item.label === 'Departamento'
            )?.value ||
            'Turno'

          return `
            <article class="v151-shift-card">
              <h4>${escapeHtml(title)}</h4>
              ${entries.filter(item => item.value !== title).map(item => `<div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></div>`).join('')}
            </article>
          `
        }
      )
      .join('')

  return `
    ${renderPresentationHeader(presentation)}
    ${renderAnswerSummary(presentation)}
    ${renderFriendlyKpis(presentation.cards)}
    ${cards ? `<section class="v151-shifts reveal-item">${cards}</section>` : renderFriendlyTable(presentation.table)}
    ${renderFriendlyVisualizations(presentation.visualizations)}
    ${renderInsights(presentation.insights)}
    ${renderFriendlyQuality(presentation.quality)}
    ${renderSourcesAndActions(presentation)}
  `
}

function renderCollapsedFriendlyTable(
  table
) {

  if (!table) {
    return ''
  }

  return `
    <details class="v16-raw-detail reveal-item">
      <summary>Ver datos completos</summary>
      ${renderFriendlyTable(table)}
    </details>
  `
}

function renderStandardPresentation(
  presentation
) {

  const dataFirst =
    renderDataFirstAnalytics(
      presentation
    )

  const showRawInsights =
    !dataFirst

  return `
    ${renderPresentationHeader(presentation)}
    ${renderAnswerSummary(presentation)}
    ${dataFirst}
    ${dataFirst ? '' : renderFriendlyKpis(presentation.cards)}
    ${dataFirst ? '' : renderFriendlyVisualizations(presentation.visualizations)}
    ${showRawInsights ? renderInsights(presentation.insights) : ''}
    ${dataFirst ? renderCollapsedFriendlyTable(presentation.table) : renderFriendlyTable(presentation.table)}
    ${!presentation.table && presentation.safeEntries.length ? `
      <section class="v151-info-grid reveal-item">
        ${presentation.safeEntries.map(item => `<article><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></article>`).join('')}
      </section>
    ` : ''}
    ${renderFriendlyQuality(presentation.quality)}
    ${renderSourcesAndActions(presentation)}
  `
}

function showBackendResultV151(
  presentation
) {

  ensureBackendResultCard()

  answerCard.className =
    `mia-backend-result presentation-v151 presentation-${presentation.type}`

  if (
    presentation.type ===
      'scalar'
  ) {

    answerCard.innerHTML =
      renderScalarPresentation(
        presentation
      )

  } else if (
    presentation.type ===
      'employee360'
  ) {

    answerCard.innerHTML =
      renderEmployee360PresentationHtml(
        presentation.employee360Presentation,
        presentation.data,
        presentation.answer
      )

  } else if (
    presentation.type ===
      'person'
  ) {

    answerCard.innerHTML =
      `<div class="v151-shell">${renderPersonPresentation(presentation)}</div>`

  } else if (
    presentation.type ===
      'shifts'
  ) {

    answerCard.innerHTML =
      `<div class="v151-shell">${renderShiftPresentation(presentation)}</div>`

  } else {

    answerCard.innerHTML =
      `<div class="v151-shell">${renderStandardPresentation(presentation)}</div>`
  }

  answerCard
    .querySelector(
      '.backend-result-close'
    )
    ?.addEventListener(
      'click',
      hideBackendResult
    )

  answerCard
    .querySelectorAll(
      '[data-mia-prompt]'
    )
    .forEach(
      button => {
        button.addEventListener(
          'click',
          event => {
            event.preventDefault()
            event.stopPropagation()

            const prompt =
              button.dataset.miaPrompt ||
              ''

            if (!prompt) {
              return
            }

            if (queryInProgress) {
              pendingQuickAction =
                prompt

              button.classList.add(
                'is-queued'
              )

              button.setAttribute(
                'aria-busy',
                'true'
              )

              setLiveStatus(
                'En cuanto termine esta respuesta te muestro ese detalle.'
              )

              return
            }

            submitQuery(
              prompt,
              'action'
            )
          }
        )
      }
    )

  bindFriendlyResultSearch()

  requestAnimationFrame(
    () => {

      answerCard.classList.add(
        'visible'
      )

      requestAnimationFrame(
        () => {

          answerCard.classList.add(
            'staged'
          )
        }
      )
    }
  )
}

function bindFriendlyResultSearch() {

  const search =
    answerCard?.querySelector(
      '.result-table-search'
    )

  if (!search) {

    return
  }

  search.addEventListener(
    'input',
    () => {

      const query =
        search.value
          .trim()
          .toLowerCase()

      answerCard
        .querySelectorAll(
          '[data-result-row]'
        )
        .forEach(
          row => {

            const haystack =
              row.dataset.search ||
              ''

            row.hidden =
              Boolean(query) &&
              !haystack.includes(
                query
              )
          }
        )
    }
  )
}

// =======================================================
// CARGAR MODELO
// =======================================================

const loader =
  new GLTFLoader()

loader.load(

  '/models/mIA_WEB.glb',

  gltf => {

    mia =
      gltf.scene

    groundRoot =
      new THREE.Group()

    groundRoot.name =
      'mIA_GroundRoot'

    groundRoot.position.set(
      MIA_HOME.x,
      0,
      MIA_HOME.z
    )

    groundRoot.add(
      mia
    )

    scene.add(
      groundRoot
    )

    mia.traverse(
      object => {

        if (
          object.isMesh ||
          object.isSkinnedMesh
        ) {

          object.castShadow =
            true

          object.receiveShadow =
            true
        }
      }
    )

    // ---------------------------------------------------
    // ESCALA
    // ---------------------------------------------------

    let box =
      new THREE.Box3()
        .setFromObject(
          mia
        )

    const size =
      box.getSize(
        new THREE.Vector3()
      )

    const desiredHeight =
      MIA_MODEL_HEIGHT

    mia.scale.setScalar(
      desiredHeight /
      size.y
    )

    mia.updateMatrixWorld(
      true
    )

    // ---------------------------------------------------
    // CENTRAR
    // ---------------------------------------------------

    box =
      new THREE.Box3()
        .setFromObject(
          mia
        )

    const center =
      box.getCenter(
        new THREE.Vector3()
      )

    mia.position.x -=
      center.x

    mia.position.z -=
      center.z

    mia.position.y -=
      box.min.y

    mia.position.y +=
      MIA_GROUND_OFFSET

    mia.updateMatrixWorld(
      true
    )

    contactShadow.position.x =
      groundRoot.position.x

    contactShadow.position.z =
      groundRoot.position.z +
      0.03

    // Nunca se mueve verticalmente el root: los pies se calibran
    // una vez con MIA_GROUND_OFFSET y después mIA camina por X/Z.
    groundRoot.position.y =
      0

    console.log(
      'MIA_GROUND_OFFSET:',
      MIA_GROUND_OFFSET
    )

    // ---------------------------------------------------
    // MIXER
    // ---------------------------------------------------

    mixer =
      new THREE.AnimationMixer(
        mia
      )

    gltf.animations.forEach(
      originalClip => {

        const cleanClip =
          sanitizeClip(
            originalClip
          )

        cleanClip.name =
          originalClip.name

        actions.set(
          cleanClip.name,

          mixer.clipAction(
            cleanClip
          )
        )

        const upperBodyClip =
          buildUpperBodyClip(
            cleanClip
          )

        if (upperBodyClip) {
          upperBodyActions.set(
            cleanClip.name,
            mixer.clipAction(
              upperBodyClip
            )
          )
        }
      }
    )

    console.log(
      'Animaciones:',
      [
        ...actions.keys()
      ]
    )

    // ---------------------------------------------------
    // AVATAR CONTROLLER · V1
    // ---------------------------------------------------

    avatarController =
      new AvatarController({
        hasAnimation:
          name =>
            actions.has(name),

        playAnimation:
          (
            name,
            options
          ) =>
            playAnimation(
              name,
              options
            ),

        playGesture:
          (
            name,
            options
          ) =>
            playUpperBodyGesture(
              name,
              options
            ),

        stopGesture:
          fade =>
            stopUpperBodyGesture(
              fade
            ),

        enableIdleMicroGestures:
          true,

        enableSpeakingGestures:
          true
      })

    // ---------------------------------------------------
    // ARRANQUE
    // ---------------------------------------------------

    goIdle(
      0
    )

    createDevelopmentPanel()

    createInteractionUI()

    applyResponsive3DProfile()
    updateVisualViewportVars()

    setTimeout(
      () => {

        runStartupGreeting()
      },
      650
    )
  },

  undefined,

  error => {

    console.error(
      'Error cargando mIA:',
      error
    )
  }
)

// =======================================================
// PANEL DESARROLLO
// =======================================================

function createDevelopmentPanel() {

  const panel =
    document.createElement(
      'div'
    )

  panel.className =
    'dev-panel'

  const title =
    document.createElement(
      'div'
    )

  title.className =
    'dev-title'

  title.textContent =
    'mIA · Desarrollo'

  panel.appendChild(
    title
  )

  const stateLabel =
    document.createElement(
      'div'
    )

  stateLabel.className =
    'mia-state'

  stateLabel.textContent =
    miaState

  panel.appendChild(
    stateLabel
  )

  const select =
    document.createElement(
      'select'
    )

  Array
    .from(
      actions.keys()
    )
    .sort()
    .forEach(
      name => {

        const option =
          document.createElement(
            'option'
          )

        option.value =
          name

        option.textContent =
          name.replace(
            'mIA_',
            ''
          )

        select.appendChild(
          option
        )
      }
    )

  select.value =
    'mIA_IDLE'

  select
    .addEventListener(
      'change',
      () => {

        if (
          queryInProgress
        ) {

          return
        }

        playAnimation(
          select.value,
          {
            fade:
              0.45
          }
        )
      }
    )

  panel.appendChild(
    select
  )

  const idleButton =
    document.createElement(
      'button'
    )

  idleButton.className =
    'mia-idle-button'

  idleButton.textContent =
    'Volver a IDLE'

  idleButton
    .addEventListener(
      'click',
      () => {

        if (
          !queryInProgress
        ) {

          goIdle()
        }
      }
    )

  panel.appendChild(
    idleButton
  )

  document.body.appendChild(
    panel
  )
}

// =======================================================
// RESPONSIVE · V15.1
// =======================================================

window.addEventListener(
  'resize',
  () => {

    applyResponsive3DProfile()
    updateVisualViewportVars()
  }
)

if (
  window.visualViewport
) {

  window.visualViewport.addEventListener(
    'resize',
    updateVisualViewportVars
  )

  window.visualViewport.addEventListener(
    'scroll',
    updateVisualViewportVars
  )
}

// =======================================================
// LOOP
// =======================================================

function animate() {

  requestAnimationFrame(
    animate
  )

  const now =
    performance.now()

  const delta =
    clock.getDelta()

  if (mixer) {

    mixer.update(
      delta
    )
  }

  updateGroundMotion(
    now
  )

  updateCameraTracking()

  updateContactShadow()

  renderer.render(
    scene,
    camera
  )
}

animate()