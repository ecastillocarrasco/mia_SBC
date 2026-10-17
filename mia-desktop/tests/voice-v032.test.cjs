'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const cp=require('node:child_process');
const root=path.resolve(__dirname,'..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');
const {normalizeConfig}=require('../src/config.cjs');

test('tres modos de chat visibles sin inicio automático de transcripción',()=>{
  const html=read('src/ui/bubble.html'),ui=read('src/ui/bubble.js');
  for(const x of ['off','once','conversation'])assert.match(html,new RegExp('<option value="'+x+'"'));
  assert.match(html,/id="micIndicator"/);
  assert.match(ui,/bridge\.setChatMicMode\(mode\)/);
  assert.match(ui,/const epoch=captureEpoch/);
  assert.match(ui,/epoch!==captureEpoch/);
  assert.match(ui,/conversationActive=false/);
});
test('preferencias heredadas no abren el dictado al mostrar a mIA',()=>{
  const cfg=normalizeConfig({autoListenOnWake:true,autoListenOnShow:true,voiceMode:'conversation'});
  assert.equal(cfg.autoListenOnWake,false);
  assert.equal(cfg.autoListenOnShow,false);
  const main=read('src/main.cjs');
  assert.doesNotMatch(main,/willListen.*requestMicrophone/);
  assert.match(main,/const explicitTalk=options\.autoDictate===true && options\.userGesture===true/);
  assert.match(main,/if \(explicitTalk\) requestMicrophone\(\)/);
});
test('apagado detiene motor nativo y confirma el bloqueo en main',()=>{
  const main=read('src/main.cjs'),voice=read('src/voice.cjs');
  assert.match(main,/mia:set-chat-mic-mode/);
  assert.match(main,/speech\.setEnabled\(mode!=='off'\)/);
  assert.match(main,/if\(config\.voiceMode==='off'\)return \{ok:false,code:'MIC_OFF'/);
  assert.match(voice,/if\(disabled\)return Promise\.resolve\(false\)/);
  assert.match(voice,/if\(disabled \|\| generation!==enableGeneration\)/);
});
test('modelos calientes, micrófono cerrado hasta escucha autorizada',()=>{
  const script=read('src/voice/worker.py');
  assert.match(script,/def open_microphone\(\)/);
  assert.match(script,/def close_microphone\(\)/);
  assert.match(script,/close_microphone\(\)\n        active_mode='processing'/);
  assert.match(script,/close_microphone\(\)\n                            emit\('WAKE_PAUSED'\)/);
});
test('simulación de worker: preparado sin abrir micrófono, abre en wake y lo cierra al desactivar',()=>{
  const python=`import sys,types,io,os,tempfile,pathlib,json
sys.path.insert(0,'src/voice')
class Stream:
 started=0;closed=0;opened=0
 def __init__(self,*a,**k): Stream.opened+=1
 def start(self): Stream.started+=1
 def stop(self): pass
 def close(self): Stream.closed+=1
sd=types.ModuleType('sounddevice');sd.RawInputStream=Stream;sys.modules['sounddevice']=sd
np=types.ModuleType('numpy');sys.modules['numpy']=np
v=types.ModuleType('vosk');v.Model=lambda p:object();v.KaldiRecognizer=lambda *a:object();v.SetLogLevel=lambda n:None;sys.modules['vosk']=v
w=types.ModuleType('faster_whisper');w.WhisperModel=lambda *a,**k:object();sys.modules['faster_whisper']=w
vad=types.ModuleType('webrtcvad');vad.Vad=lambda n:object();sys.modules['webrtcvad']=vad
import worker
with tempfile.TemporaryDirectory() as root:
 p=pathlib.Path(root);(p/'vosk-model-small-es-0.42').mkdir();(p/'whisper-base').mkdir();(p/'whisper-base'/'model.bin').write_bytes(b'x')
 sys.argv=['worker.py',root]
 sys.stdin=io.StringIO('\\n'.join([json.dumps({'cmd':'wake','enabled':True}),json.dumps({'cmd':'wake','enabled':False}),json.dumps({'cmd':'shutdown'})])+'\\n')
 assert worker.run()==0
 assert Stream.opened==1,(Stream.opened,Stream.closed)
 assert Stream.closed==1,(Stream.opened,Stream.closed)
`;
  const p=cp.spawnSync('python',['-c',python],{cwd:root,encoding:'utf8',timeout:7000});
  if(p.error?.code==='ENOENT')return;
  assert.equal(p.status,0,p.stderr);
  const types=p.stdout.trim().split(/\r?\n/).filter(Boolean).map(x=>JSON.parse(x).type);
  assert.deepEqual(types.slice(0,3),['READY','WAKE_READY','WAKE_PAUSED']);
});
