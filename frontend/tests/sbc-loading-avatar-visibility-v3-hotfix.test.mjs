import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const root=resolve(import.meta.dirname,'..');
const src=(p)=>readFileSync(resolve(root,p),'utf8');

test('V3 overlay never paints an opaque canvas-obscuring white root',()=>{
  const v3=src('src/worlds/3d/sbc-logo-assembly-v3.css');
  const block=v3.match(/\.mia-boot\[data-variant="sbc-assembly"\]\s*\{([^}]+)\}/);
  assert.ok(block,'missing targeted brand variant rule');
  assert.match(block[1],/background\s*:\s*transparent\s*;/);
  assert.doesNotMatch(block[1],/background\s*:\s*#fff\b/);
  const v2=src('src/worlds/3d/sbc-logo-assembly-v2.css');
  assert.match(v2,/\.mia-boot\[data-variant="sbc-assembly"\]::before\s*\{[^}]*background:\s*#fff/);
  assert.match(v2,/\.mia-boot\[data-variant="sbc-assembly"\]\.mia-boot--avatar-ready::before\s*\{\s*opacity:0/);
  assert.match(v2,/\.mia-boot\[data-variant="sbc-assembly"\]\.mia-boot--error::before\s*\{\s*opacity:1/);
});

test('Avatar reveal waits for logo, uses same GLB and opens original action',()=>{
  const loader=src('src/core/boot-loader-v43.js');
  const main=src('src/worlds/3d/main.js');
  assert.match(loader,/await this\.assemblyDone;/);
  assert.match(loader,/this\.node\.classList\.add\('mia-boot--avatar-ready'\)/);
  assert.match(loader,/this\.avatarScene = scene;/);
  assert.match(main,/await boot\.revealAvatar\(scene\)/);
  assert.match(main,/await boot\.complete\(\{ onContinue:/);
  assert.doesNotMatch(src('src/worlds/2d/main.js'),/sbc-logo-assembly-v3/);
});
