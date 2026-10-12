import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MiaWelcomeVoiceV45 } from '../src/core/welcome-voice-v45.js';
import { MiaBehaviorV4 } from '../src/core/behavior-v4.js';
const code = (relative) => readFileSync(new URL('../' + relative, import.meta.url), 'utf8');

function stubUrls() {
  globalThis.URL.createObjectURL = () => 'blob:mia-test';
  globalThis.URL.revokeObjectURL = () => {};
}

test('welcome audio is prepared once, autoplay starts on GLB readiness, replay does not refetch', async () => {
  stubUrls();
  let fetchCount = 0;
  let tries = 0;
  let blocked = 0;
  let starts = 0;
  const audio = {
    pause() {}, currentTime: 0,
    addEventListener() {},
    play() {
      tries += 1;
      if (tries === 1) return Promise.reject(Object.assign(new Error('Autoplay blocked'), { name: 'NotAllowedError' }));
      return Promise.resolve();
    },
  };
  const voice = new MiaWelcomeVoiceV45({
    fetchImpl: async () => {
      fetchCount += 1;
      return { ok: true, blob: async () => new Blob(['audio']) };
    },
    audioFactory: () => audio,
    onBlocked: () => { blocked += 1; },
    onStart: () => { starts += 1; },
  });
  assert.equal((await voice.prepare('Hola Enrique')).status, 'ready');
  assert.equal((await voice.start('Hola Enrique')).status, 'blocked');
  assert.equal(fetchCount, 1, 'preloaded audio reused during startup');
  assert.equal(blocked, 1);
  assert.equal((await voice.replay('Hola Enrique')).status, 'playing');
  assert.equal(fetchCount, 1, 'manual click must not refetch');
  assert.equal(tries, 2);
  assert.equal(starts, 1);
  voice.dispose();
});

test('voice endpoint error provides manual browser synthesis fallback', async () => {
  stubUrls();
  let count = 0; let spoken = '';
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  globalThis.speechSynthesis = {
    getVoices: () => [{lang:'es-ES'}],
    cancel() {},
    speak(u) { spoken = u.text; count++; u.onstart?.(); },
  };
  const voice = new MiaWelcomeVoiceV45({
    fetchImpl: async () => ({ ok:false, status:503 }),
  });
  assert.equal((await voice.start('Hola Enrique')).status, 'unavailable');
  assert.equal((await voice.replay('Hola Enrique')).status, 'browser-speaking');
  assert.equal(spoken, 'Hola Enrique');
  assert.equal(count, 1);
  voice.dispose();
  delete globalThis.SpeechSynthesisUtterance;
  delete globalThis.speechSynthesis;
});

test('stale TTS is cancelled after query starts', async () => {
  let cancelled = false;
  const voice = new MiaWelcomeVoiceV45({fetchImpl:(_uri,{signal})=>new Promise((resolve,reject)=>{
    signal.addEventListener('abort', () => { cancelled = true; reject(new Error('aborted')); });
  })});
  const prepare = voice.prepare('Hola Enrique');
  voice.cancel();
  assert.equal((await prepare).status, 'cancelled');
  assert.equal(cancelled, true);
});

test('the animation library is unchanged; greeting uses safe runtime subclip and early crossfade', () => {
  const scene = code('src/core/scene.js');
  const b = code('src/core/behavior-v4.js');
  const main = code('src/worlds/3d/main.js');
  assert.match(scene, /mIA_SEQ_BIENVENIDA_SAFE/);
  assert.match(scene, /AnimationUtils\.subclip/);
  assert.match(scene, /sourceGreeting\.duration - 2\.1/);
  assert.match(b, /\['mIA_SEQ_BIENVENIDA_SAFE', 'mIA_SEQ_BIENVENIDA', 'mIA_GREET'\]/);
  assert.match(main, /duration \* 1000 - 650/);
  assert.match(main, /!\['mIA_IDLE_SAFE', 'mIA_SEQ_BIENVENIDA_SAFE'\]/);
});

test('welcoming behavior uses new clip and keeps idle transition', () => {
  const played=[];
  globalThis.window={setTimeout,clearTimeout,matchMedia:()=>({matches:false})};
  const actions = new Map(['mIA_SEQ_BIENVENIDA_SAFE','mIA_IDLE_SAFE'].map(x=>[x,true]));
  const scene = {actions,play: (name,options)=>played.push(name),stopGesture(){},stopWaitOrbit(){},clipDuration:()=>5,isFrontFacingClip:()=>true};
  const b = new MiaBehaviorV4({scene});
  b.enter('greeting');
  assert.equal(played.at(-1), 'mIA_SEQ_BIENVENIDA_SAFE');
  b.enter('idle');
  assert.equal(played.at(-1),'mIA_IDLE_SAFE');
  b.destroy();
});

test('face corrections affect only neck and head AFTER mixer, never model root', () => {
  const scene = code('src/core/scene.js');
  assert.match(scene, /smartrig:Neck/);
  assert.match(scene, /smartrig:Head/);
  assert.match(scene, /mixer\?\.update\(delta\);\s*this\._adjustFacePose\(\);/);
  assert.match(scene, /if \(\/WALK\|RUN\|TURN/);
  assert.match(scene, /bone\.quaternion\.slerp\(this\._faceDesired, opt\.strength\)/);
  assert.doesNotMatch(scene.slice(scene.indexOf('_adjustFacePose() {'),scene.indexOf('clipDuration(name)')), /model\.rotation|model\.position|_groundRoot\.rotation/);
  const main=code('src/worlds/3d/main.js');
  assert.match(main, /facePitch/);
  assert.match(main, /faceYaw/);
});

test('3D prepares welcome audio and gates voice behind real click; hologram stays autoplay', () => {
  const main=code('src/worlds/3d/main.js');
  const html=code('src/worlds/3d/index.html');
  assert.match(main,/welcomeVoice\.prepare\(initialWelcomeText\)/);
  assert.match(main,/welcomeVoice\.replay\(greeting\)/);
  assert.match(main,/welcomeAutostart\?\.blocked\(\)/);
  assert.doesNotMatch(html,/id="miaWelcomeReplay"/);
  const hologram = code('src/worlds/hologram/main.js');
  assert.match(hologram, /welcomeVoice\.prepare\(welcomeMessage\)/);
  assert.match(hologram, /welcomeAutostart\.start\(welcomeMessage\)/);
});

test('microphone tri-state and tabular presentation are retained', () => {
  const main=code('src/worlds/3d/main.js');
  assert.match(main,/voice\?\.cycle\(\)/);
  assert.match(main,/enhancePremiumTables\(conversation, \{ pageSize: 20/);
  assert.match(main,/render2DTableExtras/);
});
