import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import vm from 'node:vm';

const root = resolve(import.meta.dirname, '..');
const read = (path) => readFileSync(resolve(root, path), 'utf8');

function mockBootLoader() {
  class Stub {
    constructor() {this.style={};this.attrs={};this.dataset={};this.hidden=true;this.className='';this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};this.textContent='';}
    setAttribute(name, value){this.attrs[name]=value;}
    addEventListener(){}
    remove() {this.removed=true;}
    querySelector() {return new Stub();}
    querySelectorAll() {return [new Stub(),new Stub(),new Stub()];}
  }
  let script=read('src/core/boot-loader-v43.js')
    .replace(/^import ['"]\.\/boot-loader-v43\.css['"];?\n/m,'')
    .replace('import.meta.env?.BASE_URL', "{ BASE_URL: '/' }.BASE_URL")
    .replace('export class MiaBootLoader', 'class MiaBootLoader');
  script += '\nglobalThis.TestBoot = MiaBootLoader;';
  const rootNode=new Stub();
  rootNode.appendChild=()=>{};
  const ctx={
    document:{createElement:()=>new Stub(),body:rootNode},
    window:{location:{reload() {}}},console,
    requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},setTimeout,clearTimeout,
  };
  vm.runInNewContext(script,ctx);
  return new ctx.TestBoot({root:rootNode});
}

test('loading percentage uses real transfer progress and cannot regress',()=>{
  const boot=mockBootLoader();
  assert.equal(boot.target,0);
  boot.progress(.25,{phase:'downloading',loadedBytes:100,totalBytes:400});
  assert.equal(boot.target,25);
  assert.equal(boot.statusEl.textContent,'Cargando los recursos de Mía…');
  boot.progress(.1,{phase:'downloading',loadedBytes:40,totalBytes:400});
  assert.equal(boot.target,25);
  boot.progress(.94,{phase:'processing'});
  assert.equal(boot.target,94);
  assert.equal(boot.statusEl.textContent,'Preparando el personaje 3D…');
  boot.displayed=94;boot._render();
  assert.equal(boot.percentEl.textContent,'94');
  assert.equal(boot.progressEl.attrs['aria-valuenow'],'94');
  boot.dispose();
});

test('failed loads do not fake 100 and offer a retry',()=>{
  const boot=mockBootLoader();
  boot.progress(.48,{phase:'downloading'});
  boot.fail(new Error('HTTP 404'));
  assert.equal(boot.target,48);
  assert.equal(boot.phase,'error');
  assert.equal(boot.retryEl.hidden,false);
  boot.dispose();
});

test('percent is not baked into artwork and corporate original logo included',()=>{
  const js=read('src/core/boot-loader-v43.js');
  assert.match(js,/data-boot-percent/);
  assert.match(js,/sunset-beach-club-logo\.png/);
  assert.match(js,/mia-loading-art\.webp/);
  assert.match(js,/target = this\.displayed = 100/);
});

test('3D and hologram call dynamic boot loader and wait before the greeting',()=>{
  for (const path of ['src/worlds/3d/main.js','src/worlds/hologram/main.js']) {
    const js=read(path);
    assert.match(js,/new MiaBootLoader/);
    assert.match(js,/boot\.progress\(/);
    assert.match(js,/await boot\.complete\(\)/);
    assert.match(js,/boot\.fail\(error\)/);
  }
  const scene=read('src/core/scene.js');
  assert.match(scene,/event\.loaded/);
  assert.match(scene,/event\.total/);
  assert.match(scene,/EXPECTED_BYTES = 39562116/);
  assert.match(scene,/onProgress\?\.\(0\.99/);
});

test('microphone manual activation and 84-clip model remain unchanged',()=>{
  for (const path of ['src/worlds/3d/main.js','src/worlds/hologram/main.js']) {
    const js=read(path);
    assert.match(js,/MiaVoiceV4/);
    assert.match(js,/voice\?\.toggle\(/);
    assert.doesNotMatch(js,/startIfPreviouslyAllowed\(/);
  }
  assert.match(read('src/core/scene.js'),/mIA_SBC_V4_84_ANIMACIONES\.glb/);
});
