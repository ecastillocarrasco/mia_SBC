import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { SBC_LOGO_PIECES, sbcAssemblyMarkup } from '../src/core/sbc-logo-assembly-v1.js';

const root = resolve(import.meta.dirname, '..');
const file = (name) => readFileSync(resolve(root,name),'utf8');

test('Seven original pieces ordered: sun, arc, exactly four stars, lettering', () => {
  assert.deepEqual(SBC_LOGO_PIECES.map(([key])=>key), [
    'sol','arcoiris','estrella-1','estrella-2','estrella-3','estrella-4','nombre',
  ]);
  const html = sbcAssemblyMarkup('/mia/');
  assert.equal((html.match(/data-sbc-piece=/g)||[]).length,7);
  assert.ok(html.includes('Continuar la experiencia'));
  assert.ok(html.includes('role="progressbar"'));
  assert.ok(html.includes('data-boot-skip'));
  for (const [piece] of SBC_LOGO_PIECES) {
    assert.ok(existsSync(resolve(root,`public/assets/loading/logo-pieces/${piece}.png`)));
    assert.ok(html.includes(`/mia/assets/loading/logo-pieces/${piece}.png`));
  }
});

test('3D reveals same scene after image assembly and before the real click, preserving voice', () => {
  const main = file('src/worlds/3d/main.js');
  const boot = file('src/core/boot-loader-v43.js');
  assert.match(main,/new MiaBootLoader\(\{ mode: "3d", variant: "sbc-assembly", markup: sbcAssemblyMarkup \}\)/);
  assert.match(main,/await boot\.revealAvatar\(scene\)/);
  assert.ok(main.indexOf('await boot.revealAvatar(scene)') < main.indexOf('await boot.complete({ onContinue:'));
  assert.match(main,/welcomeVoice\.replay\(greeting\)/);
  assert.match(boot,/await this\.assemblyDone/);
  assert.match(boot,/scene\._framingGoal = window\.innerWidth/);
  assert.doesNotMatch(boot,/new GLTFLoader/);
});

test('2D uses original 3D boot template, tracks actual image loads, retains paint guard', () => {
  const entry = file('src/worlds/2d/mia-entry-v530.js');
  assert.match(entry,/import \{ MiaBootLoader \}/);
  assert.match(entry,/new MiaBootLoader\(\{ mode: '2d', root \}\)/);
  assert.match(entry,/img\.addEventListener\('load'/);
  assert.match(entry,/img\.addEventListener\('error'/);
  assert.match(entry,/boot\.complete\(\{ onContinue:/);
  for (const page of ['mia-2d.html','src/worlds/2d/index.html']) {
    assert.match(file(page),/mia2d-entry-paint-guard/);
  }
});

test('Reduced motion and mobile fallbacks preserve usability',()=>{
  const css=file('src/worlds/3d/sbc-logo-assembly-v1.css');
  assert.match(css,/@media\(max-width:750px\)/);
  assert.match(css,/@media\(prefers-reduced-motion:reduce\)/);
  assert.match(css,/\.mia-boot--avatar-ready/);
});
