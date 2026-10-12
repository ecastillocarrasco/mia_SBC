import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const materialFile = new URL('../src/worlds/hologram/hologram-material-v51.js', import.meta.url);
const source = await fs.readFile(materialFile, 'utf8');
const mod = await import('data:text/javascript;charset=utf-8,' + encodeURIComponent(source));

const fakeThree = {
  FrontSide: 'front', NormalBlending: 'normal', AdditiveBlending: 'add',
  SRGBColorSpace: 'srgb',
  Color: class Color { constructor(hex){this.hex=hex;} },
  ShaderMaterial: class ShaderMaterial {
    constructor(options){Object.assign(this,options);this.isShaderMaterial=true;}
  },
};
function fakeMaterial() {
  const texture = {name:'original-face-texture',colorSpace:'srgb'};
  const material = {
    map: texture,
    color: {multiply(){}},
    emissive: {set(hex){this.hex=hex;}},
    isShaderMaterial:false,
    depthWrite:true,
    transparent:false,
    userData: {},
    clone(){return {...this,emissive:{set(hex){this.hex=hex;}},userData:{}};},
    customProgramCacheKey(){return 'standard';},
  };
  return material;
}
function makeScene() {
  const material = fakeMaterial();
  const mesh = {isMesh:true,material};
  const instance = {
    model:{traverse(fn){fn(mesh);}},
    scene:{background:null},
  };
  return {instance,mesh,material};
}

test('hibrido es predeterminado; ninguna URL cambia el GLB',()=>{
  assert.equal(mod.resolveHologramMode('').mode,'hybrid');
  assert.equal(mod.resolveHologramMode('?avatar=hybrid').mode,'hybrid');
  assert.equal(mod.resolveHologramMode('?avatar=classic').mode,'classic');
  assert.equal(mod.resolveHologramMode('?avatar=natural').mode,'natural');
  assert.equal(mod.resolveHologramMode('?avatar=algo-desconocido').mode,'hybrid');
});

test('parámetros controlados y sin NaN',()=>{
  assert.equal(mod.resolveHologramMode('?glow=abc&face=-10').glow,1);
  assert.equal(mod.resolveHologramMode('?glow=abc&face=-10').face,.35);
  assert.equal(mod.resolveHologramMode('?glow=999&face=20').glow,1.8);
  assert.equal(mod.resolveHologramMode('?fan=1').fan,true);
  assert.equal(mod.resolveHologramMode('?fan=1').mode,'projection');
});

test('híbrido preserva mapa facial original y no toca material original',()=>{
  const {instance,mesh,material}=makeScene();
  const visual=mod.installHologramStyle(instance,fakeThree,'?avatar=hybrid');
  assert.equal(visual.mode,'hybrid');
  assert.equal(visual.meshes,1);
  assert.notEqual(mesh.material,material);
  assert.equal(mesh.material.map,material.map);
  assert.equal(mesh.material.transparent,true);
  assert.equal(mesh.material.depthWrite,true);
  assert.equal(material.transparent,false);
  assert.equal(mesh.material.customProgramCacheKey(),'standard|mia-hg51-hybrid');
});

test('shader hibrido conserva el GLSL PBR/skinning e inyecta máscara facial',()=>{
  const {instance,mesh}=makeScene();
  const visual=mod.installHologramStyle(instance,fakeThree,'?avatar=hybrid');
  const shader={
    uniforms:{},
    vertexShader:'#include <common>\n#include <project_vertex>\n',
    fragmentShader:'#include <common>\n#include <opaque_fragment>\n',
  };
  mesh.material.onBeforeCompile(shader);
  assert.match(shader.vertexShader,/vHgWorld\s*=/);
  assert.match(shader.vertexShader,/transformedNormal/);
  assert.match(shader.fragmentShader,/hgFaceMask/);
  assert.match(shader.fragmentShader,/gl_FragColor\.a\s*=\s*mix/);
  assert.match(shader.fragmentShader,/#include <opaque_fragment>/);
  assert.equal(shader.uniforms.uHgTime.value,0);
  visual.tick(2.5);
  assert.equal(shader.uniforms.uHgTime.value,2.5);
});

test('clásico reproduce shader radiográfico aditivo; opción natural restaura material',()=>{
  const classic=makeScene();
  const visual=mod.installHologramStyle(classic.instance,fakeThree,'?avatar=classic');
  assert.equal(classic.mesh.material.isShaderMaterial,true);
  assert.equal(classic.mesh.material.blending,'add');
  assert.match(classic.mesh.material.fragmentShader,/edge\s*=/);
  visual.tick(7);
  assert.equal(classic.mesh.material.uniforms.uTime.value,7);
  const natural=makeScene();
  const vn=mod.installHologramStyle(natural.instance,fakeThree,'?avatar=natural');
  assert.equal(natural.mesh.material,natural.material);
  assert.equal(vn.mode,'natural');
});

test('modo ventilador usa negro absoluto y más opacidad',()=>{
  const {instance,mesh}=makeScene();
  const visual=mod.installHologramStyle(instance,fakeThree,'?fan=1');
  assert.equal(instance.scene.background.hex,0x000000);
  const shader={uniforms:{},vertexShader:'#include <common>\n#include <project_vertex>',fragmentShader:'#include <common>\n#include <opaque_fragment>'};
  mesh.material.onBeforeCompile(shader);
  assert.equal(shader.uniforms.uHgBodyOpacity.value,.74);
  assert.equal(shader.uniforms.uHgGlow.value,1.22*1.14);
  assert.equal(visual.fan,true);
});

test('entrada holograma mantiene voz, 84 animaciones, datos y micrófono',async()=>{
  const base = new URL('../src/worlds/hologram/',import.meta.url);
  const main=await fs.readFile(new URL('main.js',base),'utf8');
  for (const token of ['new MiaVoiceV4', 'voice?.cycle()', 'await client.speak', 'renderHologramBrief', 'scene.load(', 'sourceClipCount !== 84', 'new MiaHologramDirectorV52', 'installHologramStyle', 'hologramEffect?.tick(time)']) {
    assert.ok(main.includes(token),token);
  }
  for (const forbidden of ['src/worlds/3d/', 'src/worlds/2d/']) {
    assert.ok(!main.includes(forbidden));
  }
});
