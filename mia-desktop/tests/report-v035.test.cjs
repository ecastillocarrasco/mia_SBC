'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {extractReport,isReportQuestion,validateDownloadUrl,hasValidSignature,fetchReportFile}=require('../src/report.cjs');
const {extractPresentation}=require('../src/presentation.cjs');
const {sendPrompt}=require('../src/backend.cjs');
const http=require('node:http');
const BASE='http://127.0.0.1:5001';
test('PDF devuelto por motor existente es reconocible sin recrearlo',()=>{
 const r=extractReport({data:{report:{formato:'pdf',nombre_archivo:'Informe_Agosto.pdf',url_descarga:'/api/mia/informes/123/descargar'}}});
 assert.equal(r?.format,'pdf');assert.equal(r?.available,true);
 assert.equal(r?.filename,'Informe_Agosto.pdf');assert.equal(validateDownloadUrl(BASE,r),BASE+'/api/mia/informes/123/descargar');
});
test('PDF en lista de archivos puede ser un enlace con token de origen',()=>{
 const r=extractReport({data:{files:[{filename:'Costes_SBC.pdf',download_url:'/api/mia/reportes/abc?token=opaque'}]}});
 assert.equal(r?.available,true);assert.equal(r?.format,'pdf');
 assert.equal(validateDownloadUrl(BASE,r),BASE+'/api/mia/reportes/abc?token=opaque');
});
test('Sin enlace de descarga no se finge un archivo',()=>{
 const r=extractReport({data:{report:{formato:'pdf',secciones:6,caduca_en_horas:24}}});
 assert.equal(r?.available,false);assert.equal(r?.format,'pdf');
 assert.throws(()=>validateDownloadUrl(BASE,r),/no ha incluido un enlace/);
});
test('Metadatos no son KPIs económicos',()=>{
 const p=extractPresentation({data:{cards:[{label:'Secciones',value:6},{label:'Caduca en horas',value:24},{label:'Coste total',value:125000}]}});
 assert.deepEqual(p.cards.map(x=>x.label),['Coste total']);
});
test('Solo informes explícitos activan el aviso de archivo no entregado',()=>{
 assert.equal(isReportQuestion('informe comparativo gastos agosto 2026 entre todos los departamentos'),true);
 assert.equal(isReportQuestion('dime los turnos del miércoles'),false);
});
test('Enlace externo, file://, credenciales y ruta no API bloqueados',()=>{
 for(const downloadUrl of ['https://otro-servidor.example/api/file','file:///C:/secret.pdf','//example.org/api/file','http://admin:password@127.0.0.1:5001/api/file','/admin/export']){
  assert.throws(()=>validateDownloadUrl(BASE,{format:'pdf',downloadUrl}));
 }
});
test('Archivo falso en JSON, HTML o PDF incompleto no pasa validación',()=>{
 assert.equal(hasValidSignature(Buffer.from('{"error": "not found"}'),'pdf'),false);
 assert.equal(hasValidSignature(Buffer.from('<html>login</html>'),'pdf'),false);
 assert.equal(hasValidSignature(Buffer.from('%PDF-1.7\nbody'),'pdf'),true);
});
test('Descarga GET transmite PDF válido; error HTTP no crea fichero',async()=>{
 const srv=http.createServer((req,res)=>{
  if(req.url==='/api/report/good'){res.writeHead(200,{'Content-Type':'application/pdf'});res.end('%PDF-1.4\nvalid-synthetic-qa');}
  else{res.writeHead(404,{'Content-Type':'application/json'});res.end('{"error":"expired"}');}
 });
 await new Promise(r=>srv.listen(0,'127.0.0.1',r));
 const base='http://127.0.0.1:'+srv.address().port;
 try{
  const ok={format:'pdf',filename:'synthetic.pdf',downloadUrl:'/api/report/good'};
  assert.equal((await fetchReportFile(base,ok)).toString(),'%PDF-1.4\nvalid-synthetic-qa');
  await assert.rejects(()=>fetchReportFile(base,{...ok,downloadUrl:'/api/report/expired'}),/HTTP 404/);
 }finally{srv.close();}
});
test('Enlace sin archivo binario nunca genera éxito',async()=>{
 const srv=http.createServer((_req,res)=>{res.writeHead(200,{'Content-Type':'application/json'});res.end('{"status":"ok"}');});
 await new Promise(r=>srv.listen(0,'127.0.0.1',r));
 try{const base='http://127.0.0.1:'+srv.address().port;await assert.rejects(()=>fetchReportFile(base,{format:'pdf',downloadUrl:'/api/report/download'}),/JSON/);}
 finally{srv.close();}
});
test('Respuesta chat con datos meta no expone PDF falso',async()=>{
 const srv=http.createServer(async(req,res)=>{
  if(req.url==='/api/mia/v4/chat'){
   res.writeHead(200,{'content-type':'application/json'});
   res.end(JSON.stringify({status:'ok',answer:'El informe está listo en PDF. Descárgalo desde la pantalla.',data:{cards:[{label:'Secciones',value:6},{label:'Caduca en horas',value:24}]}}));
  }else{res.writeHead(404);res.end();}
 });
 await new Promise(r=>srv.listen(0,'127.0.0.1',r));
 try{
  const out=await sendPrompt('http://127.0.0.1:'+srv.address().port,'informe comparativo gastos agosto 2026 entre todos los departamentos');
  assert.equal(out.reportPending,true);assert.equal(out.report,null);assert.equal(out.presentation.cards.length,0);
 }finally{srv.close();}
});
test('Respuesta realista con descriptor entregable habilita descargar',async()=>{
 const srv=http.createServer(async(req,res)=>{
  if(req.url==='/api/mia/v4/chat'){
   res.writeHead(200,{'content-type':'application/json'});
   res.end(JSON.stringify({status:'ok',answer:'Informe preparado',data:{cards:[{label:'Secciones',value:6},{label:'Caduca en horas',value:24}],report:{formato:'pdf',filename:'SBC_Agosto_2026.pdf',download_url:'/api/mia/archivos/test/descargar'}}}));
  }else{res.writeHead(404);res.end();}
 });
 await new Promise(r=>srv.listen(0,'127.0.0.1',r));
 try{const out=await sendPrompt('http://127.0.0.1:'+srv.address().port,'informe comparativo de gastos de agosto 2026');
  assert.equal(out.report?.available,true);assert.equal(out.reportPending,false);assert.equal(out.report?.filename,'SBC_Agosto_2026.pdf');
  assert.equal(out.presentation.cards.length,0);
 }finally{srv.close();}
});
test('Ventana Resultados tiene sección documental y control unido a IPC',()=>{
 const fs=require('node:fs'),path=require('node:path');const root=path.join(__dirname,'..');
 const html=fs.readFileSync(path.join(root,'src/ui/results.html'),'utf8');
 const js=fs.readFileSync(path.join(root,'src/ui/results.js'),'utf8');
 const preload=fs.readFileSync(path.join(root,'src/preload.cjs'),'utf8');
 const main=fs.readFileSync(path.join(root,'src/main.cjs'),'utf8');
 for(const id of ['documentSection','documentTitle','documentDescription','documentStatus','downloadReport'])assert.match(html,new RegExp('id="'+id+'"'));
 assert.match(js,/bridge\.downloadReport\(\)/);assert.match(preload,/mia:download-report/);assert.match(main,/ipcMain\.handle\('mia:download-report'/);
});
