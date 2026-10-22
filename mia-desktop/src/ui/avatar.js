import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const bridge = window.miaDesktop;
const canvas = document.getElementById('scene');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(33, 1, .01, 150);
camera.position.set(0, 0, 5.0);
const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
scene.add(new THREE.HemisphereLight(0xffffff, 0x91849d, 2.1));
const mainLight = new THREE.DirectionalLight(0xffffff, 2.6);
mainLight.position.set(3, 5, 7); scene.add(mainLight);
const fill = new THREE.DirectionalLight(0xd7b6a9, .8);
fill.position.set(-4, 2, 3); scene.add(fill);
const clock = new THREE.Clock();
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let character = null, mixer = null, clips = [], currentAction = null;
let ready = false, visible = true, idleFps = 15, lastFrame = 0, lastPass = null;
let drag = null;
let currentOneShot = null;
let subtleMovement = true;
let lastInteraction = Date.now();
let avatarMode = 'IDLE';
let ambling = false;
let idleWalkCircle = true, idleBored = true;
let greetingAudio = null, greetingUrl = null;
let welcomeRunning = false;
let ceremonyId=null,greetingTimer=null;
function resize() {
  const width = window.innerWidth, height = window.innerHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / height; camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();
function playAnimation(hint = 'IDLE') {
  if (!mixer || !clips.length) return;
  const aliases = { LISTEN: 'IDLE_BREATHING', THINK: 'THINK', TALK: 'TALK', GREET: 'GREET', JOY_GREET:'SEQ_BIENVENIDA', FAREWELL:'SEQ_DESPEDIDA', BORED:'SEQ_ESPERA', WALK_CIRCLE:'WALK_CIRCLE' };
  const target = aliases[hint] || hint;
  const chosen = clips.find(c => c.name.toUpperCase() === `MIA_${target}`) ||
    clips.find(c => c.name.toUpperCase().includes(target)) || clips.find(c => c.name === 'mIA_IDLE') || clips[0];
  const next = mixer.clipAction(chosen);
  const continuous = ['IDLE','LISTEN','TALK','THINK'].includes(hint);
  if (currentAction === next) return;
  next.reset().setEffectiveWeight(1).fadeIn(.3).play();
  next.setLoop(continuous ? THREE.LoopRepeat : THREE.LoopOnce, continuous ? Infinity : 1);
  next.clampWhenFinished = !continuous;
  currentOneShot = continuous ? null : next;
  if (currentAction) currentAction.fadeOut(.3);
  currentAction = next;
}
async function loadModel() {
  ready = false;
  if (character) { scene.remove(character); character = null; }
  if (mixer) { mixer.stopAllAction(); mixer = null; }
  clips = []; currentAction = null;
  try {
    const gltf = await new GLTFLoader().loadAsync(`mia://assets/avatar.glb?revision=${Date.now()}`);
    character = gltf.scene;
    // Normalización no destructiva del modelo, conservando esqueleto y clips.
    const bounds = new THREE.Box3().setFromObject(character);
    if (bounds.isEmpty()) throw Error('Modelo sin geometría.');
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const scale = 2.9 / Math.max(size.y, .001);
    character.scale.setScalar(scale);
    character.position.set(-center.x * scale, -center.y * scale, -center.z * scale);
    character.traverse(obj => { if (obj.isMesh) { obj.frustumCulled = false; } });
    scene.add(character);
    clips = gltf.animations || [];
    if (clips.length) {
      mixer = new THREE.AnimationMixer(character);
      mixer.addEventListener('finished', ev => { if (currentOneShot === ev.action) { currentOneShot = null; playAnimation('IDLE'); } });
      playAnimation('IDLE');
    }
    ready = true;
    bridge.avatarReady();
  } catch (error) {
    console.warn('Avatar GLB aún no disponible:', error.message);
    bridge.reportRendererError('AVATAR_GLTF_LOAD_FAILED');
    ready = false;
  }
}
function inCharacterCoords(x, y) {
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 ||
      x >= window.innerWidth || y >= window.innerHeight) return false;
  const nx = x / window.innerWidth, ny = y / window.innerHeight;
  // A usable central grab area: skinned GLB meshes and animated limbs may not
  // always intersect a ray despite being visibly drawn under the cursor.
  const centralGrab = ny > .15 && ny < .94 && Math.abs(nx - .5) < (.12 + .20 * ny);
  if (!ready || !character) return centralGrab;
  mouse.x = nx * 2 - 1;
  mouse.y = -(ny * 2 - 1);
  raycaster.setFromCamera(mouse, camera);
  return centralGrab || raycaster.intersectObject(character, true).length > 0;
}
function inCharacter(ev) { return inCharacterCoords(ev.clientX, ev.clientY); }

