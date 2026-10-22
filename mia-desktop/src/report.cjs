'use strict';
// V0.3.5: Desktop SOLO distribuye los documentos del motor único mIA SBC.
// Nunca genera informes, recalcula datos, ni inventa URL de descarga.
const FORMATS = Object.freeze({
  pdf: {mime:'application/pdf', maxBytes:40*1024*1024},
  xlsx: {mime:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',maxBytes:40*1024*1024},
  pptx: {mime:'application/vnd.openxmlformats-officedocument.presentationml.presentation',maxBytes:40*1024*1024},
  html: {mime:'text/html',maxBytes:15*1024*1024}
});
const object = v => !!v && typeof v==='object' && !Array.isArray(v);
const str = v => typeof v==='string'?v.trim():'';
const urlFields=['download_url','downloadUrl','url_descarga','descarga_url','file_url','fileUrl','archivo_url','href','url','enlace_descarga'];
const nameFields=['filename','file_name','nombre_archivo','nombre','name'];
function normalizeFormat(value){const s=str(value).toLowerCase().replace(/^\./,'');if(FORMATS[s])return s; if(s.includes('application/pdf'))return 'pdf';if(s.includes('spreadsheetml'))return 'xlsx';if(s.includes('presentationml'))return 'pptx';if(s==='text/html')return 'html';return '';}
function inferFormat(value){const t=str(value).split(/[?#]/,1)[0].toLowerCase();return normalizeFormat((t.match(/\.([a-z]{3,4})$/)||[])[1]);}
function safeFilename(value,fmt){const raw=str(value).split(/[\\/]/).pop().replace(/[<>:"|?*\x00-\x1f]/g,'_').replace(/^\.+/,'').slice(0,125);const name=raw||'Informe_mIA_SBC';return name.toLowerCase().endsWith('.'+fmt)?name:name.replace(/\.(pdf|xlsx|pptx|html)$/i,'')+'.'+fmt;}
// The SBC report engine's actual contract is a presentation with
// {type:'download',format:'pdf',url:'/api/reports/<id>'}.  V0.3.5 did not
// inspect `presentations` or `actions`, and silently discarded that artifact.
const containerFields = Object.freeze([
 'data','result','resultado','output','tool_result','payload',
 'presentations','presentation','actions','items','downloads',
 'report','informe','artifact','artefacto','document','documento',
 'file','archivo','report_file','generated_report','reporting',
 'reports','informes','artifacts','artefactos','documents','documentos',
 'files','archivos','attachments','adjuntos','generated_files'
]);
function reportCandidates(reply){
 const seen=new WeakSet(),found=[];let scanned=0;
 function visit(obj,depth){
   if(depth>6 || ++scanned>250)return;
   if(Array.isArray(obj)){for(const item of obj.slice(0,30))visit(item,depth+1);return;}
   if(!object(obj)||seen.has(obj))return;
   seen.add(obj);
   const type=str(obj.type||obj.action||obj.kind).toLowerCase();
   const href=urlFields.map(k=>str(obj[k])).find(Boolean)||'';
   const format=normalizeFormat(obj.format||obj.formato||obj.mime_type||obj.mime)||
     inferFormat(href)||inferFormat(nameFields.map(k=>str(obj[k])).find(Boolean)||'');
   if(type==='download' || type==='report_download' || (href && format) ||
      (format && ('caduca_en_horas' in obj || 'secciones' in obj || 'filename' in obj)))found.push(obj);
   for(const key of containerFields){if(obj[key] && typeof obj[key]==='object')visit(obj[key],depth+1);}
 }
 visit(reply,0);
 return found;
}
function reportFromItem(item){
 const href=urlFields.map(k=>str(item[k])).find(Boolean)||'';
 const rawFormat=item.format||item.formato||item.mime_type||item.mime||item.content_type||'';
 const filename=nameFields.map(k=>str(item[k])).find(Boolean)||'';
 const fmt=normalizeFormat(rawFormat)||inferFormat(filename)||inferFormat(href)||
  // Some v4 action wrappers only expose a labelled download action.
  (/\bpdf\b/i.test(str(item.label||item.title||item.titulo))?'pdf':
   /\b(excel|xlsx)\b/i.test(str(item.label||item.title||item.titulo))?'xlsx':
   /\b(pptx|powerpoint|power point)\b/i.test(str(item.label||item.title||item.titulo))?'pptx':'');
 if(!FORMATS[fmt])return null;
 if(item.ok===false || ['error','failed','denied','forbidden'].includes(str(item.status).toLowerCase()))return null;
 const title=str(item.title||item.titulo||item.label)||filename||('Informe '+fmt.toUpperCase());
 return {format:fmt,title:title.slice(0,140),filename:safeFilename(filename||title,fmt),downloadUrl:href.slice(0,3000),available:!!href};
}
function reportFromMarkdown(reply){
 const texts=[reply?.answer,reply?.natural_answer,reply?.response,
   reply?.data?.answer,reply?.data?.natural_answer,reply?.data?.response].filter(x=>typeof x==='string');
 for(const value of texts){
  // Backend delivery contract may return a Markdown link when actions are stripped
  // by a compatibility gateway. Never interpret unrelated links as documents.
  const pattern=/\[\s*(PDF|Power\s*Point|PPTX|Excel|XLSX)\s*\]\(\s*(\/api\/reports\/[a-zA-Z0-9._~-]+(?:\?[a-zA-Z0-9._~%=&-]+)?)\s*\)/gi;
  let match;
  while((match=pattern.exec(value))){
    const fmt=/^pdf$/i.test(match[1])?'pdf':/^excel$|^xlsx$/i.test(match[1])?'xlsx':'pptx';
    return {format:fmt,title:'Informe '+match[1],filename:safeFilename('Informe_mIA_SBC',fmt),downloadUrl:match[2],available:true};
  }
 }
 return null;
}
function extractReport(reply){
 const options=reportCandidates(reply).map(reportFromItem).filter(Boolean);
 // Downloadable reports have priority over metadata-only report descriptions.
 // An action may come after a summary in a v4 response.
 const available=options.find(item=>item.available);
 return available||reportFromMarkdown(reply)||options[0]||null;
}
function isReportQuestion(q){return /\b(informe|report|reporte|pdf|powerpoint|presentaci[oó]n|xlsx|excel)\b/i.test(str(q));}
function validateDownloadUrl(base,report){
 if(!report || !FORMATS[report.format] || !str(report.downloadUrl))throw Error('El backend no ha incluido un enlace de descarga del informe.');
 const origin = new URL(base);
 if(origin.username||origin.password||origin.search||origin.hash || (origin.protocol!=='https:'&&!['127.0.0.1','localhost','[::1]'].includes(origin.hostname)))throw Error('Servidor de informes no autorizado.');
 const raw=str(report.downloadUrl);
 if(raw.startsWith('//') || raw.startsWith('\\') || /[\x00-\x1f]/.test(raw))throw Error('Enlace de informe no válido.');
 const target=new URL(raw,origin.origin+'/');
 if(target.origin!==origin.origin || target.username || target.password || !['http:','https:'].includes(target.protocol))throw Error('El informe debe descargarse desde el backend corporativo configurado.');
 if(!target.pathname.startsWith('/api/'))throw Error('La ruta de descarga no es un endpoint API autorizado.');
 return target.toString();
}
function hasValidSignature(bytes,format){
 if(format==='pdf')return bytes.subarray(0,5).toString('latin1')==='%PDF-';
 if(format==='xlsx'||format==='pptx')return bytes.length>=4 && bytes[0]===0x50 && bytes[1]===0x4b && bytes[2]===0x03 && bytes[3]===0x04;
 if(format==='html')return /^\s*(?:<!doctype html|<html)\b/i.test(bytes.subarray(0,512).toString('utf8'));
 return false;
}
async function fetchReportFile(base,report,fetchImpl=fetch){
 const url=validateDownloadUrl(base,report), max=FORMATS[report.format].maxBytes;
 const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),90000);
 try{
  const res=await fetchImpl(url,{method:'GET',redirect:'error',signal:ctrl.signal,headers:{Accept:FORMATS[report.format].mime}});
  if([401,403].includes(res.status))throw Error('No tienes autorización para descargar este informe.');
  if(!res.ok)throw Error('El backend no permite descargar el archivo (HTTP '+res.status+').');
  const declared=Number(res.headers.get('content-length'));
  if(declared>max)throw Error('El informe supera el límite de descarga del cliente.');
  const ct=(res.headers.get('content-type')||'').toLowerCase();
  if(ct.includes('application/json'))throw Error('El servidor ha respondido con JSON, no con un archivo.');
  const parts=[];let total=0;
  if(!res.body?.getReader)throw Error('El servidor no ha transmitido el contenido del archivo.');
  const reader=res.body.getReader();
  try{for(;;){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>max)throw Error('El archivo supera el máximo permitido.');parts.push(Buffer.from(value));}}
  catch(e){await reader.cancel().catch(()=>{});throw e;}
  const bytes=Buffer.concat(parts,total);
  if(!bytes.length || !hasValidSignature(bytes,report.format))throw Error('El archivo recibido no coincide con el formato anunciado.');
  return bytes;
 }finally{clearTimeout(timer);}
}
module.exports={extractReport,isReportQuestion,validateDownloadUrl,hasValidSignature,fetchReportFile,safeFilename};
