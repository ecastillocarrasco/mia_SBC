import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { SBC_V2_PIECES, SBC_V2_ASSEMBLY_SECONDS, sbcAssemblyMarkup } from '../src/core/sbc-logo-assembly-v2.js';
const root=resolve(import.meta.dirname,'..');
const file=(name)=>readFileSync(resolve(root,name),'utf8');

test('Fidelity: sun, three original arcs, exactly four stars and original lettering',()=>{
  assert.deepEqual(SBC_V2_PIECES.map(p=>p.id),[
    'sol','arco-exterior','arco-rojo','arco-interior',
    'estrella-1','estrella-2','estrella-3','estrella-4','nombre'
  ]);
  const html=sbcAssemblyMarkup('/sbc/');
  assert.equal((html.match(/data-sbc-piece=/g)||[]).length,9);
  for(const piece of SBC_V2_PIECES){
    assert.ok(existsSync(resolve(root,`public/assets/loading/logo-pieces/${piece.id}.png`)));
    assert.ok(html.includes(`/sbc/assets/loading/logo-pieces/${piece.id}.png`));
  }
  assert.match(html,/Continuar la experiencia/);
  assert.match(html,/data-boot-retry/);
  assert.match(html,/data-boot-skip/);
  assert.match(html,/role="progressbar"/);
});

test('Timeline ends before mIA avatar reveal; CTA after actual GLB and preserved welcome audio click',()=>{
  assert.ok(SBC_V2_ASSEMBLY_SECONDS>=SBC_V2_PIECES.at(-1).delay+1.15);
  const main=file('src/worlds/3d/main.js');
  const loader=file('src/core/boot-loader-v43.js');
  assert.match(main,/import \{ sbcAssemblyMarkup \} from '\.\.\/\.\.\/core\/sbc-logo-assembly-v2\.js'/);
  assert.match(main,/await boot\.revealAvatar\(scene\)/);
  assert.ok(main.indexOf('await boot.revealAvatar(scene)')<main.indexOf('await boot.complete({ onContinue:'));
  assert.match(main,/welcomeVoice\.replay\(greeting\)/);
  assert.match(loader,/reduced \? 0 : 5650/);
  assert.match(loader,/scene\.play\('mIA_IDLE_SAFE'/);
  assert.match(loader,/window\.removeEventListener\('resize', this\._introResize\)/);
  assert.doesNotMatch(loader,/new GLTFLoader/);
});

test('True layers and reduced motion; confined to the 3D world',()=>{
  const css=file('src/worlds/3d/sbc-logo-assembly-v2.css');
  assert.match(css,/translateZ\(/);
  assert.match(css,/rotateY\(/);
  assert.match(css,/--sbc-mask/);
  assert.match(css,/prefers-reduced-motion:reduce/);
  assert.match(css,/max-width:850px/);
  assert.match(file('src/worlds/3d/main.js'),/sbc-logo-assembly-v2.css/);
  assert.doesNotMatch(file('src/worlds/2d/main.js'),/sbc-logo-assembly-v2/);
  assert.doesNotMatch(file('src/worlds/hologram/main.js'),/sbc-logo-assembly-v2/);
});
