import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { friendlyProgress } from "../src/core/progress-language-v42.js";
import { MiaWaitingV4, waitMessage } from "../src/core/waiting-v4.js";
import { MiaNarrativeV42 } from "../src/core/narrative-v42.js";
import { MiaBehaviorV4 } from "../src/core/behavior-v4.js";
import { MiaVoiceV4 } from "../src/core/voice-v4.js";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const file = (name) => readFileSync(join(root, name), "utf8");

test("states and technical names become honest natural-language feedback", () => {
  assert.equal(friendlyProgress("analisis_financiero"), "Estamos tramitando tu solicitud.");
  assert.equal(friendlyProgress("consultando_sql"), "Estoy consultando la información que necesitas.");
  assert.equal(friendlyProgress("generando_informe"), "Estoy preparando el informe solicitado.");
  assert.equal(friendlyProgress("/api/tools/sql-server"), "Estamos tramitando tu solicitud.");
  assert.equal(friendlyProgress("consulta_financiera_2026"), "Estamos tramitando tu solicitud.");
  assert.equal(friendlyProgress("Estamos revisando tu petición."),
    "Estamos revisando tu petición.");
  assert.equal(friendlyProgress("La operación continúa en curso."),
    "La operación continúa en curso.");
});

test("wait milestones are natural and honest, also after one minute", () => {
  assert.match(waitMessage(0), /tramitando/);
  assert.match(waitMessage(8), /Sigo con tu consulta/);
  assert.match(waitMessage(19), /continúa en curso/);
  assert.match(waitMessage(36), /tardando un poquito/);
  assert.match(waitMessage(67), /No necesitas repetir/);
  assert.match(waitMessage(125), /Sigo aquí contigo/);
  assert.doesNotMatch(waitMessage(210), /%|finalizado|sql/i);
});

test("backend messages take priority temporarily, and technical names are filtered", () => {
  let now = 1000;
  const seen = [];
  const w = new MiaWaitingV4({
    clock: () => now, interval: 999999,
    onUpdate: text => seen.push(text),
  });
  w.start();
  w.progress("analisis_financiero");
  assert.equal(seen.at(-1), "Estamos tramitando tu solicitud.");
  w.progress("Estamos revisando la solicitud.");
  assert.equal(seen.at(-1), "Estamos revisando la solicitud.");
  now += 11000; w.tick();
  assert.equal(seen.at(-1), "Estamos revisando la solicitud.");
  now += 10000; w.tick();
  assert.match(seen.at(-1), /continúa en curso/);
  w.stop();
  assert.equal(w.active,false);
});

test("narrative shows an editorial scene without putting user text through innerHTML", () => {
  globalThis.requestAnimationFrame = callback => callback();
  globalThis.document = {
    createElement: () => ({
      textContent: "", className: "", attrs: {},
      setAttribute(key,value){this.attrs[key]=value;},
    }),
  };
  const classes = new Set();
  const rootElement = {
    dataset:{}, attrs:{}, children:[],
    classList:{
      add(...xs){ xs.forEach(x=>classes.add(x)); },
      remove(...xs){xs.forEach(x=>classes.delete(x));},
    },
    replaceChildren(...elements){this.children=elements;},
    setAttribute(key,value){this.attrs[key]=value;},
    removeAttribute(key){delete this.attrs[key];},
  };
  const narrative = new MiaNarrativeV42(rootElement);
  narrative.show("<script>alert('x')</script> Estoy revisando tu información.",{kind:"answer"});
  assert.equal(rootElement.children.length,4);
  assert.match(rootElement.children[1].textContent, /<script>/);
  assert.equal(rootElement.dataset.kind,"answer");
  assert.equal(classes.has("is-revealed"),true);
  narrative.clear();
  assert.equal(rootElement.children.length,0);
});

