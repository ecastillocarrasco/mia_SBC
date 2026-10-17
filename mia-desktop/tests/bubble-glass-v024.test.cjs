'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root,name),'utf8');
const {computeResizeBounds}=require('../src/bubble-resize.cjs');
const area={x:-1920,y:0,width:1920,height:1040};
const box={x:-1450,y:190,width:500,height:490};
test('glass translúcido real con entrada de texto blanca y zonas que no tapan el avatar',()=>{
 const css=read('src/ui/bubble.css');
 assert.match(css,/background:transparent!important/);
 assert.match(css,/backdrop-filter:blur\(/);
 assert.match(css,/background:#fff!important/);
 assert.match(css,/\.composer\{/);
 assert.match(css,/\.window-grip\[data-resize='e'\]/);
 assert.match(css,/\.resize-handle\[data-resize='se'\]/);
 assert.match(css,/-webkit-app-region:drag/);
 assert.match(css,/-webkit-app-region:no-drag/);
});
test('ventana sin marco dispone de cuatro lados y cuatro esquinas',()=>{
 const html=read('src/ui/bubble.html');
 for (const e of ['n','s','e','w','ne','nw','se','sw']) assert.match(html,new RegExp(`data-resize="${e}"`));
 assert.match(read('src/ui/bubble.js'),/bridge\.resizeBubble\(/);
 assert.match(read('src/main.cjs'),/computeResizeBounds\(/);
});
test('redimensionar al este y sur modifica solamente tamaño',()=>{
 assert.deepEqual(computeResizeBounds(box,area,70,80,'se'),{x:-1450,y:190,width:570,height:570});
 assert.deepEqual(computeResizeBounds(box,area,100,0,'e'),{x:-1450,y:190,width:600,height:490});
 assert.deepEqual(computeResizeBounds(box,area,0,60,'s'),{x:-1450,y:190,width:500,height:550});
});
test('redimensionar por izquierda y arriba ajusta posición conservando ancla opuesta',()=>{
 assert.deepEqual(computeResizeBounds(box,area,-45,-30,'nw'),{x:-1495,y:160,width:545,height:520});
 assert.deepEqual(computeResizeBounds(box,area,35,25,'nw'),{x:-1415,y:215,width:465,height:465});
});
test('límites mínimos y máximos, y protección de zonas externas al monitor',()=>{
 const min=computeResizeBounds(box,area,-1000,-1000,'se');
 assert.equal(min.width,390);assert.equal(min.height,385);
 const max=computeResizeBounds(box,area,2000,2000,'se');
 assert.equal(max.width,1000);assert.equal(max.height,842);
 const near={x:-1910,y:10,width:500,height:490};
 const moved=computeResizeBounds(near,area,-100,-100,'nw');
 assert.equal(moved.x,-1912);assert.equal(moved.y,8);
});
test('cambios incremental no afectan motor informes ni mundos web',()=>{
 assert(!fs.existsSync(path.join(root,'src','worlds')));
 assert(!fs.existsSync(path.join(root,'src','mia','reporting')));
});
