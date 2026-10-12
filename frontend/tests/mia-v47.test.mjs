import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MiaWelcomeAutostartV47 } from '../src/core/welcome-autostart-v47.js';

const source = (file) => readFileSync(new URL('../' + file, import.meta.url), 'utf8');
const tick = () => new Promise((resolve) => setImmediate(resolve));

function harness(voice, { allowed = () => true } = {}) {
  const listeners = new Map();
  const timeouts = new Map();
  let next = 0;
  const eventTarget = {
    addEventListener(name, fn) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(fn);
    },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
    fire(name, extra = {}) {
      for (const fn of listeners.get(name) || []) {
        fn({ type: name, isTrusted: true, ...extra });
      }
    },
    count(name) { return listeners.get(name)?.size || 0; },
  };
  const controller = new MiaWelcomeAutostartV47({
    voice, canSpeak: allowed, eventTarget,
    setTimer: (fn) => { const id = ++next; timeouts.set(id, fn); return id; },
    clearTimer: (id) => timeouts.delete(id),
  });
  return {
    controller, eventTarget, timeouts,
    async runTimers() {
      const tasks = [...timeouts.values()];
      timeouts.clear();
      tasks.forEach((fn) => fn());
      await tick();
    },
  };
}

test('welcome starts automatically and requires no replay button', async () => {
  let play = 0;
  const h = harness({ start: async () => { play++; return { status: 'playing' }; } });
  assert.equal((await h.controller.start('Hola Enrique')).status, 'playing');
  assert.equal(play, 1);
  assert.equal(h.eventTarget.count('pointerdown'), 0);
  assert.equal(h.timeouts.size, 0);
});

test('autoplay rejection retries cached audio once without fake DOM clicks', async () => {
  let attempts = 0, preloaded = 0;
  const h = harness({
    start: async () => { preloaded++; return { status: 'blocked' }; },
    playPrepared: async () => { attempts++; return { status: 'playing' }; },
  });
  assert.equal((await h.controller.start('Hola Enrique')).status, 'blocked');
  assert.equal(h.eventTarget.count('pointerdown'), 1);
  assert.equal(h.timeouts.size, 1);
  await h.runTimers();
  assert.equal(attempts, 1);
  assert.equal(preloaded, 1);
  assert.equal(h.eventTarget.count('pointerdown'), 0);
  assert.equal(h.timeouts.size, 0);
});

test('when both autoplay attempts are blocked the first trusted gesture plays cached voice', async () => {
  let attempts = 0;
  const h = harness({
    start: async () => ({ status: 'blocked' }),
    playPrepared: async () => { attempts++; return { status: 'blocked' }; },
    replay() { attempts++; return Promise.resolve({ status: 'playing' }); },
  });
  await h.controller.start('Hola Enrique');
  await h.runTimers();
  assert.equal(attempts, 1);
  h.eventTarget.fire('pointerdown');
  await tick();
  assert.equal(attempts, 2);
  assert.equal(h.eventTarget.count('pointerdown'), 0);
  h.eventTarget.fire('click');
  await tick();
  assert.equal(attempts, 2, 'no double greeting on subsequent events');
});

test('synthetic events cannot trigger the gesture fallback', async () => {
  let attempts = 0;
  const h = harness({
    start: async () => ({ status: 'blocked' }),
    playPrepared: async () => ({ status: 'blocked' }),
    replay() { attempts++; return Promise.resolve({ status: 'playing' }); },
  });
  await h.controller.start('Hola Enrique');
  h.eventTarget.fire('click', { isTrusted: false });
  await tick();
  assert.equal(attempts, 0);
  h.eventTarget.fire('keydown', { key: 'Control' });
  await tick();
  assert.equal(attempts, 0);
  h.eventTarget.fire('keydown', { key: 'Enter' });
  await tick();
  assert.equal(attempts, 1);
});

test('cancel on user query/mute prevents deferred greeting and removes listeners', async () => {
  let attempts = 0;
  const h = harness({
    start: async () => ({ status: 'blocked' }),
    playPrepared: async () => { attempts++; return { status: 'playing' }; },
    replay: async () => { attempts++; return { status: 'playing' }; },
  });
  await h.controller.start('Hola Enrique');
  h.controller.cancel();
  assert.equal(h.timeouts.size, 0);
  assert.equal(h.eventTarget.count('pointerdown'), 0);
  h.eventTarget.fire('pointerdown');
  await h.runTimers();
  assert.equal(attempts, 0);
});

test('voice endpoint unavailable attempts browser TTS without requiring a button', async () => {
  let attempts = 0;
  const h = harness({
    start: async () => ({ status: 'unavailable' }),
    replay: async () => { attempts++; return { status: 'browser-speaking' }; },
  });
  await h.controller.start('Hola Enrique');
  await h.runTimers();
  assert.equal(attempts, 1);
  h.controller.markPlaying();
  assert.equal(h.eventTarget.count('keydown'), 0);
});

test('do not trigger audio on muted or busy state', async () => {
  let maySpeak = true, starts = 0, replays = 0;
  const h = harness({
    start: async () => { starts++; return { status: 'blocked' }; },
    replay: async () => { replays++; return { status: 'playing' }; },
    playPrepared: async () => ({ status: 'blocked' }),
  }, { allowed: () => maySpeak });
  await h.controller.start('Hola Enrique');
  maySpeak = false;
  h.eventTarget.fire('pointerdown');
  await h.runTimers();
  assert.equal(replays, 0);
  await h.controller.start('Hola Enrique');
  assert.equal(starts, 1);
});

test('3D uses click-to-start and hologram retains autostart; no replay button', () => {
  for (const world of ['3d', 'hologram']) {
    const js = source(`src/worlds/${world}/main.js`);
    const html = source(`src/worlds/${world}/index.html`);
    assert.match(js, /MiaWelcomeAutostartV47/);
    if (world === 'hologram') assert.match(js, /welcomeAutostart\.start\(.*\)/);
    else assert.match(js, /welcomeVoice\.replay\(greeting\)/);
    assert.match(js, /welcomeAutostart\.cancel\(\)/);
    assert.match(js, /welcomeAutostart\.dispose\(\)/);
    assert.doesNotMatch(js, /welcomeReplay|\.click\(\)/);
    assert.doesNotMatch(html, /miaWelcomeReplay|Escuchar saludo/);
  }
  assert.match(source('src/worlds/3d/main.js'), /voice\?\.cycle\(\)/);
  assert.match(source('src/worlds/hologram/main.js'), /voice\?\.cycle\(\)/);
});

test('microphone clicks, mute clicks and typing do not inadvertently replay greeting', async () => {
  let count=0;
  const h=harness({start:async()=>({status:'blocked'}),playPrepared:async()=>({status:'blocked'}),replay(){count++;return Promise.resolve({status:'playing'});}});
  await h.controller.start('Hola Enrique');
  const mic={closest:(sel)=>sel.includes('#mic') ? {} : null};
  h.eventTarget.fire('pointerdown',{target:mic});
  const mute={closest:(sel)=>sel.includes('#voiceToggle') ? {} : null};
  h.eventTarget.fire('pointerdown',{target:mute});
  h.eventTarget.fire('keydown',{key:'a',target:{tagName:'INPUT'}});
  await tick();
  assert.equal(count,0);
  h.eventTarget.fire('pointerdown',{target:{closest:()=>null}});
  await tick();
  assert.equal(count,1);
});
