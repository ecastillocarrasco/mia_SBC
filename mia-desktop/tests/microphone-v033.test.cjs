'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
test('el elemento de estado de voz existe y tiene un id HTML bien formado',()=>{
  const html=read('src/ui/bubble.html');
  assert.match(html,/<div id="voiceStatus" class="voice-status" role="status">/);
  assert.doesNotMatch(html,/id="voiceStatus class=/);
});
test('cada getElementById del chat tiene un identificador real en la plantilla',()=>{
  const html=read('src/ui/bubble.html');
  const js=read('src/ui/bubble.js');
  const ids=new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]));
  for(const match of js.matchAll(/document\.getElementById\('([^']+)'\)/g))
    assert.ok(ids.has(match[1]),`El control ${match[1]} no existe en la plantilla HTML`);
});
test('en conversación el botón Detener permanece activo durante escucha',()=>{
  const js=read('src/ui/bubble.js');
  assert.match(js,/mic\.disabled=modeChanging\|\|mode==='off'\|\|answering\|\|\(recognizing&&!conversationActive\)/);
  assert.match(js,/if\(cfg\.voiceMode==='conversation'&&conversationActive\)\{stopConversation\(\)/);
});
test('cuando wake está habilitado no se promete falsamente que el micrófono está inactivo',()=>{
  const main=read('src/main.cjs');
  assert.match(main,/config\.wakePhraseEnabled\?'Solo detección de comandos activa/);
  assert.match(main,/configFile = \(\) => path\.join\(app\.getPath\('userData'\)/);
});
test('instalador portable y modelos de voz fuera del directorio del código',()=>{
  const installer=read('INSTALAR_VOZ_LOCAL.cmd');
  const voice=read('src/voice.cjs');
  assert.match(installer,/cd \/d "%~dp0"/);
  assert.match(installer,/%APPDATA%\\mia-desktop-sbc/);
  assert.match(voice,/path\.join\(root,'voice-models'\)/);
  assert.match(voice,/path\.join\(__dirname,'voice','worker.py'\)/);
});
