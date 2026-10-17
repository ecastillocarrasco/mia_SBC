'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {toCSV,toXLSX,validate}=require('../src/export.cjs');
const source={columns:[{key:'Persona',label:'Persona'},{key:'Puesto',label:'Puesto'},{key:'Salario',label:'Salario'}],rows:[{Persona:'Persona ficticia A',Puesto:'Dirección',Salario:100.25},{Persona:'=1+1',Puesto:'=HYPERLINK("http://bad")',Salario:50},{Persona:'Persona ficticia C',Puesto:'Recepción',Salario:0}],total:25,received:3};
test('exporta CSV seguro para Excel con BOM y sin fórmulas ejecutables',()=>{
 const txt=toCSV(source).toString('utf8');
 assert.match(txt,/^\uFEFF/);assert.match(txt,/"'=1\+1"/);assert.match(txt,/"'=HYPERLINK/);
 assert.match(txt,/"Persona ficticia A"/);
});
test('exporta xlsx OOXML sin dependencias extra',()=>{
 const buf=toXLSX(source);assert(buf.subarray(0,2).equals(Buffer.from('PK')));assert(buf.length>1000);
});
test('solo exporta indices seleccionados y no permite selecciones inválidas',()=>{
 const buf=toCSV(source,[0,2]).toString('utf8');assert(!buf.includes('HYPERLINK'));assert(buf.includes('Recepción'));
 assert.throws(()=>toCSV(source,[999]));assert.throws(()=>validate(source,[0,0]));
});
test('configuración expone saludo, tamaño de ventana y animaciones sin activar escucha automáticamente',()=>{
 const {normalizeConfig}=require('../src/config.cjs');
 const cfg=normalizeConfig({greetingName:'María',bubbleWidth:720,bubbleHeight:600,idleWalkCircle:true,idleBored:true});
 assert.equal(cfg.greetingName,'María');assert.equal(cfg.bubbleWidth,720);assert.equal(cfg.idleBored,true);assert.equal(cfg.wakePhraseEnabled,false);
});
