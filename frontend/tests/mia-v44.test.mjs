import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MiaVoiceV4 } from '../src/core/voice-v4.js';
import { MiaBehaviorV4 } from '../src/core/behavior-v4.js';

let instances, queued, timerID, fakeDocument;
class FakeRecognition {
  constructor() { instances.push(this); this.starts = 0; this.aborts = 0; }
  start() { this.starts++; this.onstart?.(); }
  abort() { this.aborts++; this.onend?.(); }
  result(value, final = true) {
    const row = Object.assign([{ transcript: value }], { isFinal: final });
    this.onresult?.({ resultIndex: 0, results: [row] });
    this.onend?.();
  }
  error(code) { this.onerror?.({ error: code }); this.onend?.(); }
}
function setup() {
  instances = [];
  queued = new Map();
  timerID = 0;
  fakeDocument = {
    hidden: false, listeners: new Map(),
    addEventListener(name, fn) { this.listeners.set(name, fn); },
    removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name); },
    visibility(visible) {
      this.hidden = !visible;
      this.listeners.get('visibilitychange')?.();
    },
  };
  globalThis.document = fakeDocument;
  globalThis.window = {
    SpeechRecognition: FakeRecognition,
    setTimeout(fn, ms) { const id = ++timerID; queued.set(id, { fn, ms }); return id; },
    clearTimeout(id) { queued.delete(id); },
    matchMedia: () => ({ matches: false }),
  };
  function flush() {
    const tasks = [...queued.values()];
    queued.clear();
    for (const item of tasks) item.fn();
  }
  return { flush, instances };
}

test('mic off initially: no recognizer start, no permission checks', () => {
  setup();
  const m = new MiaVoiceV4();
  assert.equal(m.mode, 'off');
  assert.equal(m.listening, false);
  assert.equal(instances[0].starts, 0);
  assert.equal(m.startIfPreviouslyAllowed(), false);
  assert.equal(instances[0].starts, 0);
  m.destroy();
});

test('three clicks: off -> once -> continuous -> off', () => {
  const { flush } = setup();
  const seen = [];
  const m = new MiaVoiceV4({ onModeChange: mode => seen.push(mode) });
  assert.equal(m.cycle(), 'once');
  assert.equal(instances[0].starts, 1);
  assert.equal(m.cycle(), 'continuous');
  assert.equal(instances[0].starts, 1); // no duplicate recognition.start
  assert.equal(m.cycle(), 'off');
  flush();
  assert.equal(instances[0].starts, 1); // no auto restart after off
  assert.equal(m.mode, 'off');
  assert.ok(seen.includes('once') && seen.includes('continuous') && seen.includes('off'));
  m.destroy();
});

test('once captures only one phrase, pauses and preserves second-click stage', () => {
  const { flush } = setup();
  const phrases = [];
  const m = new MiaVoiceV4({ onFinal: text => phrases.push(text) });
  m.cycle();
  instances[0].result('¿Qué turnos hay hoy?');
  assert.deepEqual(phrases, ['¿Qué turnos hay hoy?']);
  assert.equal(m.mode, 'once');
  assert.equal(m.listening, false);
  assert.equal(m.suspended, true);
  flush();
  assert.equal(instances[0].starts, 1);
  // El segundo clic conserva el ciclo aun despues de terminar la frase.
  assert.equal(m.cycle(), 'continuous');
  m.destroy();
});

test('continuous persists across answer, suspends during TTS and resumes afterwards', () => {
  const { flush } = setup();
  let count = 0;
  const m = new MiaVoiceV4({ onFinal: () => count++ });
  m.cycle();
  m.cycle();
  instances[0].result('Enséñame las estadísticas');
  assert.equal(count, 1);
  assert.equal(m.mode, 'continuous');
  assert.equal(m.suspended, true);
  flush();
  assert.equal(instances[0].starts, 1, 'capture must not restart during answer');
  m.resume();
  flush();
  assert.equal(instances[0].starts, 2, 'capture restarts after answer');
  assert.equal(m.mode, 'continuous');
  m.cycle();
  flush();
  assert.equal(m.mode, 'off');
  assert.equal(instances[0].starts, 2);
  m.destroy();
});

test('continuous resumes after no speech, but once does not', () => {
  const { flush } = setup();
  const m = new MiaVoiceV4();
  m.cycle();
  m.cycle();
  instances[0].error('no-speech');
  assert.equal(m.mode, 'continuous');
  flush();
  assert.equal(instances[0].starts, 2);
  m.stop();
  m.cycle();
  instances[0].error('no-speech');
  assert.equal(m.mode, 'once');
  assert.equal(m.listening, false);
  assert.equal(m.suspended, true);
  m.destroy();
});

