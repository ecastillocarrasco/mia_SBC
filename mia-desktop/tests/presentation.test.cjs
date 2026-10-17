'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {extractPresentation}=require('../src/presentation.cjs');
test('lista de personas y puestos se convierte en tabla visible completa cuando ha llegado completa',()=>{
 const r=extractPresentation({answer:'Se muestra en pantalla',data:{table:{title:'Personas y puestos',columns:[{key:'Persona',label:'Persona'},{key:'Puesto',label:'Puesto'}],rows:[{Persona:'Persona sintética A',Puesto:'Administración'},{Persona:'Persona sintética B',Puesto:'Recepción'}],total:2}}});
 assert.equal(r.tables.length,1);assert.equal(r.tables[0].rows[1].Puesto,'Recepción');assert.equal(r.tables[0].total,2);
});
test('respuesta solo narrativa NO finge que trae tabla',()=>{
 const r=extractPresentation({answer:'La lista completa se muestra en pantalla',data:{}});
 assert.equal(r.tables.length,0);assert.equal(r.hasStructuredData,false);
});
test('soporta arrays de entidades sin esquema table y tarjetas',()=>{
 const r=extractPresentation({data:{empleados:[{Nombre:'Prueba A',Puesto:'RRHH'}],cards:[{label:'Personas',value:1}]}});
 assert.equal(r.tables[0].rows[0].Puesto,'RRHH');assert.equal(r.cards[0].value,1);
});
test('no presume que listado parcial es completo',()=>{
 const r=extractPresentation({data:{table:{rows:[{Empleado:'A'}],total:25}}});
 assert.equal(r.tables[0].total,25);assert.ok(r.notices.some(x=>x.includes('solo ha enviado 1')));
});
test('no introduce HTML en la vista, limita celdas enormes y evita metadatos',()=>{
 const r=extractPresentation({data:{rows:[{nombre:'<img onerror=x>',observacion:'a'.repeat(2000)}],sources:[{url:'https://...'}]}});
 assert.equal(r.tables[0].rows[0].nombre,'<img onerror=x>');assert.equal(r.tables[0].rows[0].observacion.length,1200);
 assert.equal(r.tables.length,1);
});
test('limita filas con aviso explícito',()=>{
 const r=extractPresentation({data:{table:{rows:Array.from({length:3002},(_,i)=>({i}))}}});
 assert.equal(r.tables[0].rows.length,3000);assert.ok(r.tables[0].truncated);assert.ok(r.notices.length>0);
});
test('mIA provisional no está presente en el arranque 3D',()=>{
 const fs=require('node:fs');const path=require('node:path');
 const html=fs.readFileSync(path.join(__dirname,'../src/ui/avatar.html'),'utf8');
 assert.doesNotMatch(html,/preview\.svg|id="fallback"|VISTA PROVISIONAL/i);
});
test('configuración ofrece voz Windows como respaldo identificable',()=>{
 const {normalizeConfig}=require('../src/config.cjs');
 assert.equal(normalizeConfig({}).voiceFallbackEnabled,true);
 assert.equal(normalizeConfig({voiceFallbackEnabled:false}).voiceFallbackEnabled,false);
});
