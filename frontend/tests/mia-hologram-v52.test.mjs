import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const root = new URL('../src/worlds/hologram/', import.meta.url);
async function read(file){return fs.readFile(new URL(file, root),'utf8')}
async function pureModule(file){
  return import('data:text/javascript;charset=utf-8,' + encodeURIComponent(await read(file)));
}
const material = await pureModule('hologram-material-v51.js');
const directorMod = await pureModule('hologram-director-v52.js');
const premium = await pureModule('hologram-premium-v5.js');

class Color { constructor(hex){this.hex=hex;} }
class ShaderMaterial {
  constructor(o){Object.assign(this,o);this.isShaderMaterial=true;}
}
const THREE = {
  FrontSide: 'front', NormalBlending: 'normal', AdditiveBlending: 'add',
  SRGBColorSpace: 'srgb', Color, ShaderMaterial,
};
function modelAndScene(){
  const map = {name:'GLB original face texture'};
  const base = {map,isShaderMaterial:false,
    emissive: {set(){}}, color: {multiply(){}}, customProgramCacheKey(){return 'base';},
    clone(){return {...this,emissive:{set(){}},userData:{}}},
    userData:{},
  };
  const mesh={isMesh:true,material:base};
  const scene={model:{traverse(fn){fn(mesh)}},scene:{background:null}};
  return {mesh,base,map,scene};
}
const GLSL={uniforms:{},vertexShader:'#include <common>\n#include <project_vertex>\n',
  fragmentShader:'#include <common>\n#include <opaque_fragment>\n'};

test('pantalla híbrida y ventilador con cara opaca, con comparativas explícitas',()=>{
  assert.equal(material.resolveHologramMode('').mode,'hybrid');
  assert.equal(material.resolveHologramMode('?fan=1').mode,'projection');
  assert.equal(material.resolveHologramMode('?fan=1').face,.96);
  assert.equal(material.resolveHologramMode('?avatar=classic&fan=1').mode,'classic');
  assert.equal(material.resolveHologramMode('?avatar=natural').mode,'natural');
  assert.equal(material.resolveHologramMode('?avatar=hybrid&fan=1').mode,'hybrid');
  assert.equal(material.resolveHologramMode('?fan=1&glow=100').glow,1.8);
});

test('fan establece negro absoluto sin alterar el GLB y mantiene la textura facial',()=>{
  const {scene,mesh,base,map}=modelAndScene();
  const installed=material.installHologramStyle(scene,THREE,'?fan=1');
  assert.equal(installed.mode,'projection');
  assert.equal(scene.scene.background.hex,0);
  assert.notEqual(mesh.material,base);
  assert.equal(mesh.material.map,map);
  assert.equal(mesh.material.transparent,true);
  assert.equal(mesh.material.depthWrite,true);
  const shader={...GLSL,uniforms:{}};
  mesh.material.onBeforeCompile(shader);
  assert.equal(shader.uniforms.uHgOpaqueFace.value,1);
  assert.ok(shader.uniforms.uHgBodyOpacity.value < 1);
  assert.match(shader.fragmentShader,/gl_FragColor\.a\s*=\s*mix\(hgBodyAlpha, uHgOpaqueFace, hgFaceMask\)/);
  assert.match(shader.vertexShader,/vHgWorld/);
  installed.tick(6);
  assert.equal(shader.uniforms.uHgTime.value,6);
});

test('classic preserva radiografía V4 y natural no reemplaza materiales',()=>{
  const classic=modelAndScene();
  material.installHologramStyle(classic.scene,THREE,'?avatar=classic');
  assert.equal(classic.mesh.material.blending,'add');
  const natural=modelAndScene();
  material.installHologramStyle(natural.scene,THREE,'?avatar=natural');
  assert.equal(natural.mesh.material,natural.base);
});

function sceneDirector(){
  let id=0;
  const timers=new Map();
  const logs=[];
  const available=[
    'mIA_IDLE_SAFE','mIA_IDLE_BREATHING','mIA_IDLE_HAPPY',
    'mIA_SEQ_ESCUCHA_ACTIVA','mIA_SEQ_OFRECER_AYUDA','mIA_WAVE_ALT',
    'mIA_SEQ_CONSULTANDO_DATOS','mIA_SEQ_PENSANDO','mIA_SEQ_ESPERA',
    'mIA_SEQ_EXPLICAR_DIAGRAMA','mIA_SEQ_CONFIRMACION','mIA_SEQ_DUDA',
    'mIA_TALK_ALT3','mIA_TALK_ALT2','mIA_SEQ_RESPUESTA_CORTA',
  ];
  const scene={actions:new Map(available.map(n=>[n,{}])),
    play(name,opts){logs.push({name,opts})},
    clipDuration(){return 5},
    stopGesture(){},isFrontFacingClip(){return true},
  };
  const schedule=(cb,ms)=>{const key=++id;timers.set(key,{cb,ms});return key};
  const clearSchedule=(id)=>timers.delete(id);
  const instance=new directorMod.MiaHologramDirectorV52({scene,schedule,clearSchedule});
  return {instance,scene,logs,timers};
}

