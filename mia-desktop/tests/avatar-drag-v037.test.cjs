'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {isInWindow,toLocalPoint,shouldIgnoreMouse,nextDragPosition}=require('../src/avatar-pointer.cjs');
const read=p=>fs.readFileSync(path.join(__dirname,'..',p),'utf8');

test('la ventana translúcida detecta el cursor incluso con DPI/múltiples monitores',()=>{
  const b={x:-1340,y:120,width:250,height:345};
  assert.equal(isInWindow({x:-1300,y:200},b),true);
  assert.deepEqual(toLocalPoint({x:-1300,y:200},b),{x:40,y:80});
  assert.equal(isInWindow({x:-1341,y:200},b),false);
  assert.equal(isInWindow({x:-1340,y:465},b),false);
  assert.equal(isInWindow({x:NaN,y:200},b),false);
});

test('ningún cambio de transparencia puede interrumpir un arrastre',()=>{
  assert.equal(shouldIgnoreMouse({dragging:true,inside:true,hit:false}),false);
  assert.equal(shouldIgnoreMouse({dragging:true,inside:false,hit:false}),false);
  assert.equal(shouldIgnoreMouse({dragging:false,inside:true,hit:true}),false);
  assert.equal(shouldIgnoreMouse({dragging:false,inside:true,hit:false}),true);
  assert.equal(shouldIgnoreMouse({dragging:false,inside:false,hit:true}),true);
});

test('la posición del avatar sigue el cursor y respeta los bordes del monitor',()=>{
  const start={x:1000,y:700,width:250,height:345};
  const area={x:0,y:0,width:1920,height:1040};
  assert.deepEqual(nextDragPosition(start,{x:1100,y:800},{x:1250,y:750},area),{x:1150,y:650});
  assert.deepEqual(nextDragPosition(start,{x:1100,y:800},{x:2100,y:1800},area),{x:1670,y:695});
  const left={x:-1440,y:0,width:1440,height:900};
  assert.deepEqual(nextDragPosition({x:-1200,y:200,width:250,height:345},{x:-1100,y:280},{x:-1350,y:60},left),{x:-1440,y:0});
});

test('Electron reevalúa hit-test del cursor global incluso mientras ignora clics',()=>{
  const main=read('src/main.cjs');
  const avatar=read('src/ui/avatar.js');
  const preload=read('src/preload.cjs');
  assert.match(main,/screen\.getCursorScreenPoint\(\)/);
  assert.match(main,/isInWindow\(cursor, bounds\)/);
  assert.match(main,/webContents\.send\('mia:avatar-cursor'/);
  assert.match(preload,/onAvatarCursor: cb => subscribe\('mia:avatar-cursor'/);
  assert.match(avatar,/bridge\.onAvatarCursor\(pos =>/);
  assert.match(avatar,/setPassthrough\(!inCharacterCoords\(pos\?\.x, pos\?\.y\)\)/);
  assert.match(main,/if \(dragSession && ignore\) return;/);
  assert.match(avatar,/bridge\.startDrag\(\)/);
  assert.match(avatar,/bridge\.stopDrag\(\)/);
  assert.doesNotMatch(avatar,/window\.addEventListener\('blur',\s*\(\) => \{drag=null/);
});

test('el título del chat sigue siendo arrastrable y el resize no se altera',()=>{
  const css=read('src/ui/bubble.css');
  assert.match(css,/\.top\{[^}]*-webkit-app-region:drag/);
  assert.match(css,/\.top button\{[^}]*-webkit-app-region:no-drag/);
  assert.match(read('src/ui/bubble.js'),/bridge\.resizeBubble/);
});
