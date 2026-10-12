import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const read = (f) => readFileSync(new URL('../' + f, import.meta.url), 'utf8');

function loaderHarness() {
  class Node {
    constructor() {
      this.hidden = true; this.disabled = false; this.style = {}; this.attrs = {};
      this.dataset = {}; this.listeners = {}; this.textContent = ''; this.innerHTML = '';
      this.classList = { add: (x) => { this.className += ' ' + x; }, toggle() {} };
    }
    addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
    click() { for (const callback of this.listeners.click || []) callback({isTrusted:true}); }
    setAttribute(k,v) { this.attrs[k]=v; }
    focus() {}
    remove() { this.removed = true; }
    querySelector(selector) { return this.children[selector] ||= new Node(); }
    querySelectorAll() { return [new Node(),new Node(),new Node()]; }
  }
  const root = new Node(); root.appendChild = (node) => { root.appended = node; };
  const script = read('src/core/boot-loader-v43.js')
    .replace(/^import '\.\/boot-loader-v43\.css';\n/m, '')
    .replace('import.meta.env?.BASE_URL', "{ BASE_URL: '/' }.BASE_URL")
    .replace('export class MiaBootLoader', 'class MiaBootLoader') + '\nglobalThis.Boot = MiaBootLoader;';
  const context = { document:{body:root, createElement:()=>{ const node=new Node();node.children={};return node; }},
    window:{location:{reload() {}}}, console,
    requestAnimationFrame: (cb) => { if (!cb.name.includes('_tick')) queueMicrotask(cb); return 1; },
    cancelAnimationFrame() {}, setTimeout: (fn) => setTimeout(fn,0),clearTimeout,
  };
  vm.runInNewContext(script, context);
  return {boot:new context.Boot({root}),root};
}
const tick=()=>new Promise((resolve)=>setTimeout(resolve,5));

test('3D remains at 100% and waits for one real continue click', async () => {
  const {boot}=loaderHarness();
  let calls=0;
  const done=boot.complete({onContinue:()=>{
    calls++; return {status:'playing'};
  }});
  await tick();
  assert.equal(boot.percentEl.textContent,'100');
  assert.equal(boot.phase,'ready-for-user');
  assert.equal(boot.actionsEl.hidden,false);
  assert.equal(calls,0,'voice not started before user gesture');
  boot.continueEl.click();
  assert.equal(calls,1,'voice starts synchronously in the click callback');
  assert.equal((await done).status,'playing');
  assert.equal(boot.active,false);
});

test('blocked audio keeps the button and offers a silent fallback',async()=>{
  const {boot}=loaderHarness();
  let attempts=0;
  const done=boot.complete({onContinue:()=>{
    attempts++;return {status:'blocked'};
  }});
  await tick();boot.continueEl.click();await tick();
  assert.equal(attempts,1);
  assert.equal(boot.active,true);
  assert.equal(boot.skipEl.hidden,false);
  assert.equal(boot.continueEl.disabled,false);
  boot.skipEl.click();
  assert.equal((await done).status,'skipped-audio');
  assert.equal(boot.active,false);
});

test('3D starts cached audio via the loading click without simulated controls',()=>{
  const js=read('src/worlds/3d/main.js');
  assert.match(js,/await boot\.complete\(\{ onContinue: \(\) => \{/);
  assert.match(js,/welcomeVoice\.replay\(greeting\)/);
  assert.match(js,/const initialWelcomeAudio = welcomeVoice\.prepare\(/);
  assert.doesNotMatch(js,/welcomeAutostart\.start\(greeting\)/);
  assert.doesNotMatch(js,/\.click\(\)/);
  assert.match(js,/voice\?\.cycle\(\)/);
  assert.match(read('src/core/boot-loader-v43.js'),/data-boot-continue/);
  assert.match(read('src/core/boot-loader-v43.css'),/mia-boot__continue/);
  assert.doesNotMatch(read('src/worlds/3d/index.html'),/miaWelcomeReplay/);
});

test('hologram retains autonomous greeting and original boot behavior',()=>{
  const js=read('src/worlds/hologram/main.js');
  assert.match(js,/await boot\.complete\(\)/);
  assert.match(js,/welcomeAutostart\.start\(welcomeMessage\)/);
});
