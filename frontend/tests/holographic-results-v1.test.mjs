import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { HolographicResults3D, shouldUseSpatialResults } from '../src/worlds/3d/holographic-results-v1.js';

class FakeClasses {
  set = new Set();
  add(...names) { for (const name of names) this.set.add(name); }
  remove(...names) { for (const name of names) this.set.delete(name); }
  contains(name) { return this.set.has(name); }
  toggle(name, active) { if (active) this.add(name); else this.remove(name); }
}
class FakeElement extends EventTarget {
  constructor() {
    super();
    this.children = [];
    this.classList = new FakeClasses();
    this.vars = new Map();
    this.attributes = new Map();
    this.style = { setProperty: (k, v) => this.vars.set(k, v),
      removeProperty: (k) => this.vars.delete(k) };
    this.offsetWidth = 900;
    this.offsetHeight = 650;
  }
  appendChild(element) { this.children.push(element); element.parent = this; return element; }
  insertBefore(element) { return this.appendChild(element); }
  remove() { this.parent?.children.splice(this.parent.children.indexOf(this), 1); }
  setAttribute(k,v) { this.attributes.set(k,v); }
  getBoundingClientRect() { return {left:510,top:18,width:900,height:650}; }
  querySelector(selector) {
    if (selector === '.panel-head') return this.head;
    if (selector === '#closeResults') return this.close;
    return null;
  }
}
function environment(width = 1440, query = '') {
  const window = new EventTarget();
  window.innerWidth = width;
  window.innerHeight = 900;
  window.location = { search: query };
  const root = new FakeElement();
  const panel = new FakeElement();
  panel.head = new FakeElement();
  panel.head.close = new FakeElement();
  globalThis.window = window;
  globalThis.document = {body:root,createElement:() => new FakeElement()};
  globalThis.getComputedStyle = () => ({right:'22px',top:'18px'});
  const rafs = new Map(); let id = 0;
  globalThis.requestAnimationFrame = (cb) => {rafs.set(++id,cb);return id;};
  globalThis.cancelAnimationFrame = (key) => rafs.delete(key);
  const flush = () => {const batch=[...rafs.entries()];rafs.clear();for(const [,cb] of batch)cb(0);};
  const scene = {scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(40,16/9,.01,100),onFrame:null};
  scene.camera.position.set(0,1.47,3.88);
  return {scene,panel,root,flush};
}

test('spatial visuals respect fallback and accessibility', () => {
  assert.equal(shouldUseSpatialResults({width:1440}),true);
  assert.equal(shouldUseSpatialResults({width:1099}),false);
  assert.equal(shouldUseSpatialResults({width:1440,reducedMotion:true}),false);
  assert.equal(shouldUseSpatialResults({enabled:false}),false);
});

test('prepare / reveal / reading / close preserve presentation and dispose', () => {
  const {scene,panel,root,flush} = environment();
  const prior = () => {};
  scene.onFrame = prior;
  const hologram = new HolographicResults3D({scene,panel,root});
  hologram.prepare();
  assert.equal(root.classList.contains('mia-holo-active'),true);
  assert.equal(root.classList.contains('mia-holo-preparing'),true);
  hologram.reveal(); flush(); flush();
  assert.equal(root.classList.contains('mia-holo-preparing'),false);
  assert.equal(panel.classList.contains('mia-holo-materialize'),true);
  assert.equal(hologram.emitter.visible,true);
  scene.onFrame(1.25);
  assert.ok(Number.isFinite(hologram.emitter.position.x));
  hologram.setReading(true);
  assert.equal(root.classList.contains('mia-holo-active'),false);
  assert.equal(root.classList.contains('mia-holo-reading'),true);
  assert.equal(hologram.emitter.visible,false);
  hologram.setReading(false);
  assert.equal(root.classList.contains('mia-holo-active'),true);
  hologram.reset();
  assert.equal(root.classList.contains('mia-holo-active'),false);
  assert.equal(panel.classList.contains('mia-holo-materialize'),false);
  hologram.destroy();
  assert.equal(scene.onFrame,prior);
  assert.equal(scene.scene.children.length,0);
});

test('explicit opt-out and narrow screens never activate spatial stage', () => {
  for (const [width, query] of [[1440,'?holo3d=0'],[800,'']]) {
    const {scene,panel,root} = environment(width,query);
    const engine = new HolographicResults3D({scene,panel,root});
    engine.prepare();engine.reveal();
    assert.equal(root.classList.contains('mia-holo-active'),false);
    assert.equal(engine.emitter.visible,false);
    engine.destroy();
  }
});
