import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { HolographicResults3D } from '../src/worlds/3d/holographic-results-v1.js';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
class FakeClasses {
  set = new Set();
  add(...items) { items.forEach((item) => this.set.add(item)); }
  remove(...items) { items.forEach((item) => this.set.delete(item)); }
  contains(item) { return this.set.has(item); }
  toggle(item, value) { value ? this.add(item) : this.remove(item); }
}
class FakeElement extends EventTarget {
  constructor() {
    super();
    this.classList = new FakeClasses();
    this.children = [];
    this.vars = new Map();
    this.style = {setProperty:(key,val)=>this.vars.set(key,val),
      getPropertyValue:(key)=>this.vars.get(key) || '', removeProperty:(key)=>this.vars.delete(key)};
    this.offsetWidth = 820;
    this.offsetHeight = 600;
    this.attributes = new Map();
    this.metrics = [];
    this.chartElements = [];
    this.barElements = [];
    this.tableRows = [];
  }
  appendChild(el) { this.children.push(el);el.parent=this;return el; }
  insertBefore(el) { return this.appendChild(el); }
  remove() { this.parent?.children.splice(this.parent.children.indexOf(this),1); }
  setAttribute(k,v) { this.attributes.set(k,v); }
  getBoundingClientRect() { return {left:300,top:18,width:820,height:600}; }
  querySelector(selector) {
    if (selector === '.panel-head') return this.head;
    if (selector === '#closeResults') return this.close;
    return null;
  }
  querySelectorAll(selector) {
    if (selector === '.stat-bar-track i') return this.barElements;
    if (selector === '.stat-chart') return this.chartElements;
    if (selector === 'table tbody tr') return this.tableRows;
    return this.metrics;
  }
}
function setup({query='',width=1450,rows=0,bars=[],metrics=3}={}) {
  const win = new EventTarget();
  win.innerWidth = width;
  win.innerHeight = 900;
  win.location = {search:query};
  globalThis.window = win;
  globalThis.document = {body:new FakeElement(),createElement:()=>new FakeElement()};
  globalThis.getComputedStyle = (elem) => ({right:'22px',top:'18px',getPropertyValue:
    (key)=>elem?.style?.getPropertyValue?.(key) ?? ''});
  const rafs=new Map();let rafId=0;
  globalThis.requestAnimationFrame=(callback)=>{rafs.set(++rafId,callback);return rafId;};
  globalThis.cancelAnimationFrame=(id)=>rafs.delete(id);
  const flush=()=>{const entries=[...rafs];rafs.clear();entries.forEach(([,fn])=>fn(1));};
  const scene = {scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(40,16/9,.01,100),onFrame:null};
  scene.camera.position.set(0,1.47,3.88);
  const panel = new FakeElement();
  panel.head = new FakeElement();
  panel.head.close = new FakeElement();
  panel.metrics=Array.from({length:metrics},()=>new FakeElement());
  panel.barElements=bars.map((bar)=>{const element=new FakeElement();element.style.setProperty('--bar',`${bar}%`);return element;});
  panel.tableRows=Array.from({length:rows},()=>new FakeElement());
  return {scene,panel,root:document.body,flush};
}
test('Breakout V2 uses actual Three.js extruded geometry and only source chart values', () => {
  const ctx=setup({bars:[74,29,0],metrics:2});
  const engine=new HolographicResults3D(ctx);
  engine.prepare();engine.reveal();ctx.flush();ctx.flush();
  assert.equal(engine.breakout.visible,true);
  assert.equal(engine.breakout.name,'mIA_Breakout3D_DataPortal');
  assert.equal(ctx.root.classList.contains('mia-breakout-active'),true);
  assert.equal(engine._breakoutParts.length,4);
  assert.equal(engine._barMeshes.filter((m)=>m.visible).length,2);
  assert.ok(engine._barMeshes[0].scale.x > engine._barMeshes[1].scale.x);
  assert.equal(engine._barMeshes[2].visible,false);
  assert.ok(ctx.panel.metrics.every((m)=>m.classList.contains('mia-breakout-card')));
  assert.equal(ctx.panel.metrics.length,2); // nothing cloned
  ctx.scene.onFrame(2);
  assert.ok(Number.isFinite(engine.breakout.position.x));
  engine.setReading(true);
  assert.equal(engine.breakout.visible,false);
  assert.equal(ctx.root.classList.contains('mia-breakout-active'),false);
  engine.setReading(false);
  assert.equal(engine.breakout.visible,true);
  engine.reset();
  assert.ok(ctx.panel.metrics.every((m)=>!m.classList.contains('mia-breakout-card')));
  engine.destroy();
  assert.equal(ctx.scene.scene.children.length,0);
});
test('Breakout off falls back to V1; spatial off disables all effects', () => {
  for (const [query,oldActive] of [['?breakout3d=0',true],['?holo3d=0',false]]) {
    const ctx=setup({query});
    const engine=new HolographicResults3D(ctx);
    engine.prepare();engine.reveal();ctx.flush();ctx.flush();
    assert.equal(ctx.root.classList.contains('mia-holo-active'),oldActive);
    assert.equal(ctx.root.classList.contains('mia-breakout-active'),false);
    assert.equal(engine.breakout.visible,false);
    engine.destroy();
  }
});
test('long tables return to frontal reading automatically and timer clears on reset', async () => {
  const ctx=setup({rows:16});
  const engine=new HolographicResults3D(ctx);
  engine.prepare();engine.reveal();ctx.flush();ctx.flush();
  assert.ok(engine._readingTimer);
  engine.reset();
  assert.equal(engine._readingTimer,0);
  assert.equal(engine.hasResult,false);
  engine.destroy();
});
test('world 3D only: single renderer, non-destructive controls and disabling by URL', () => {
  const main=read('src/worlds/3d/main.js');
  const script=read('src/worlds/3d/holographic-results-v1.js');
  const css=read('src/worlds/3d/holographic-results-v1.css');
  assert.match(main,/holographicResults\.prepare\(\)/);
  assert.match(main,/holographicResults\.reveal\(\)/);
  assert.match(script,/breakout3d/);
  assert.match(script,/querySelectorAll\?\.\('\.stat-bar-track i'\)/);
  assert.match(css,/miaBreakoutCardLaunch/);
  assert.match(css,/mia-holo-reading/);
  assert.doesNotMatch(read('src/worlds/2d/main.js'),/mia-breakout-active/);
  assert.doesNotMatch(read('src/worlds/hologram/main.js'),/mia-breakout-active/);
});
