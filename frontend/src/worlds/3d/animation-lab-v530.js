/**
 * mIA 3D - LAB temporal de animaciones (sin editar GLB, rig o mixers).
 * Instalar con installMiaAnimationLab(scene). No hace nada hasta activar vista previa.
 */
import * as THREE from 'three';
import './animation-lab-v530.css';

export function installMiaAnimationLab(scene, { root = document.body } = {}) {
  if (!scene || !root || document.querySelector('#miaAnimationLabV530')) return null;
  const panel = document.createElement('aside');
  panel.id = 'miaAnimationLabV530';
  panel.className = 'mia-animation-lab';
  panel.setAttribute('aria-label','Laboratorio temporal de animaciones 3D');
  panel.innerHTML = `
    <div class="mia-animation-lab__header"><div><span class="mia-animation-lab__tag">3D · TEMPORAL</span><strong>Animaciones mIA</strong></div><button type="button" data-lab-hide title="Ocultar laboratorio" aria-label="Ocultar laboratorio">×</button></div>
    <label for="miaLabClip">Clip a visualizar</label>
    <select id="miaLabClip" disabled><option>Cargando animaciones…</option></select>
    <div class="mia-animation-lab__controls"><button type="button" data-lab-play disabled>▶ Reproducir</button><button type="button" data-lab-release disabled>↺ Volver a mIA</button></div>
    <div class="mia-animation-lab__settings"><label for="miaLabSpeed">Velocidad <output id="miaLabSpeedValue">1,00×</output></label><input id="miaLabSpeed" type="range" min="0.25" max="2" step="0.05" value="1"><label class="mia-animation-lab__check"><input id="miaLabLoop" type="checkbox" checked> Repetir</label></div>
    <p class="mia-animation-lab__meta" id="miaLabInfo">Solo inspección visual, sin cambiar el rig.</p>
  `;
  root.appendChild(panel);
  const $ = (selector) => panel.querySelector(selector);
  const select = $('#miaLabClip');
  const playButton = $('[data-lab-play]');
  const releaseButton = $('[data-lab-release]');
  const speed = $('#miaLabSpeed');
  const speedValue = $('#miaLabSpeedValue');
  const loop = $('#miaLabLoop');
  const info = $('#miaLabInfo');
  const nativePlay = typeof scene.play === 'function' ? scene.play : null;
  const nativeGesture = typeof scene.playGesture === 'function' ? scene.playGesture : null;
  let locked = false;
  let ownPlay = false;
  let timer = null;
  let count = 0;
  let released = false;
  let action = null;
  const names = () => [...(scene.actions?.keys?.() || [])].filter(Boolean);
  function guardMethod(method, raw) {
    return function(...args) {
      if (locked && !ownPlay) return undefined;
      return raw.apply(scene,args);
    };
  }
  if (nativePlay) scene.play = guardMethod('play', nativePlay);
  if (nativeGesture) scene.playGesture = guardMethod('gesture', nativeGesture);
  function fill() {
    if (released) return;
    const clips = names();
    if (!clips.length) return;
    if (clips.length === count) return;
    count = clips.length;
    const previous = select.value;
    select.replaceChildren();
    const groups = new Map();
    for (const name of clips.sort((a,b)=>a.localeCompare(b,'es'))) {
      const kind = /IDLE|LOOK|THINK|TALK|TYPING/i.test(name) ? 'Reposo y conversación'
        : /WALK|STRUT|TURN|RUN|DANCE/i.test(name) ? 'Movimiento'
        : /SAFE|SEQ_/i.test(name) ? 'Secuencias y seguridad' : 'Gestos y expresiones';
      if (!groups.has(kind)) groups.set(kind, []);
      groups.get(kind).push(name);
    }
    for (const [kind, group] of groups) {
      const optgroup = document.createElement('optgroup'); optgroup.label = kind;
      for (const name of group) {
        const opt = document.createElement('option'); opt.value = opt.textContent = name;
        optgroup.appendChild(opt);
      }
      select.appendChild(optgroup);
    }
    select.disabled = false;
    playButton.disabled = false;
    select.value = clips.includes(previous) ? previous : (clips.find(n=>n==='mIA_IDLE') || clips[0]);
    updateInfo();
  }
  const updateInfo = () => {
    const clip = select.value;
    const duration = typeof scene.clipDuration === 'function' ? Number(scene.clipDuration(clip)) : NaN;
    const seconds = Number.isFinite(duration) ? ` · ${duration.toFixed(2).replace('.',',')} s` : '';
    info.textContent = `${count} clips disponibles${seconds}. El modo de vista previa suspende los gestos automáticos.`;
  };
  const syncAction = () => {
    if (!action || !locked) return;
    action.timeScale = Number(speed.value) || 1;
    action.setLoop(loop.checked ? THREE.LoopRepeat : THREE.LoopOnce, loop.checked ? Infinity : 1);
    action.clampWhenFinished = !loop.checked;
  };
  const release = () => {
    if (!locked) return;
    locked = false;
    releaseButton.disabled = true;
    playButton.textContent = '▶ Reproducir';
    if (action) action.paused = false;
    action = null;
    try { scene.stopGesture?.(0.12); } catch { /* optional */ }
    if (nativePlay) {
      ownPlay = true;
      try { nativePlay.call(scene, scene.actions?.has('mIA_IDLE_SAFE') ? 'mIA_IDLE_SAFE' : 'mIA_IDLE'); }
      finally { ownPlay = false; }
    }
    updateInfo();
  };
  function play() {
    if (!scene.actions?.has(select.value)) return;
    if (!locked) {
      locked = true;
      releaseButton.disabled = false;
      try { scene.stopGesture?.(0.10); } catch { /* optional */ }
    }
    ownPlay = true;
    try {
      nativePlay?.call(scene, select.value);
      action = scene.actions.get(select.value);
      if (action) {
        // Reiniciar clip incluso cuando scene.play evita reproducir el actual.
        action.reset(); action.enabled = true; action.paused = false;
        action.play();
        syncAction();
      }
      playButton.textContent = '↻ Reiniciar clip';
    } finally { ownPlay = false; }
    updateInfo();
  }
  select.addEventListener('change', () => { updateInfo(); play(); });
  playButton.addEventListener('click', play);
  releaseButton.addEventListener('click', release);
  speed.addEventListener('input', () => { speedValue.textContent = `${Number(speed.value).toFixed(2).replace('.',',')}×`; syncAction(); });
  loop.addEventListener('change', syncAction);
  $('[data-lab-hide]').addEventListener('click', () => { release(); panel.hidden = true; });
  timer = setInterval(fill, 650);
  fill();
  const dispose = () => {
    if (released) return;
    release();
    released = true;
    clearInterval(timer);
    if (nativePlay) scene.play = nativePlay;
    if (nativeGesture) scene.playGesture = nativeGesture;
    panel.remove();
  };
  window.addEventListener('pagehide', dispose, {once:true});
  return { refresh: fill, release, dispose, get active() { return locked; } };
}
