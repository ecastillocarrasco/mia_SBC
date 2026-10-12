import test from 'node:test';
import assert from 'node:assert/strict';
import { HologramVoiceV522 } from '../src/worlds/hologram/hologram-voice-v522.js';

const sleep=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
function audioFake({reject=false,fireEnd=true}={}) {
  const listeners=new Map();
  return {
    pause(){},
    addEventListener(name, fn) {listeners.set(name,fn);},
    removeEventListener(name,fn) {if(listeners.get(name)===fn) listeners.delete(name);},
    play(){
      if(reject)return Promise.reject(new Error('Autoplay blocked'));
      if(fireEnd)setTimeout(()=>listeners.get('ended')?.(),0);
      return Promise.resolve();
    }
  };
}
const audioResponse=(status=200, mime='audio/mpeg')=>({
  ok: status===200, status, headers:{get:()=>mime},
  blob:async()=>new Blob(['audio dummy'],{type:mime}),
});

test('HG usa exclusivamente el mismo endpoint TTS que 3D y reproduce audio backend', async()=>{
  const requests=[];
  let started=0;
  const voice=new HologramVoiceV522({apiBase:'http://127.0.0.1:5001',
    fetchImpl:async(url,opts)=>{requests.push({url,opts});return audioResponse();},
    createAudio:()=>audioFake()});
  const res=await voice.speak('Hola Mía',{onStart:()=>started++});
  assert.equal(res.status,'completed');
  assert.equal(started,1);
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'http://127.0.0.1:5001/api/voice/stream');
  assert.deepEqual(JSON.parse(requests[0].opts.body),{text:'Hola Mía'});
});

test('HG nunca recurre a la voz del navegador si el servidor falla', async()=>{
  let browserCalls=0;
  globalThis.speechSynthesis={speak(){browserCalls++},cancel(){browserCalls++}};
  const warnings=console.warn;
  console.warn=()=>{};
  try {
    const voice=new HologramVoiceV522({fetchImpl:async()=>audioResponse(503),createAudio:()=>audioFake()});
    const res=await voice.speak('Informe de nominas');
    assert.equal(res.status,'voice-http-error');
    assert.equal(res.http,503);
    assert.equal(browserCalls,0);
  } finally {console.warn=warnings;delete globalThis.speechSynthesis;}
});

test('HG detecta HTML inesperado de proxy y no intenta reproducirlo', async()=>{
  const voice=new HologramVoiceV522({fetchImpl:async()=>audioResponse(200,'text/html'),
    createAudio:()=>{throw Error('No debe crearse audio')}});
  const old=console.warn; console.warn=()=>{};
  try {assert.equal((await voice.speak('Hola')).status,'voice-invalid-content-type');}
  finally {console.warn=old;}
});

test('HG respeta bloqueo del navegador sin hablar por SpeechSynthesis', async()=>{
  let browserCalls=0;
  globalThis.speechSynthesis={speak(){browserCalls++},cancel(){browserCalls++}};
  const old=console.warn;console.warn=()=>{};
  try {
    const voice=new HologramVoiceV522({fetchImpl:async()=>audioResponse(),
      createAudio:()=>audioFake({reject:true})});
    assert.equal((await voice.speak('Hola')).status,'playback-blocked');
    assert.equal(browserCalls,0);
  } finally {console.warn=old;delete globalThis.speechSynthesis;}
});

test('HG cancela descarga TTS sin iniciar segundo sintetizador', async()=>{
  let aborts=0;
  const voice=new HologramVoiceV522({fetchTimeoutMs:120,
    fetchImpl:(_url,{signal})=>new Promise((_resolve,reject)=>{
      signal.addEventListener('abort',()=>{aborts++;reject(new Error('Abort'))},{once:true});
    }), createAudio:()=>audioFake()});
  const old=console.warn;console.warn=()=>{};
  try {assert.equal((await voice.speak('Hola')).status,'voice-fetch-timeout');assert.equal(aborts,1);}
  finally {console.warn=old;}
});