test('microphone is never live on a hidden tab and resumes only opted-in continuous mode', () => {
  const { flush } = setup();
  const m = new MiaVoiceV4();
  m.cycle(); m.cycle();
  fakeDocument.visibility(false);
  assert.equal(m.mode, 'continuous');
  assert.equal(m.listening, false);
  flush();
  assert.equal(instances[0].starts, 1);
  fakeDocument.visibility(true);
  flush();
  assert.equal(instances[0].starts, 2);
  m.destroy();
  assert.equal(fakeDocument.listeners.size, 0);
});

test('permission failure turns off the mic; never loops the permission prompt', () => {
  const { flush } = setup();
  const errors = [];
  const m = new MiaVoiceV4({ onError: message => errors.push(message) });
  m.cycle();m.cycle();
  instances[0].error('not-allowed');
  flush();
  assert.equal(m.mode, 'off');
  assert.deepEqual(errors, ['not-allowed']);
  assert.equal(instances[0].starts, 1);
  m.destroy();
});

test('waiting: bored at >=35 s, circular walk at >=65 s, then return smoothly', () => {
  setup();
  const played = [], movements = [];
  const actions = ['mIA_IDLE_SAFE', 'mIA_THINK', 'mIA_SEQ_CONSULTANDO_DATOS',
    'mIA_TYPING', 'mIA_SEQ_TRABAJANDO', 'mIA_IDLE_SAD',
    'mIA_SEQ_ESPERA', 'mIA_WALK_CIRCLE'];
  const scene = {
    actions: new Map(actions.map(name => [name, true])),
    play: name => played.push(name), clipDuration: name => name === 'mIA_WALK_CIRCLE' ? 12.53 : 4,
    isFrontFacingClip: () => true,
    stopGesture: () => {},
    startWaitOrbit: sec => movements.push(['start', sec]),
    stopWaitOrbit: () => movements.push(['stop']),
  };
  const originalNow = Date.now;
  let now = 100000;
  Date.now = () => now;
  try {
    const behavior = new MiaBehaviorV4({ scene, mode: '3d' });
    behavior.enter('thinking');
    assert.ok(played.at(-1).startsWith('mIA_'));
    now += 36000;
    behavior._runCycle('thinking');
    assert.equal(played.at(-1), 'mIA_IDLE_SAD');
    now += 31000;
    behavior._runCycle('thinking');
    assert.equal(played.at(-1), 'mIA_WALK_CIRCLE');
    assert.equal(movements.at(-1)[0], 'start');
    behavior.enter('presenting');
    assert.equal(movements.at(-1)[0], 'stop');
    behavior.destroy();
  } finally { Date.now = originalNow; }
});

test('hologram can show boredom, but not orbital physical movement', () => {
  setup();
  const played = [];
  const actions = new Map(['mIA_THINK','mIA_IDLE_SAD','mIA_WALK_CIRCLE','mIA_IDLE_SAFE'].map(n=>[n,true]));
  const scene = {
    actions, play: n=>played.push(n), clipDuration:()=>5, stopGesture:()=>{},
    stopWaitOrbit:()=>{}, startWaitOrbit:()=>{throw new Error('HG must stay centered')},
  };
  const was = Date.now;
  let now = 100000;
  Date.now = () => now;
  try {
    const b = new MiaBehaviorV4({ scene, mode:'hologram' });
    b.enter('thinking');
    now += 70000;
    b._runCycle('thinking');
    assert.ok(!played.includes('mIA_WALK_CIRCLE'));
    assert.ok(played.includes('mIA_IDLE_SAD'));
    b.destroy();
  } finally { Date.now = was; }
});

test('UI retains loading, premium 3D presentation, and two modes indicators', () => {
  const read = name => readFileSync(new URL(`../${name}`,import.meta.url),'utf8');
  const main3d=read('src/worlds/3d/main.js');
  const mainHg=read('src/worlds/hologram/main.js');
  const style=read('src/worlds/3d/v4-white.css');
  assert.match(main3d,/new MiaBootLoader/);
  assert.match(main3d,/enhancePremiumTables\(conversation, \{ pageSize: 20/);
  assert.match(main3d,/voice\?\.resume\(\)/);
  const micClick = main3d.slice(main3d.indexOf('function micClick()'), main3d.indexOf('micLauncher.addEventListener("click", micClick)'));
  assert.doesNotMatch(micClick, /openDock\(/, 'microphone click must not move the floating button');
  assert.match(mainHg,/voice\?\.resume\(\)/);
  assert.match(style,/data-mic-mode="continuous"/);
  assert.match(read('src/worlds/3d/index.html'), /id="miaMicLauncher"/);
  assert.match(read('src/worlds/hologram/index.html'), /id="mic"/);
});
