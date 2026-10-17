'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const cp=require('node:child_process');
const voice=require('../src/voice.cjs');
const read=n=>fs.readFileSync(path.join(__dirname,'..',n),'utf8');
test('motor V0.3 no invoca SAPI/PowerShell',()=>{
  assert.doesNotMatch(read('src/voice.cjs'),/spawn\s*\(\s*['"]powershell/i);
  assert.match(read('src/voice.cjs'),/worker\.py/);
});
test('worker local usa micrófono persistente y no sube voz',()=>{
  const src=read('src/voice/worker.py');
  assert.match(src,/RawInputStream/);
  assert.match(src,/local_files_only=True/);
  assert.doesNotMatch(src,/\brequests\.post\b|\.upload\b|urlopen\(/);
  assert.match(src,/collections\.deque\(maxlen=25\)/);
});
test('motor local separa dictado y comandos en protocolo',()=>{
  assert.match(read('src/voice.cjs'),/DICTATION_COMMAND/);
  assert.match(read('src/voice.cjs'),/TRANSCRIPT/);
  assert.match(read('src/main.cjs'),/result\.command/);
  assert.match(read('src/main.cjs'),/speech\.shutdown\(\)/);
});
test('instalador deposita modelos fuera del frontend',()=>{
  const cmd=read('INSTALAR_VOZ_LOCAL.cmd');
  assert.match(cmd,/%APPDATA%/);
  assert.match(cmd,/voice-models/);
  assert.match(read('package.json'),/asarUnpack/);
});
test('la clasificación no convierte preguntas en comandos',()=>{
  const r=cp.spawnSync('python',['-c',`import sys;sys.path.insert(0,'src/voice');import worker; p={'show':'Hola mIA','hide':'Oculta mIA','exit':'Cierra mIA'};tests=[('Hola Mía','SHOW'),('Oye Mia','SHOW'),('Oculta Mia','HIDE'),('Cierra Mia','EXIT'),('Dame la lista de turnos',None),('Mia crea un informe',None)]; assert all(worker.classify(s,p)==cmd for s,cmd in tests)`], {encoding:'utf8'});
  // Python is not required for the base Electron UI and may not be installed in CI.
  if(r.error?.code==='ENOENT')return;
  assert.equal(r.status,0,r.stderr);
});
