'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {init,record,folder}=require('../src/diagnostics.cjs');
const source=path.join(__dirname,'../src/voice/windows-speech.ps1');
test('diagnósticos nunca guardan texto del usuario, rutas, tokens ni respuestas',()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'mia-diag-test-'));
 try{
   init(tmp,'0.2.3');
   const secret='Nombre Apellido nómina confidencial TOKENSECRET';
   assert.equal(record('speech_test',{code:'NO_ES_RECOGNIZER',mode:'dictate',text:secret,transcription:secret,prompt:secret,answer:secret,path:'C:\\secret',token:secret,httpStatus:503,exitCode:2}),true);
   const data=fs.readdirSync(folder()).map(f=>fs.readFileSync(path.join(folder(),f),'utf8')).join('');
   assert(!data.includes(secret));assert(!data.includes('token'));assert(!data.includes('C:\\secret'));
   assert(data.includes('NO_ES_RECOGNIZER'));assert(data.includes('503'));
 }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});
test('PowerShell tiene diagnóstico SAPI, informa codigos y usa constructor UTF8 correcto',()=>{
 const script=fs.readFileSync(source,'utf8');
 assert(script.includes("'probe','wake','dictate'"));
 assert(script.includes("[System.Text.UTF8Encoding]::new($false)"));
 assert(script.includes('NO_ES_RECOGNIZER'));
 assert(script.includes('NO_MICROPHONE'));
 assert(!script.includes('New-Object System.Text.UTF8Encoding'));
});
test('interfaz permite logotipo real, diagnóstico de voz y abrir carpeta de logs',()=>{
 const main=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
 const settings=fs.readFileSync(path.join(__dirname,'../src/ui/settings.html'),'utf8');
 for(const x of ['mia:probe-voice','mia:open-diagnostics','mia:pick-mia-logo'])assert(main.includes(x));
 for(const x of ['id="probeVoice"','id="openLogs"','id="chooseMiaLogo"'])assert(settings.includes(x));
});
