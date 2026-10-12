import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { installInlineWorldEntry } from '../src/core/landing-world-entry-v48.js';

const source = (path) => readFileSync(new URL('../'+path, import.meta.url),'utf8');

function setup({ invalidMarkup = false, failStyles = false } = {}) {
  const calls = [], callbacks = new Map();
  const link = {
    href:'https://mia.local/src/worlds/3d/index.html',target:'',
    hasAttribute:()=>false,
    addEventListener:(event, cb)=>callbacks.set(event,cb),
    removeEventListener:(event)=>callbacks.delete(event),
  };
  const landingCSS = { disabled: false };
  const theme = {content:'old'};
  const body = {
    className:'old', dataset:{},
    replaceChildren(...nodes){this.nodes=nodes;calls.push('replace-body');},
  };
  const doc = {
    title:'Landing',body,
    querySelectorAll:() => [{getAttribute:()=> './src/landing.css', ...landingCSS}],
    querySelector:() => theme,
    importNode:(node)=>({...node}),
  };
  const win = {
    history:{pushState(_,__,url){ calls.push('push:'+url); }},
    location:{assign(url){calls.push('fallback:'+url)}},
  };
  let errors=0;
  installInlineWorldEntry({
    link, markup:'<body>world</body>',doc,win,
    parseWorld:()=>({title:'mIA World',body:{childNodes:[{name:'canvas'},{name:'composer'}],className:'world'},
      querySelector:(selector)=>invalidMarkup && selector === '#canvas-root' ? null : {name:selector},
    }),
    loadStyles:async()=>{calls.push('styles');if(failStyles) throw Error('css');},
    loadApp:async()=>{calls.push('app');},
    onError:()=>errors++,
  });
  const click=async (extra={})=>{
    let prevented = false;
    await callbacks.get('click')({button:0,ctrlKey:false,metaKey:false,shiftKey:false,altKey:false,
      preventDefault(){prevented=true;},defaultPrevented:false,...extra});
    return prevented;
  };
  return {click,calls,win,doc,landingCSS,errors:()=>errors};
}

test('Click 3D conserva el documento y carga estilos antes del modulo',async()=>{
  const h=setup();assert.equal(await h.click(),true);
  assert.deepEqual(h.calls,[
    'push:https://mia.local/src/worlds/3d/index.html','replace-body','styles','app']);
  assert.equal(h.doc.body.dataset.miaInlineEntry,'3d');
  assert.equal(h.doc.title,'mIA World');
  assert.equal(h.errors(),0);
});

test('Ctrl+click deja el enlace original sin interceptar',async()=>{
  const h=setup();assert.equal(await h.click({ctrlKey:true}),false);
  assert.deepEqual(h.calls,[]);
});

test('Vuelve al enlace normal si la plantilla falla',async()=>{
  const h=setup({invalidMarkup:true});
  assert.equal(await h.click(),true);
  assert.deepEqual(h.calls,['fallback:https://mia.local/src/worlds/3d/index.html']);
  assert.equal(h.errors(),1);
});

test('Vuelve al enlace normal si CSS falla',async()=>{
  const h=setup({failStyles:true});
  await h.click();
  assert.equal(h.calls.at(-1),'fallback:https://mia.local/src/worlds/3d/index.html');
  assert.equal(h.errors(),1);
});

test('Landing incorpora el entrypoint y mantiene enlaces 2D/HG',()=>{
  const landing=source('index.html');
  assert.match(landing, /src\/landing-3d-v48\.js/);
  assert.match(landing, /href="\.\/mia-2d\.html"/);
  assert.match(landing, /href="\.\/src\/worlds\/hologram\/index\.html"/);
  assert.match(source('src/landing-3d-v48.js'), /worlds\/3d\/index\.html\?raw/);
  assert.match(source('src/landing-3d-v48.js'), /import\('\.\/worlds\/3d\/main\.js'\)/);
});

test('Escribir consulta cancela saludo tardio pendiente',()=>{
  const js=source('src/worlds/3d/main.js');
  assert.match(js, /textLauncher\.addEventListener\("click"/);
  assert.match(js, /welcomeAutostart\?\.pending/);
  assert.match(js, /welcomeVoice\.cancel\(\)/);
});

test('Los botones ocultos de saludo no reaparecen y micro se conserva',()=>{
  const html=source('src/worlds/3d/index.html');
  assert.doesNotMatch(html,/miaWelcomeReplay/);
  assert.match(html,/id="miaMicLauncher"/);
  assert.match(html,/id="mic"/);
});
