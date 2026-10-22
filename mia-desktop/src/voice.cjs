'use strict';
// mIA V0.3 — offline persistent microphone owner (no PowerShell / SAPI).
// JSONL IPC from a dedicated Python process: content is never sent to logs.
const {spawn} = require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const diagnostics=require('./diagnostics.cjs');
let root=null,worker=null,starting=null,buffer='',pendingDictation=null,awake=null,desiredWake=false,commandConfig={},lastCode='NOT_CONFIGURED',ready=false,startedAt=0;
let initTimer=null, stopping=false,disabled=false,enableGeneration=0;
const MESSAGES={
  DEPENDENCY_MISSING:'Faltan bibliotecas de reconocimiento local. Ejecuta INSTALAR_VOZ_LOCAL.cmd.',
  MODEL_MISSING:'Faltan modelos locales de voz. Ejecuta INSTALAR_VOZ_LOCAL.cmd.',
  MODEL_LOAD_FAILED:'No se pudieron cargar los modelos. Vuelve a instalar los modelos de voz.',
  MICROPHONE_UNAVAILABLE:'No se ha podido abrir el micrófono. Comprueba los permisos de Windows y el dispositivo predeterminado.',
  PYTHON_MISSING:'No existe el entorno local de voz. Ejecuta INSTALAR_VOZ_LOCAL.cmd.',
  WORKER_STOPPED:'El motor de voz local se ha detenido. Consulta Diagnósticos.',
  WORKER_TIMEOUT:'El motor local tardó demasiado en arrancar. Comprueba su instalación.',
  NO_SPEECH:'No se ha detectado voz. Puedes volver a intentarlo.',
  TRANSCRIPTION_FAILED:'La transcripción local falló. Comprueba los modelos de voz.',
  CANCELLED:'Se ha detenido la escucha.',
  MIC_OFF:'El micrófono está desactivado.',
  COMMAND_UNVERIFIED:'No he podido verificar la orden de escritorio. Repítela con claridad o utiliza el botón.'
};
function configure(userDataPath){
  if(typeof userDataPath!=='string'||!path.isAbsolute(userDataPath))throw Error('voice userData requerido');
  root=userDataPath;
}
function workerScript(){
  let p=path.join(__dirname,'voice','worker.py');
  if(p.includes('app.asar'+path.sep))p=p.replace('app.asar'+path.sep,'app.asar.unpacked'+path.sep);
  return p;
}
function pythonPath(){return path.join(root,'voice-runtime','.venv','Scripts','python.exe');}
function modelPath(){return path.join(root,'voice-models');}
function prereqs(){
  if(!root||process.platform!=='win32')return 'NOT_WINDOWS';
  if(!fs.existsSync(pythonPath()))return 'PYTHON_MISSING';
  if(!fs.existsSync(path.join(modelPath(),'vosk-model-small-es-0.42')))return 'MODEL_MISSING';
  if(!fs.existsSync(path.join(modelPath(),'whisper-base','model.bin')))return 'MODEL_MISSING';
  if(!fs.existsSync(workerScript()))return 'WORKER_SCRIPT_MISSING';
  return null;
}
function send(message){if(worker&&ready&&worker.stdin.writable)try{worker.stdin.write(JSON.stringify(message)+'\n');return true;}catch{}return false;}
function settleDictation(value){
  const pending=pendingDictation;pendingDictation=null;
  if(pending){clearTimeout(pending.timer);pending.resolve(value);}
}
function statusError(code){return {ok:false,code,error:MESSAGES[code]||'Error del reconocimiento local. Consulta los diagnósticos.'};}
function fail(code){
  lastCode=code;
  diagnostics.record('speech_local_error',{mode:'wake',code:/^[A-Z0-9_-]+$/.test(code)?code:'WORKER_STOPPED'});
  if(awake?.onStatus)awake.onStatus({active:false,message:statusError(code).error});
  settleDictation(statusError(code));
}
function onMessage(m){
  if(!m||typeof m!=='object')return;
  switch(m.type){
    case 'READY':
      ready=true;lastCode='READY';
      diagnostics.record('speech_local_ready',{mode:'wake',code:'READY',durationMs:Date.now()-startedAt});
      if(starting){clearTimeout(initTimer);initTimer=null;starting.resolve(true);starting=null;}
      if(desiredWake)send({cmd:'wake',enabled:true,phrases:commandConfig});
      break;
    case 'WAKE_READY':
      if(awake?.onStatus)awake.onStatus({active:true,message:'Comandos locales preparados. Puedes hablar.'});
      break;
    case 'COMMAND':
      if(awake?.onCommand&&desiredWake&&['SHOW','HIDE','EXIT'].includes(m.command)){
        // Destructive commands must have independent verification in Python.
        if(m.command!=='SHOW' && m.verified!==true){
          diagnostics.record('voice_command_rejected',{mode:'wake',code:'NOT_VERIFIED'});
          break;
        }
        diagnostics.record('voice_command',{mode:'wake',code:m.command});
        awake.onCommand(m.command);
      }
      break;
    case 'COMMAND_REJECTED':
      if(['HIDE','EXIT'].includes(m.command))
        diagnostics.record('voice_command_rejected',{mode:'wake',code:m.command});
      break;
    case 'DICTATION_READY':
      if(pendingDictation?.onReady)pendingDictation.onReady();
      break;
    case 'SPEECH_DETECTED':
      diagnostics.record('speech_detected',{mode:'dictate',code:'DETECTED',durationMs:pendingDictation?Date.now()-pendingDictation.started:0});
      break;
    case 'TRANSCRIPT':
      if(typeof m.text==='string'&&m.text.length<5000){
        diagnostics.record('speech_transcription',{mode:'dictate',code:'OK',durationMs:pendingDictation?Date.now()-pendingDictation.started:0});
        settleDictation({ok:true,text:m.text,confidence:null,alternatives:[]});
      }else settleDictation(statusError('TRANSCRIPTION_FAILED'));
      break;
    case 'DICTATION_COMMAND':
      if(m.verified===true && ['SHOW','HIDE','EXIT'].includes(m.command))
        settleDictation({ok:true,command:m.command,text:'',confidence:1,alternatives:[]});
      else settleDictation(statusError('COMMAND_UNVERIFIED'));
      break;
    case 'DICTATION_ERROR':
      settleDictation(statusError(m.code in MESSAGES?m.code:'TRANSCRIPTION_FAILED'));
      break;
    case 'ERROR':
      lastCode=typeof m.code==='string'&&/^[A-Z0-9_-]+$/.test(m.code)?m.code:'WORKER_STOPPED';
      break;
  }
}
function ensureWorker(){
  if(disabled)return Promise.resolve(false);
  if(ready&&worker)return Promise.resolve(true);
  if(starting)return starting.promise;
  const missing=prereqs();
  if(missing){lastCode=missing;return Promise.resolve(false);}
  let resolveFn;
  const promise=new Promise(resolve=>resolveFn=resolve);
  starting={promise,resolve:resolveFn};
  startedAt=Date.now();
  try{
    stopping=false;
    const child=spawn(pythonPath(),['-u',workerScript(),modelPath()],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env, PYTHONIOENCODING:'utf-8'}});
    worker=child;ready=false;buffer='';
    // stderr intentionally discarded: can contain paths or model content.
    child.stderr.resume();
    child.stdout.setEncoding('utf8');
    child.stdout.on('data',chunk=>{
      buffer+=chunk;
      if(buffer.length>65536){buffer='';lastCode='WORKER_STOPPED';child.kill();return;}
      let i;
      while((i=buffer.indexOf('\n'))>=0){
        const line=buffer.slice(0,i);buffer=buffer.slice(i+1);
        try{onMessage(JSON.parse(line));}catch{}
      }
    });
    const closed=()=>{
      if(worker!==child)return;
      worker=null;ready=false;
      if(stopping){stopping=false;if(starting){starting.resolve(false);starting=null;}return;}
      clearTimeout(initTimer);initTimer=null;
      const code=lastCode==='READY'?'WORKER_STOPPED':lastCode;
      if(starting){starting.resolve(false);starting=null;}
      fail(code);
    };
    child.once('error',()=>{lastCode='WORKER_STOPPED';closed();});
    child.once('exit',closed);
    initTimer=setTimeout(()=>{if(!ready&&worker===child){lastCode='WORKER_TIMEOUT';child.kill();}},65000);
  }catch{
    worker=null;ready=false;
    if(starting){starting.resolve(false);starting=null;}
    lastCode='WORKER_STOPPED';
  }
  return promise;
}
function watchWake(phrase,onCommand,onStatus,commands={}){
  if(disabled)return {killed:true,kill(){}};
  desiredWake=true;
  commandConfig={show:String(phrase||'Hola mIA'),hide:String(commands.hidePhrase||'Oculta mIA'),exit:String(commands.exitPhrase||'Cierra mIA')};
  const active={onCommand,onStatus,kill(){if(awake===active){awake=null;desiredWake=false;send({cmd:'wake',enabled:false});}}};
  awake=active;
  ensureWorker().then(ok=>{
    if(awake!==active){releaseIdle();return;}
    if(!ok){onStatus({active:false,message:statusError(lastCode).error});return;}
    send({cmd:'wake',enabled:true,phrases:commandConfig});
  });
  return active;
}
function recognizeOnce(_unused,onReady=()=>{}){
  if(disabled)return Promise.resolve(statusError('MIC_OFF'));
  if(pendingDictation)return Promise.resolve({ok:false,code:'MIC_IN_USE',error:'Ya hay un reconocimiento en curso.'});
  return new Promise(async resolve=>{
    const generation=enableGeneration;
    const ok=await ensureWorker();
    if(disabled || generation!==enableGeneration){resolve(statusError('MIC_OFF'));return;}
    if(!ok){resolve(statusError(lastCode));return;}
    desiredWake=false;
    send({cmd:'wake',enabled:false});
    const timer=setTimeout(()=>{
      if(pendingDictation?.resolve===resolve){send({cmd:'cancel'});settleDictation(statusError('WORKER_TIMEOUT'));}
    },45000);
    pendingDictation={resolve,onReady,timer,started:Date.now()};
    send({cmd:'dictate'});
  });
}
function cancelDictation(){if(pendingDictation){send({cmd:'cancel'});settleDictation(statusError('CANCELLED'));}}
async function probe(){
  const missing=prereqs();
  if(missing)return {ok:false,available:false,engine:'offline',code:missing,error:statusError(missing).error};
  const ok=await ensureWorker();
  return {ok,available:ok,engine:'Vosk + faster-whisper',count:ok?2:0,locales:ok?['es-ES']:[],code:ok?'READY':lastCode,error:ok?null:statusError(lastCode).error};
}
function setEnabled(value){disabled=!Boolean(value);enableGeneration++;if(disabled)shutdown();}
function shutdown(){desiredWake=false;awake=null;cancelDictation();stopping=true;if(worker){send({cmd:'shutdown'});worker.kill();worker=null;}ready=false;}
function releaseIdle(){if(!desiredWake && !pendingDictation)send({cmd:'wake',enabled:false});}

module.exports={configure,recognizeOnce,watchWake,cancelDictation,probe,shutdown,releaseIdle,prereqs,setEnabled};
