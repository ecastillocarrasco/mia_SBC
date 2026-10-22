import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { HolographicResults3D } from '../src/worlds/3d/holographic-results-v1.js';
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
class ClassSet {constructor(){this.s=new Set();} add(...xs){xs.forEach(x=>this.s.add(x));} remove(...xs){xs.forEach(x=>this.s.delete(x));} toggle(x,b){b?this.add(x):this.remove(x);}contains(x){return this.s.has(x);}}
class Element extends EventTarget {
 constructor(){super();this.classList=new ClassSet();this.children=[];this.vars=new Map();this.style={setProperty:(k,v)=>this.vars.set(k,v),removeProperty:(k)=>this.vars.delete(k),getPropertyValue:(k)=>this.vars.get(k)||''};this.offsetHeight=650;this.offsetWidth=900;this.scrollHeight=0;}
 appendChild(c){this.children.push(c);c.parent=this;return c;}
 insertBefore(c){return this.appendChild(c);}
 remove(){if(this.parent)this.parent.children.splice(this.parent.children.indexOf(this),1);}
 setAttribute(){};
 getBoundingClientRect(){return {left:400,top:18,width:900,height:650};}
 querySelector(q){return q==='.panel-head'?this.head:q==='.conversation'?this.conversation:q==='#closeResults'?this.close:null;}
 querySelectorAll(q){return q==='table tbody tr'?this.rows:q==='.stat-bar-track i'?[]:this.metrics;}
}
function fake(height=260,rows=1) {
 const w=new EventTarget();w.innerWidth=1652;w.innerHeight=889;w.location={search:''};globalThis.window=w;
 const body=new Element();globalThis.document={body,createElement:()=>new Element()};
 globalThis.getComputedStyle=()=>({right:'22px',top:'18px'});
 const q=[];globalThis.requestAnimationFrame=(f)=>{q.push(f);return q.length;};globalThis.cancelAnimationFrame=()=>{};
 const panel=new Element();panel.head=new Element();panel.head.close=new Element();panel.head.offsetHeight=44;panel.conversation=new Element();panel.conversation.scrollHeight=height;panel.rows=Array.from({length:rows},()=>new Element());panel.metrics=[];
 const scene={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(40,1652/889,.01,100),onFrame:null};scene.camera.position.set(0,1.47,3.88);
 return {w,body,panel,scene,q};
}
test('single-row employee detail fits within viewport, without massive empty window',()=>{
 const ctx=fake(385,1);const e=new HolographicResults3D({scene:ctx.scene,panel:ctx.panel,root:ctx.body});
 e.prepare();e.reveal();const a=ctx.q.splice(0);a.forEach(fn=>fn(0));ctx.q.splice(0).forEach(fn=>fn(0));
 const width=parseInt(ctx.body.vars.get('--mia-breakout-panel-width'),10);
 const height=parseInt(ctx.body.vars.get('--mia-breakout-panel-height'),10);
 const top=parseInt(ctx.body.vars.get('--mia-breakout-panel-top'),10);
 assert.ok(width>=550&&width<=860);
 assert.ok(height>=390&&height<700);
 assert.ok(top>=50&&top+height<889-10);
 assert.equal(ctx.body.classList.contains('mia-breakout-compact'),true);
 assert.equal(ctx.body.children.filter(n=>n.className==='mia-breakout-portal').length,1);
 e.destroy();
});
test('large report is height-limited and returns to reading with its original HTML',()=>{
 const ctx=fake(1800,21);const e=new HolographicResults3D({scene:ctx.scene,panel:ctx.panel,root:ctx.body});
 e.prepare();e.reveal();ctx.q.splice(0).forEach(fn=>fn(0));ctx.q.splice(0).forEach(fn=>fn(0));
 assert.ok(parseInt(ctx.body.vars.get('--mia-breakout-panel-height'),10)<=889-122);
 assert.equal(ctx.body.classList.contains('mia-breakout-compact'),false);
 assert.equal(e._decorated.length,0);
 assert.ok(e._readingTimer);
 e.destroy();
});
test('V3 includes compact real-detail animation, visible margins, and thin geometry',()=>{
 const src=read('src/worlds/3d/holographic-results-v1.js');
 const css=read('src/worlds/3d/holographic-results-v1.css');
 assert.match(css,/\.mia-breakout-detail/);
 assert.match(css,/miaBreakoutDetailLift/);
 assert.match(css,/--mia-breakout-panel-width/);
 assert.match(src,/content-sized|Content-sized/i);
 assert.equal((src.match(/this\.portal = document\.createElement/g)||[]).length,1);
 assert.equal((src.match(/this\._decorated = \[\]/g)||[]).length,2); // constructor and cleanup
 assert.match(read('src/worlds/3d/index.html'),/breakout-v3/);
});