test('director holograma es propio, no comparte secuencias de inicio con el 3D',()=>{
  const {instance,logs}=sceneDirector();
  instance.enter('greeting');
  assert.ok(['mIA_SEQ_OFRECER_AYUDA','mIA_WAVE_ALT'].includes(logs[0].name));
  assert.notEqual(logs[0].name,'mIA_SEQ_BIENVENIDA');
  assert.equal(logs[0].opts.loop,false);
  instance.enter('idle');
  assert.equal(logs.at(-1).opts.loop,true);
  instance.destroy();
});

test('la escucha, el análisis y la presentación eligen clips distintos',()=>{
  const {instance,logs}=sceneDirector();
  instance.enter('listening');
  const listen=logs.at(-1).name;
  instance.enter('thinking');
  const thinking=logs.at(-1).name;
  instance.enter('presenting',{presentationType:'analytics'});
  const present=logs.at(-1).name;
  assert.equal(listen,'mIA_SEQ_ESCUCHA_ACTIVA');
  assert.equal(thinking,'mIA_SEQ_CONSULTANDO_DATOS');
  assert.equal(present,'mIA_SEQ_EXPLICAR_DIAGRAMA');
  instance.destroy();
});

test('no usa caminatas ni movimientos circulares en modo ventilador',()=>{
  const all=Object.values(directorMod.HOLOGRAM_V52_CLIP_PROFILE).flat();
  assert.ok(all.length>10);
  assert.ok(all.every(c=>!/(WALK|RUN|TURN|CATWALK|CIRCLE)/.test(c)));
});

test('las transiciones cancelan animaciones pendientes, no entran después de destroy',()=>{
  const {instance,logs,timers}=sceneDirector();
  instance.enter('idle');
  assert.equal(timers.size,1);
  instance.enter('speaking');
  assert.equal(timers.size,1);
  const oldCount=logs.length;
  instance.destroy();
  assert.equal(timers.size,0);
  instance.enter('idle');
  assert.equal(logs.length,oldCount);
});

test('el progreso de backend solo inicia pensando una vez',()=>{
  const {instance,logs}=sceneDirector();
  instance.enter('thinking');
  instance.progress();
  assert.equal(logs.length,1);
  assert.equal(instance.enterBackendState('concentrada'),true);
  assert.equal(instance.state,'thinking');
  assert.equal(instance.enterBackendState('unknown'),false);
  instance.destroy();
});

test('saludo y estadísticas no alteran texto ni fabrican números',()=>{
  assert.deepEqual(premium.projectionCopy('¡Hola Enrique! Soy mIA, tu asistente virtual.', 'welcome').headline,'¡Hola Enrique!');
  assert.equal(premium.parseProjectionNumber('2.357,25 €'),2357.25);
  assert.equal(premium.parseProjectionNumber('Sin datos'),null);
});

test('HTML preserva elementos del micrófono manual y añade modo ventilador sin interfaz extra',async()=>{
  const html=await read('index.html');
  const css=await read('hologram-projection-v52.css');
  assert.match(html,/id="mic"/);
  assert.match(html,/id="hgDataPanel"/);
  assert.match(css,/background:#000!important/);
  assert.match(css,/\.hg-fan/);
  assert.match(css,/\.hg-kpi:nth-child\(n\+3\)/);
  assert.match(css,/\.mia-boot\[data-mode="hologram"\]/);
});

test('entrada del holograma exige el clic real y reproduce audio precargado',async()=>{
  const s=await read('main.js');
  assert.match(s,/await boot\.complete\(\{/);
  assert.match(s,/onContinue:\s*\(\)\s*=>\s*\{/);
  assert.match(s,/return welcomeVoice\.replay\(welcomeMessage\)/);
  assert.match(s,/const initialWelcomeAudio = welcomeVoice\.prepare\(welcomeMessage\)/);
  assert.match(s,/new MiaHologramDirectorV52/);
  assert.doesNotMatch(s,/new MiaBehaviorV4/);
  assert.doesNotMatch(s,/welcomeAutostart\.start/);
  assert.match(s,/new MiaVoiceV4/);
  assert.match(s,/voice\?\.cycle\(\)/);
  assert.match(s,/sourceClipCount !== 84/);
  assert.match(s,/await client\.speak/);
  assert.match(s,/renderHologramBrief/);
});

test('ningún archivo del parche modifica 2D, 3D, core o GLB',async()=>{
  const manifest=JSON.parse(await fs.readFile(new URL('../docs/MANIFIESTO_MIA_HOLOGRAMA_V5_2.json',import.meta.url),'utf8'));
  assert.ok(manifest.files.every(f=>f.path.startsWith('src/worlds/hologram/') ||
    f.path.startsWith('tests/') || f.path.startsWith('docs/')));
});
