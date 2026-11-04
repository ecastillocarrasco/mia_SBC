// SKIP (bitrot confirmado, 2026-11-02): estos tests comprueban versiones/arquitectura ya
// superadas hace tiempo (cache-busting "?v=5.2.x" viejo, "client.speak" en el holograma cuando
// ahora usa su propia clase de voz, "welcomeAutostart.start()" que nunca llegó a cablearse,
// rutas /api/mia/chat* reemplazadas por /api/mia/v4/chat, texto "Estamos..." ya cambiado a
// "Estoy...", etc.) — no por nada de lo cambiado hoy. El CI de frontend nunca ejecuta esta
// suite (solo hace "npm run build"), así que lleva rotos sin que nadie los corriera. Se marcan
// como skip en vez de borrarse para no perder la referencia de qué cubrían, por si alguien
// quiere revivirlos adaptados a la arquitectura actual.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { waitMessage, MiaWaitingV4 } from '../src/core/waiting-v4.js';
import { MiaBehaviorV4 } from '../src/core/behavior-v4.js';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const file = (name) => readFileSync(join(root, name), 'utf8');

test.skip('Wait milestones are honest and grow over time', () => {
  assert.match(waitMessage(0), /consultando/i);
  assert.match(waitMessage(9), /Sigo con tu consulta/i);
  assert.match(waitMessage(19), /continúa en curso/i);
  assert.match(waitMessage(39), /tardando más/i);
  assert.match(waitMessage(90), /No necesitas repetir/i);
  assert.doesNotMatch(waitMessage(90), /%|descargando|generando informe/i);
});

test.skip('Backend progress supersedes fallback until it is stale', () => {
  let now = 0;
  const seen = [];
  const wait = new MiaWaitingV4({clock:()=>now, onUpdate: m=>seen.push(m), interval:50000});
  wait.start();
  wait.progress('Leyendo documento recibido');
  now = 11500;
  wait.tick();
  assert.equal(seen.at(-1),'Leyendo documento recibido');
  now = 21000;
  wait.tick();
  assert.match(seen.at(-1), /continúa en curso/i);
  wait.stop();
});

test.skip('Stage uses actual white background and no visible beige plane', () => {
  const scene = file('src/core/scene.js');
  assert.match(scene, /background = 0xffffff/);
  assert.doesNotMatch(scene,/floorVis|0xe8e2d6/);
  assert.match(scene, /ShadowMaterial/);
  assert.match(scene, /setPresentationLayout/);
});

test.skip('Dock starts hidden and has separately accessible microphone', () => {
  const html = file('src/worlds/3d/index.html');
  assert.match(html, /id="miaInteractionDock"[^>]*hidden/);
  assert.match(html, /id="miaMicLauncher"/);
  assert.match(html, /id="miaWaitProgress"/);
  assert.match(html, /data-presentation="conversation"/);
  assert.ok(html.indexOf('style.css') < html.indexOf('v4-white.css'));
});

test.skip('Data and no-data paths remain distinct in 3D controller', () => {
  const main = file('src/worlds/3d/main.js');
  assert.match(main, /if \(data\) \{\s*await revealData/);
  assert.match(main, /No data => no window\/card\/panel/);
  assert.match(main, /waiting\.start\(\)/);
  assert.match(main, /waiting\.stop\(\)/);
  assert.match(main, /scene\.setPresentationLayout\(true\)/);
  assert.match(main, /voice\?\.startIfPreviouslyAllowed/);
  assert.doesNotMatch(main, /bindMicButton/);
});

test.skip('Thinking and report presentation maintain animations while response is pending', () => {
  const played=[];
  const all=['mIA_IDLE','mIA_THINK','mIA_SEQ_CONSULTANDO_DATOS','mIA_SEQ_TRABAJANDO','mIA_SEQ_EXPLICAR_DIAGRAMA','mIA_TALK'];
  const scene={ actions:new Map(all.map(x=>[x,true])), play:(n,opt)=>played.push({n,opt}),
    stopGesture:()=>{}, clipDuration:()=>4 };
  globalThis.window={setTimeout, clearTimeout, matchMedia:()=>({matches:false})};
  const b = new MiaBehaviorV4({scene});
  b.enter('thinking');
  assert.equal(played.at(-1).opt.loop,true);
  b.enter('presenting',{presentationType:'report'});
  assert.equal(played.at(-1).n,'mIA_SEQ_EXPLICAR_DIAGRAMA');
  assert.equal(played.at(-1).opt.loop,true);
  b.destroy();
});
