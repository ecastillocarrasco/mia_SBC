'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const {extractReport,validateDownloadUrl,fetchReportFile}=require('../src/report.cjs');
const {sendPrompt}=require('../src/backend.cjs');

test('Contrato real del backend: presentations type=download con /api/reports/<id>',()=>{
 const r=extractReport({status:'ok',answer:'Ya puedes descargarlo',presentations:[
  {type:'table',title:'Fuente',columns:['a'],rows:[]},
  {type:'download',title:'Gastos agosto 2026',format:'pdf',url:'/api/reports/a1b2c3d4',file_name:'gastos_agosto_2026.pdf'}
 ]});
 assert.equal(r?.available,true);assert.equal(r.format,'pdf');
 assert.equal(r.downloadUrl,'/api/reports/a1b2c3d4');assert.equal(r.filename,'gastos_agosto_2026.pdf');
});
test('La API v4 puede anidar presentaciones en data.presentation.items',()=>{
 const r=extractReport({data:{presentation:{items:[{type:'download',format:'pdf',url:'/api/reports/c9',file_name:'doc.pdf'}]}}});
 assert.equal(r?.available,true);assert.equal(r.downloadUrl,'/api/reports/c9');
});
test('La API de compatibilidad puede devolver actions type=download',()=>{
 const r=extractReport({data:{actions:[{type:'download',format:'pdf',url:'/api/reports/xzy789',label:'PDF'}]}});
 assert.equal(r?.available,true);assert.equal(validateDownloadUrl('http://127.0.0.1:5001',r),'http://127.0.0.1:5001/api/reports/xzy789');
});
test('Primero metadatos, después presentación: prevalece la descarga',()=>{
 const r=extractReport({data:{report:{formato:'pdf',secciones:6,caduca_en_horas:24},presentations:[{type:'download',format:'pdf',url:'/api/reports/actual'}]}});
 assert.equal(r?.available,true);assert.equal(r?.downloadUrl,'/api/reports/actual');
});
test('Rescate del enlace Markdown /api/reports sin inventar URL',()=>{
 const r=extractReport({answer:'Archivos generados y disponibles para descargar:\n- [PDF](/api/reports/abc-123)'});
 assert.equal(r?.available,true);assert.equal(r?.format,'pdf');assert.equal(r?.downloadUrl,'/api/reports/abc-123');
 assert.equal(extractReport({answer:'El PDF está listo, descarga cuando quieras'}),null);
 assert.equal(extractReport({answer:'- [PDF](https://otro-servidor.example/api/reports/abc)'}),null);
});
test('Rechaza acciones falsas, URLs no autorizadas y estados de error',()=>{
 assert.equal(extractReport({actions:[{type:'download',format:'pdf',status:'error',url:'/api/reports/no'}]}),null);
 const r=extractReport({actions:[{type:'download',format:'pdf',url:'https://evil.example/api/reports/id'}]});
 assert.equal(r?.available,true);assert.throws(()=>validateDownloadUrl('http://127.0.0.1:5001',r),/backend corporativo/);
});
test('E2E local: /api/mia/v4/chat ofrece presentation download y GET retorna PDF real',async()=>{
 const srv=http.createServer((req,res)=>{
   if(req.url==='/api/mia/v4/chat'){
     res.writeHead(200,{'content-type':'application/json; charset=utf-8'});
     res.end(JSON.stringify({status:'ok',answer:'Informe listo',data:{presentations:[{type:'download',format:'pdf',url:'/api/reports/test123',file_name:'costes.pdf'}]}}));
   }else if(req.url==='/api/reports/test123'){
     res.writeHead(200,{'content-type':'application/pdf'});res.end('%PDF-1.7\nVALIDO_SINTETICO');
   }else{res.writeHead(404);res.end();}
 });
 await new Promise(r=>srv.listen(0,'127.0.0.1',r));
 const base='http://127.0.0.1:'+srv.address().port;
 try{const result=await sendPrompt(base,'informe comparativo de gastos de agosto 2026 entre departamentos');
  assert.equal(result.report?.available,true);assert.equal(result.reportPending,false);
  const bytes=await fetchReportFile(base,result.report);assert.equal(bytes.toString('utf8'),'%PDF-1.7\nVALIDO_SINTETICO');
 }finally{srv.close();}
});
test('Diagnóstico solo registra presencia/ausencia de enlace, sin incluir URL',()=>{
 const fs=require('node:fs'),path=require('node:path');
 const main=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
 assert.match(main,/report_delivery/);assert.match(main,/LINK_AVAILABLE/);assert.match(main,/LINK_MISSING/);
});
