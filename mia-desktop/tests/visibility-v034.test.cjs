'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const cp=require('node:child_process');
const read=p=>fs.readFileSync(path.join(__dirname,'..',p),'utf8');

test('no hay ocultación por atajo de teclado ni por Escape',()=>{
  const main=read('src/main.cjs'),avatar=read('src/ui/avatar.js'),bubble=read('src/ui/bubble.js');
  assert.match(main,/globalShortcut\.register\(shortcut, \(\) => \{[\s\S]*?openBubble\(\);/);
  assert.doesNotMatch(main,/else if \(bubbleWin && bubbleWin\.isVisible\(\)\) hideAvatar\(/);
  assert.doesNotMatch(avatar,/Escape[^\n]*hideAvatar/);
  assert.doesNotMatch(bubble,/Escape[^\n]*hideBubble/);
});
test('sólo llamadas explícitas y voz validada pueden ocultar el avatar',()=>{
  const main=read('src/main.cjs');
  assert.match(main,/const HIDE_REASONS=new Set/);
  assert.match(main,/function hideAvatar\(reason\) \{[\s\S]*?HIDE_REASONS\.has\(reason\)/);
  assert.match(main,/REJECTED_UNAUTHORIZED_HIDE/);
  assert.match(main,/hideAvatar\('VOICE_VERIFIED'\)/);
  assert.match(main,/hideAvatar\('CHAT_MINIMIZE'\)/);
  assert.match(main,/hideAvatar\('TRAY_MINIMIZE'\)/);
  assert.match(main,/diagnostics\.record\('visibility_change',\{mode:'avatar',code:reason\}\)/);
  assert.doesNotMatch(main,/\bhideAvatar\(\)/);
});
test('Vosk nunca puede ocultar ni cerrar desde un resultado parcial',()=>{
  const worker=read('src/voice/worker.py'),voice=read('src/voice.cjs');
  assert.match(worker,/if cmd == 'SHOW':/);
  assert.match(worker,/confirm_destructive_command\(cmd,list\(wake_audio\),configured,transcriber,np\)/);
  assert.match(worker,/emit\('COMMAND',command=cmd,verified=True\)/);
  assert.match(voice,/m\.command!=='SHOW' && m\.verified!==true/);
  assert.match(worker,/COMMAND_REJECTED/);
});
test('doble confirmación con audio sintético, silencio y reconocedor independiente',()=>{
  const code=String.raw`
import sys,math
import numpy as np
from types import SimpleNamespace
sys.path.insert(0,'src/voice')
import worker
phrases={'show':'Hola mIA','hide':'Oculta mIA','exit':'Cierra mIA'}
samples=(np.sin(np.linspace(0,150*math.pi,16000))*.2*32767).astype(np.int16)
frames=[samples[i:i+320].tobytes() for i in range(0,len(samples),320)]
class FakeWhisper:
 def __init__(self,text): self.text=text
 def transcribe(self,*a,**kw):return iter([SimpleNamespace(text=self.text)]),None
assert worker.confirm_destructive_command('HIDE',frames,phrases,FakeWhisper('Oculta mIA'),np)
assert not worker.confirm_destructive_command('HIDE',frames,phrases,FakeWhisper('Dame los turnos'),np)
assert not worker.confirm_destructive_command('EXIT',frames,phrases,FakeWhisper('Oculta mIA'),np)
assert not worker.confirm_destructive_command('SHOW',frames,phrases,FakeWhisper('Hola mIA'),np)
assert not worker.confirm_destructive_command('HIDE',frames[:5],phrases,FakeWhisper('Oculta mIA'),np)
silence=[np.zeros(320,dtype=np.int16).tobytes() for _ in range(45)]
assert not worker.confirm_destructive_command('HIDE',silence,phrases,FakeWhisper('Oculta mIA'),np)
class ErrorWhisper:
 def transcribe(self,*a,**kw):raise RuntimeError('fake')
assert not worker.confirm_destructive_command('HIDE',frames,phrases,ErrorWhisper(),np)
`;
 const p=cp.spawnSync('python',['-c',code],{cwd:path.join(__dirname,'..'),encoding:'utf8',timeout:10000});
 if(p.error?.code==='ENOENT'||(p.status!==0&&/No module named 'numpy'/.test(p.stderr)))return;
 assert.equal(p.status,0,p.stderr);
});

test('los comandos provenientes del dictado también necesitan doble confirmación',()=>{
  const voice=read('src/voice.cjs'),worker=read('src/voice/worker.py');
  assert.match(worker,/confirm_dictation_command\(cmd,dictation_frames,configured,wake_model,KaldiRecognizer\)/);
  assert.match(worker,/emit\('DICTATION_COMMAND', command=cmd, verified=True\)/);
  assert.match(voice,/case 'DICTATION_COMMAND':\n      if\(m\.verified===true/);
  assert.match(worker,/code='COMMAND_UNVERIFIED'/);
});
