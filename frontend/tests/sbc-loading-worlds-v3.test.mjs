import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { SBC_V2_PIECES,sbcAssemblyMarkup } from '../src/core/sbc-logo-assembly-v2.js';
const root = resolve(import.meta.dirname,'..');
const src = (file) => readFileSync(resolve(root,file),'utf8');

test('V3 loads all nine high-resolution official layers, no extra brand shapes', () => {
  assert.deepEqual(SBC_V2_PIECES.map(part=>part.id), [
    'sol','arco-exterior','arco-rojo','arco-interior',
    'estrella-1','estrella-2','estrella-3','estrella-4','nombre',
  ]);
  const markup=sbcAssemblyMarkup('/');
  assert.equal((markup.match(/data-sbc-piece=/g)||[]).length,9);
  assert.match(markup, /sunset-beach-club-logo\.png\?v=3/);
  for(const p of SBC_V2_PIECES){
    assert.match(markup,new RegExp(`${p.id}\\.png\\?v=3`));
    const buf=readFileSync(resolve(root,`public/assets/loading/logo-pieces/${p.id}.png`));
    assert.equal(buf.subarray(1,4).toString(),'PNG');
    assert.equal(buf.readUInt32BE(16),958);
    assert.equal(buf.readUInt32BE(20),806);
    assert.ok(p.depth<=2,'Excessive image layers would hurt performance');
  }
});

test('V3 fixes four slots before reveal; images decode before the animation starts', () => {
  const html=sbcAssemblyMarkup('/');
  const css=src('src/worlds/3d/sbc-logo-assembly-v3.css');
  const loader=src('src/core/boot-loader-v43.js');
  assert.match(html,/mia-sbc-v3__footer/);
  assert.match(html,/mia-sbc-v3__ready/);
  assert.match(css,/grid-template-rows:22px auto 27px 164px/);
  assert.match(css,/grid-template-areas:"overlay"/);
  assert.match(css,/\.mia-sbc-v3--play \.mia-sbc-v2__piece/);
  assert.match(loader,/Promise\.all\(decode\)\.then/);
  assert.match(loader,/img\.decode\(\)/);
  assert.match(loader,/this\.node\.classList\.add\('mia-sbc-v3--play'\)/);
  assert.ok(loader.indexOf('Promise.all(decode)') < loader.indexOf("this.node.classList.add('mia-sbc-v3--play')"));
});

test('V3 leaves copy sharp and keeps final source image frontal',()=>{
  const css=src('src/worlds/3d/sbc-logo-assembly-v3.css');
  assert.match(css,/filter:none!important/);
  assert.match(css,/image-rendering:auto/);
  assert.match(css,/rotateY\(0\)/);
  assert.match(css,/\.mia-sbc-v2__rotor::after \{content:none!important/);
  assert.doesNotMatch(css,/@keyframes sbcV3Approach\s*\{[^}]*filter:blur/);
  assert.match(css,/prefers-reduced-motion:reduce/);
});

test('V3 is scoped to 3D, preserves CTA gated by real input and 2D loading',()=>{
  const main=src('src/worlds/3d/main.js');
  const loader=src('src/core/boot-loader-v43.js');
  assert.match(main,/import '\.\/sbc-logo-assembly-v3\.css'/);
  assert.match(main,/await boot\.revealAvatar\(scene\)/);
  assert.match(loader,/if \(typeof onContinue !== 'function'\)/);
  assert.match(loader,/onContinue\(\)/);
  assert.match(sbcAssemblyMarkup('/'),/Continuar la experiencia/);
  assert.doesNotMatch(src('src/worlds/2d/main.js'),/sbc-logo-assembly-v3/);
  assert.doesNotMatch(src('src/worlds/hologram/main.js'),/sbc-logo-assembly-v3/);
  assert.ok(existsSync(resolve(root,'public/assets/loading/sunset-beach-club-master-hq.jpg')));
});
