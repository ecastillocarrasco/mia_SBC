'use strict';
// Minimal diagnostic telemetry: never serialize prompts, transcripts, answers,
// URLs, authorization headers, file paths, or employee data.
const fs = require('node:fs');
const path = require('node:path');
const MAX_LOG_SIZE = 1024 * 1024;
const VALID_EVENT = /^[a-z][a-z0-9_-]{1,48}$/;
const VALID_CODE = /^[A-Z0-9_-]{1,48}$/;
let directory = null;
let build = '0.2.3';
function init(userDataPath, version = '0.2.3') {
  directory = path.join(userDataPath, 'logs');
  fs.mkdirSync(directory, {recursive:true, mode:0o700});
  build = String(version).slice(0,24);
  record('app_started', {code:'START'});
  return directory;
}
function activeFile(){
  if(!directory)return null;
  const today = new Date().toISOString().slice(0,10);
  const original=path.join(directory,`mia-desktop-${today}.jsonl`);
  try{if(fs.statSync(original).size > MAX_LOG_SIZE)fs.renameSync(original,path.join(directory,`mia-desktop-${today}-${Date.now()}.jsonl`));}catch(e){if(e.code!=='ENOENT')return original;}
  return original;
}
function record(event, fields={}) {
  const file=activeFile();
  if(!file || !VALID_EVENT.test(String(event)))return false;
  const info={ timestamp:new Date().toISOString(), version:build, event:String(event) };
  // Closed allowlist: none of the free-form content from business requests
  // or user audio can ever be added to a diagnostic record.
  if(typeof fields.code==='string' && VALID_CODE.test(fields.code)) info.code=fields.code;
  if(typeof fields.mode==='string' && ['dictate','wake','probe','backend','tts','avatar','ui'].includes(fields.mode))info.mode=fields.mode;
  if(Number.isInteger(fields.exitCode) && fields.exitCode>=-10 && fields.exitCode<=255) info.exitCode=fields.exitCode;
  if(Number.isInteger(fields.httpStatus) && fields.httpStatus>=100 && fields.httpStatus<=599)info.httpStatus=fields.httpStatus;
  if(Number.isFinite(fields.durationMs) && fields.durationMs>=0 && fields.durationMs<600000)info.durationMs=Math.round(fields.durationMs);
  if(Number.isInteger(fields.recognizerCount) && fields.recognizerCount>=0 && fields.recognizerCount<=99)info.recognizerCount=fields.recognizerCount;
  if(typeof fields.available==='boolean')info.available=fields.available;
  try {fs.appendFileSync(file,JSON.stringify(info)+'\n',{encoding:'utf8',mode:0o600});return true;}catch{return false;}
}
function folder(){return directory;}
module.exports={init,record,folder};