function setPassthrough(pass) {
  if (drag) pass = false;
  if (pass === lastPass) return;
  lastPass = pass;
  bridge.setPassthrough(pass);
  canvas.style.cursor = pass ? 'default' : 'grab';
}
// Authoritative recovery path: the main process can see the global cursor
// even while Electron has setIgnoreMouseEvents(true). Do not rely only on
// forwarded pointermove events from an ignored transparent window.
bridge.onAvatarCursor(pos => {
  if (drag) return;
  setPassthrough(!inCharacterCoords(pos?.x, pos?.y));
});
// Pointer capture + movimiento desde el proceso principal. No depende de
// recibir mousemove desde una ventana que está siendo desplazada.
window.addEventListener('pointermove', ev => {
  lastInteraction=Date.now();
  if(drag){
    drag.moved = drag.moved || Math.abs(ev.screenX-drag.x)>7 || Math.abs(ev.screenY-drag.y)>7;
    return;
  }
  setPassthrough(!inCharacter(ev));
});
window.addEventListener('pointerdown', ev => {
  if(ev.button!==0 || !inCharacter(ev)) return;
  drag={id:ev.pointerId, x:ev.screenX, y:ev.screenY, moved:false};
  try { canvas.setPointerCapture?.(ev.pointerId); } catch { /* Window-level pointer events still work. */ }
  setPassthrough(false);
  canvas.style.cursor = 'grabbing';
  bridge.startDrag();
});
function releaseDrag(ev){
  if(!drag || (ev && ev.pointerId!==drag.id))return;
  const moved=drag.moved || (ev && Math.abs(ev.screenX-drag.x)+Math.abs(ev.screenY-drag.y)>7);
  drag=null;bridge.stopDrag();
  canvas.style.cursor = 'grab';
  if(!moved){playAnimation('GREET');bridge.openBubble();}
}
window.addEventListener('pointerup',releaseDrag);
window.addEventListener('pointercancel', () => {drag=null;bridge.stopDrag();canvas.style.cursor='grab';});
// Window moves or companion focus may fire blur during an active drag.
// The pointerup / pointercancel events, not focus changes, own drag release.
// Escape never minimizes the avatar; use the explicit minimize action.
window.addEventListener('contextmenu', ev => {
  if (inCharacter(ev)) { ev.preventDefault(); bridge.avatarContextMenu(); }
});
bridge.onAvatarAction(action => {
  if (typeof action === 'string') { avatarMode = action; lastInteraction = Date.now(); playAnimation(action); }
});
bridge.onConfigChanged(cfg => { subtleMovement = !!cfg?.subtleMovement; idleWalkCircle=!!cfg?.idleWalkCircle;idleBored=!!cfg?.idleBored; });
bridge.getState().then(state => { subtleMovement = !!state?.config?.subtleMovement; idleWalkCircle=!!state?.config?.idleWalkCircle; idleBored=!!state?.config?.idleBored; }).catch(()=>{});
// Gestos de reposo reales: mIA_WALK_CIRCLE y mIA_SEQ_ESPERA (espera aburrida).
// Nunca se interrumpe al usuario mientras habla o escribe.
setInterval(() => {
  if(!subtleMovement || !visible || document.hidden || !ready || drag || welcomeRunning || avatarMode!=='IDLE' || currentOneShot)return;
  if(Date.now()-lastInteraction<16000)return;
  const moves=['LOOK_AROUND','STRETCH_NECK','IDLE_BREATHING'];
  if(idleBored && clips.some(c=>c.name==='mIA_SEQ_ESPERA'))moves.push('BORED');
  if(idleWalkCircle && clips.some(c=>c.name==='mIA_WALK_CIRCLE'))moves.push('WALK_CIRCLE');
  const action=moves[Math.floor(Math.random()*moves.length)];
  if(action==='IDLE_BREATHING')playAnimation('IDLE_BREATHING');
  else playAnimation(action);
},28000);
function stopGreeting(){
  if(greetingTimer){clearTimeout(greetingTimer);greetingTimer=null;}
  if(ceremonyId!==null){bridge.ceremonyFinished(ceremonyId);ceremonyId=null;}
  bridge.playbackState(false);
  if(greetingAudio){greetingAudio.pause();greetingAudio=null;}
  if(greetingUrl){URL.revokeObjectURL(greetingUrl);greetingUrl=null;}
  welcomeRunning=false;avatarMode='IDLE';playAnimation('IDLE');
}
async function greetAtStartup(payload){
  if(!ready){if(Number.isInteger(payload?.id))bridge.ceremonyFinished(payload.id);return;}
  if(welcomeRunning)stopGreeting();
  welcomeRunning=true;
  ceremonyId=Number.isInteger(payload?.id)?payload.id:null;
  playAnimation(payload?.animation||'GREET');
  if(!payload?.voiceEnabled){greetingTimer=setTimeout(stopGreeting,2600);return;}
  let response;
  try {response=await bridge.speak(payload.text);}catch{response=null;}
  if(!welcomeRunning)return;
  if(response?.audioBase64){
    try {
      const raw=atob(response.audioBase64),bytes=new Uint8Array(raw.length);
      for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
      greetingUrl=URL.createObjectURL(new Blob([bytes],{type:response.mimeType||'audio/mpeg'}));
      greetingAudio=new Audio(greetingUrl);
      greetingAudio.addEventListener('ended',stopGreeting,{once:true});
      greetingAudio.addEventListener('error',stopGreeting,{once:true});
      bridge.playbackState(true);await greetingAudio.play();return;
    }catch{
      if(greetingAudio){greetingAudio.pause();greetingAudio=null;}
      if(greetingUrl){URL.revokeObjectURL(greetingUrl);greetingUrl=null;}
      bridge.playbackState(false);
    }
  }
  if(payload.fallbackEnabled && 'speechSynthesis' in window){
    const utterance=new SpeechSynthesisUtterance(payload.text);
    utterance.lang='es-ES';utterance.rate=.97;
    utterance.onstart=()=>bridge.playbackState(true);utterance.onend=stopGreeting;utterance.onerror=stopGreeting;
    speechSynthesis.speak(utterance);
  }else greetingTimer=setTimeout(stopGreeting,2600);
}
bridge.onStartupGreeting(greetAtStartup);
bridge.onAvatarCeremony(greetAtStartup);
bridge.onModelChanged(loadModel);
bridge.onAvatarVisibility(value => { visible = Boolean(value);if(!visible){stopGreeting();if('speechSynthesis' in window)speechSynthesis.cancel();} });
function render(time) {
  requestAnimationFrame(render);
  if (!visible || document.hidden) { clock.getDelta(); return; }
  if (time - lastFrame < 1000 / idleFps) return;
  const delta = Math.min(clock.getDelta(), .12);
  lastFrame = time;
  if (mixer) mixer.update(delta);
  renderer.render(scene, camera);
}
requestAnimationFrame(render);
loadModel();

window.addEventListener('error',()=>window.miaDesktop.reportRendererError('WINDOW_ERROR'));
window.addEventListener('unhandledrejection',()=>window.miaDesktop.reportRendererError('UNHANDLED_REJECTION'));
