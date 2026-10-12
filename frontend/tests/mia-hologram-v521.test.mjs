import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const url=new URL('../src/worlds/hologram/hologram-results-v521.js',import.meta.url);
const source=await fs.readFile(url,'utf8');
const {adaptHologramResult:adapt}=await import('data:text/javascript;charset=utf-8,'+encodeURIComponent(source));

const sample = {
  type:'table',title:'Personal trabajando ahora',
  columns:[{key:'nombre',label:'Nombre'},{key:'departamento',label:'Departamento'}],
  rows:[
    {nombre:'Persona A',departamento:'Cocina'},
    {nombre:'Persona B',departamento:'Restaurante'},
    {nombre:'Persona C',departamento:'Mantenimiento'},
  ],
};

test('tabla con filas objeto ya NO se pierde en modo pantalla',()=>{
  const r=adapt({answer:'Personal trabajando en distintos departamentos.'},[sample],{type:'data'});
  assert.equal(r.visible,true);
  assert.match(r.html,/Persona A/);
  assert.match(r.html,/Restaurante/);
  assert.match(r.html,/Mantenimiento/);
  assert.match(r.html,/Registros recibidos/);
  assert.equal(r.counts.rows,3);
});

test('proyección no expone nombres de trabajadores; solo el número recibido',()=>{
  const r=adapt({answer:'Personal trabajando en distintos departamentos.'},[sample],{type:'data',fan:true});
  assert.equal(r.visible,true);
  assert.equal(r.counts.rows,3);
  assert.match(r.html,/Registros recibidos/);
  assert.doesNotMatch(r.html,/Persona [ABC]/);
  assert.doesNotMatch(r.html,/Restaurante/);
  assert.doesNotMatch(r.html,/Cocina/);
});

test('comparativas numéricas recibidas muestran barras sin KPI ficticio',()=>{
  const data={type:'chart',title:'Plantilla por departamento',data:[
    {name:'Restaurante',value:25},{name:'Cocina',value:14},{name:'Mantenimiento',value:8}]};
  const r=adapt({answer:'Comparativa preparada.'},[data],{type:'comparison',fan:true});
  assert.equal(r.visible,true);
  assert.equal(r.counts.rows,3);
  assert.match(r.html,/hg-chart-source/);
  assert.match(r.html,/Restaurante/);
  assert.doesNotMatch(r.html,/Registros recibidos/);
});

test('tabla agregada por departamento se convierte en comparación trazable en fan',()=>{
  const agg={type:'table',title:'Por departamentos',columns:['Departamento','Personas'],
    rows:[['Cocina',14],['Mantenimiento',7],['Restaurante',25]]};
  const r=adapt({answer:'Comparativa de personal.'},[agg],{type:'comparison',fan:true});
  assert.match(r.html,/hg-chart-source/);
  assert.doesNotMatch(r.html,/Registros recibidos/);
});

test('tabla de datos personales con cifras no crea gráfica de datos sensibles en fan',()=>{
  const privateRecords={type:'table',columns:['Nombre','Edad'],rows:[['Persona A',47],['Persona B',34]]};
  const r=adapt({answer:'Dos registros recibidos.'},[privateRecords],{type:'person',fan:true});
  assert.doesNotMatch(r.html,/Persona A/);
  assert.doesNotMatch(r.html,/hg-chart-source/);
  assert.match(r.html,/Registros recibidos/);
});

test('dashboard de KPIs muestra valores reales',()=>{
  const p={type:'dashboard',kpis:[{label:'Consultas',value:113},{label:'Resolución',value:83.5,unit:'%'}]};
  const r=adapt({},[p],{type:'analytics',fan:true});
  assert.match(r.html,/113/);
  assert.match(r.html,/83,5/);
  assert.match(r.html,/%/);
  assert.equal(r.counts.metrics,2);
});

test('documento recibido tiene respuesta visual aunque no exista KPI',()=>{
  const r=adapt({answer:'He generado un documento.'},[{type:'download',url:'/api/reports/annual.pdf',title:'Informe'}],{type:'document',fan:true});
  assert.equal(r.visible,true);
  assert.match(r.html,/RESULTADO DISPONIBLE/);
  assert.doesNotMatch(r.html,/href=/);
});

test('presentación chart sin información numérica muestra estado y no inventa números',()=>{
  const r=adapt({answer:'No hay datos para generar una gráfica.'},[{type:'chart',data:[{x:'Ene',value:null},{x:'Feb',value:'—'}]}],{type:'analytics',fan:true});
  assert.equal(r.visible,true);
  assert.match(r.html,/RESULTADO DISPONIBLE/);
  assert.equal(r.counts.metrics,0);
});

test('respuesta puramente conversacional no añade tarjetas innecesarias',()=>{
  const r=adapt({answer:'Hola. ¿Qué necesitas?'},[],{type:'conversation'});
  assert.equal(r.visible,false);
  assert.equal(r.html,'');
});

test('una tabla Markdown recibida únicamente en texto también se presenta',()=>{
  const answer='Estos son los datos:\n| Departamento | Total |\n|---|---|\n| Cocina | 7 |\n| Restaurante | 13 |';
  const r=adapt({answer},[],{type:'comparison'});
  assert.equal(r.visible,true);
  assert.match(r.html,/Restaurante/);
  assert.equal(r.counts.rows,2);
});

test('se escapan los contenidos HTML del backend',()=>{
  const x={type:'table',columns:['Departamento','Total'],rows:[['<script>alert(1)</script>',15]]};
  const r=adapt({},[x],{type:'data'});
  assert.doesNotMatch(r.html,/<script>/);
  assert.match(r.html,/&lt;script&gt;/);
});

test('sin datos ni respuesta devuelve estado vacío, no crea métricas',()=>{
  const r=adapt({},[],{type:'analytics',fan:true});
  assert.equal(r.visible,false);
  assert.deepEqual(r.counts,{metrics:0,rows:0,docs:0});
});

test('el flujo main conserva la respuesta aunque falle la reproducción de voz',async()=>{
  const main=await fs.readFile(new URL('../src/worlds/hologram/main.js',import.meta.url),'utf8');
  assert.match(main,/adaptHologramResult/);
  assert.match(main,/try\s*\{\s*await client\.speak/);
  assert.match(main,/datos conservados/);
  assert.match(main,/premiumStage\.dataVisible\(Boolean\(resultEl\.textContent/);
  assert.match(main,/new MiaHologramDirectorV52/);
  assert.match(main,/voice\?\.cycle\(\)/);
});
