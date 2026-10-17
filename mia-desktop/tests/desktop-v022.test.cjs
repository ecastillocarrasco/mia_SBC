'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const read=x=>fs.readFileSync(path.resolve(__dirname,'..',x),'utf8');
test('saludo de inicio usa modelo GLB y devuelve a reposo',()=>{
 const main=read('src/main.cjs');const avatar=read('src/ui/avatar.js');
 assert(main.includes('mia:startup-greeting'));assert(main.includes('greetingTriggered'));
 assert(avatar.includes("playAnimation('GREET')"));assert(avatar.includes('function stopGreeting()'));
 assert(avatar.includes('bridge.avatarReady()'));
});
test('carga animaciones mIA_WALK_CIRCLE y mIA_SEQ_ESPERA de GLB original',()=>{
 const code=read('src/ui/avatar.js');
 assert(code.includes('mIA_SEQ_ESPERA'));assert(code.includes('mIA_WALK_CIRCLE'));
 assert(code.includes("avatarMode!=='IDLE'"));
});
test('tamaño, arrastre y ventana secundaria resizable realmente conectados al main',()=>{
 const main=read('src/main.cjs');
 assert(main.includes('avatarWin.setBounds({x:'));assert(main.includes("mia:start-drag"));
 assert(main.includes('resizable: true'));assert(main.includes("mia:resize-bubble"));
 assert(read('src/ui/bubble.html').includes('id="resizeBubble"'));
});
test('sistema de dictado no envia de forma automatica de forma predeterminada',()=>{
 const {DEFAULTS}=require('../src/config.cjs');assert.equal(DEFAULTS.autoSendDictation,false);
 assert(read('src/voice/windows-speech.ps1').includes('RESULT'));
 assert(read('src/ui/bubble.js').includes('result.alternatives'));
});
test('branding muestra icono mIA y logo corporativo si esta disponible',()=>{
 for(const file of ['bubble','results','settings']) {
   const t=read('src/ui/'+file+'.html');assert(t.includes('data-sbc-logo'));assert(t.includes('data-mia-logo'));assert(t.includes('mia-wordmark.svg'));
 }
 assert(fs.existsSync(path.join(__dirname,'../assets/mia.ico')));
});
test('exportaciones ofrecen CSV y XLSX por tabla con peticion protegida',()=>{
 const t=read('src/ui/results.js'),main=read('src/main.cjs');
 assert(t.includes("exportData('csv')"));assert(t.includes("exportData('xlsx')"));
 assert(main.includes('ownSender(event,[resultsWin])'));
});