test("idle cycle avoids the odd last motion and dynamically trimmed safe clip", () => {
  const s=file("src/core/behavior-v4.js");
  assert.match(s,/mIA_IDLE_SAFE/);
  assert.doesNotMatch(s,/['"]mIA_WEIGHT_SHIFT['"],/);
  const scene=file("src/core/scene.js");
  assert.match(scene,/AnimationUtils\.subclip/);
  assert.match(scene,/mIA_IDLE_SAFE/);
  assert.match(scene,/isFrontFacingClip/);
});

test("behavior plays a welcome, then idle, and contextual reports", () => {
  const played=[];
  const names=[
    "mIA_SEQ_BIENVENIDA","mIA_IDLE_SAFE","mIA_IDLE_BREATHING",
    "mIA_THINK","mIA_TALK","mIA_SEQ_EXPLICAR_DIAGRAMA",
    "mIA_SEQ_CONSULTANDO_DATOS",
  ];
  const scene = {
    actions:new Map(names.map(x=>[x,true])),
    play:(name,opt)=>played.push({name,opt}),
    stopGesture:()=>{},
    clipDuration:()=>5,
    isFrontFacingClip:()=>true,
  };
  globalThis.window={setTimeout,clearTimeout,matchMedia:()=>({matches:false})};
  const b=new MiaBehaviorV4({scene});
  b.enter("greeting");
  assert.equal(played.at(-1).name,"mIA_SEQ_BIENVENIDA");
  b.enter("idle");
  assert.equal(played.at(-1).name,"mIA_IDLE_SAFE");
  b.enter("presenting",{presentationType:"report"});
  assert.equal(played.at(-1).name,"mIA_SEQ_EXPLICAR_DIAGRAMA");
  b.destroy();
});

test("3D restores microphone buttons, starts only after click and keeps text input", () => {
  const main=file("src/worlds/3d/main.js");
  const html=file("src/worlds/3d/index.html");
  assert.match(main,/new MiaVoiceV4/);
  assert.match(main,/micButton\.addEventListener\("click", micClick\)/);
  assert.match(main,/micLauncher\.addEventListener\("click", micClick\)/);
  assert.doesNotMatch(main,/startIfPreviouslyAllowed|voice\?\.start\(/);
  assert.match(html,/id="mic"/);
  assert.match(html,/id="miaMicLauncher"/);
  assert.match(html,/id="miaTextLauncher"/);
  assert.match(html,/id="miaInteractionDock"[^>]+hidden/);
  assert.match(main,/behavior\.enter\("greeting"\)/);
  assert.match(main,/MiaNarrativeV42/);
  assert.match(main,/if \(data\) \{\s*await revealData/);
  assert.match(main,/enhancePremiumTables\(conversation, \{ pageSize: 20/);
});

test("hologram has manually activated mic and retains concise results", () => {
  const main=file("src/worlds/hologram/main.js");
  const html=file("src/worlds/hologram/index.html");
  assert.match(main,/new MiaVoiceV4/);
  assert.match(main,/micButton\.addEventListener\("click"/);
  assert.doesNotMatch(main,/startIfPreviouslyAllowed|bindMicButton/);
  assert.match(html,/id="mic"/);
  assert.match(main,/new MiaWaitingV4/);
  assert.match(main,/behavior\.enter\("greeting"\)/);
  assert.match(main,/renderHologramBrief/);
});

test("3D white stage and premium narrative are present", () => {
  const css=file("src/worlds/3d/v4-white.css");
  const scene=file("src/core/scene.js");
  assert.match(css, /background:#fff!important/);
  assert.match(css, /mia-narrative-lead/);
  assert.match(css, /mia-narrative-accent/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(scene, /background = 0xffffff/);
  assert.match(scene, /ShadowMaterial/);
  assert.doesNotMatch(scene, /floorVis|0xe8e2d6/);
});

test("tables still enforce no more than 20 rows per page", () => {
  const js=file("src/core/premium-tables.js");
  assert.match(js,/PAGE_SIZE = 20/);
  assert.match(js,/Math\.min\(PAGE_SIZE/);
  assert.match(js,/tbody\.replaceChildren\(\.\.\.rows\.slice/);
});

test("backend voice synthesis remains enabled separately from dictation", () => {
  const main=file("src/worlds/3d/main.js");
  assert.match(main,/client\.speak\(/);
  assert.match(main,/voiceEnabled/);
  assert.match(main,/client\.stopSpeaking\(\)/);
});

test("recognition never starts or requests microphone permission at initialization", () => {
  const oldWindow=globalThis.window;
  const oldDocument=globalThis.document;
  let starts=0,aborts=0;
  class Recognition {
    lang=""; continuous=false; interimResults=false;
    start(){starts+=1;this.onstart?.();}
    abort(){aborts+=1;this.onend?.();}
  }
  globalThis.window={SpeechRecognition:Recognition};
  globalThis.document={hidden:false,addEventListener(){},removeEventListener(){}};
  try {
    const statuses=[];
    const mic=new MiaVoiceV4({onListening:value=>statuses.push(value)});
    assert.equal(starts,0);
    assert.equal(mic.wantsListening,false);
    assert.equal(mic.startIfPreviouslyAllowed(),false);
    assert.equal(starts,0);
    assert.equal(mic.toggle(),'once');
    assert.equal(starts,1);
    assert.equal(mic.listening,true);
    assert.equal(mic.toggle(),'continuous');
    assert.equal(mic.mode,'continuous');
    assert.equal(mic.toggle(),'off');
    assert.equal(mic.listening,false);
    assert.equal(mic.wantsListening,false);
    assert.ok(aborts>=1);
    assert.equal(starts,1);
    mic.destroy();
  } finally {
    globalThis.window=oldWindow;
    globalThis.document=oldDocument;
  }
});

test("one finalized sentence stops listening without rearming after result or visibility", () => {
  const oldWindow=globalThis.window;
  const oldDocument=globalThis.document;
  let starts=0;
  class Recognition {
    start(){starts+=1;this.onstart?.();}
    abort(){this.onend?.();}
  }
  let visibilityChange=null;
  globalThis.window={SpeechRecognition:Recognition};
  globalThis.document={
    hidden:false,
    addEventListener(name,callback){if(name==='visibilitychange') visibilityChange=callback;},
    removeEventListener(){},
  };
  try {
    const phrases=[];
    const mic=new MiaVoiceV4({onFinal:phrase=>phrases.push(phrase)});
    mic.start();
    assert.equal(starts,1);
    mic.recognition.onresult({
      resultIndex:0,
      results:[{isFinal:true,0:{transcript:"¿Qué turnos hay mañana?"}}],
    });
    assert.deepEqual(phrases,["¿Qué turnos hay mañana?"]);
    assert.equal(mic.mode,'once'); // etapa 1 conservada hasta pulsar de nuevo
    assert.equal(mic.suspended,true); // sin captura real de audio
    assert.equal(mic.listening,false);
    mic.resume(); // no rearma la etapa de una pregunta
    visibilityChange();
    assert.equal(starts,1);
    mic.destroy();
  } finally {
    globalThis.window=oldWindow;
    globalThis.document=oldDocument;
  }
});
