'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const read=f=>fs.readFileSync(path.join(__dirname,'..',f),'utf8');
test('pantalla resultados premium incluye imagen mIA, marca SBC y resumen de datos recibidos',()=>{
 const html=read('src/ui/results.html');
 for(const id of ['statRows','statTables','statKpis','cards','tables','query','answer','notices'])assert(html.includes(`id="${id}"`));
 assert(html.includes('data-sbc-logo'));
 assert(html.includes('data-mia-logo'));assert(html.includes('mia-wordmark.svg'));
 const css=read('src/ui/results.css');
 for(const cls of ['.hero','.hero-stats','.kpi','.table-card','.chart-panel','.expanded-table'])assert(css.includes(cls));
});
test('gráficos sólo utilizan filas numéricas de la respuesta; hay filtro, orden y exportación',()=>{
 const code=read('src/ui/results.js');
 assert(code.includes('function availableChart(table)'));
 assert(code.includes("typeof row[c.key]==='number'"));
 assert(code.includes('Number.isFinite'));
 assert(code.includes('table.rows.slice(0,12)'));
 assert(code.includes("exportData('csv')"));assert(code.includes("exportData('xlsx')"));
 assert(code.includes('aria-sort'));
 assert(code.includes('search.addEventListener'));
 assert(code.includes('expanded-table'));
 assert(code.includes('el.textContent=String(value)'));
 assert(!code.includes('innerHTML'));
});
