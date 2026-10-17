'use strict';
const zlib = require('node:zlib');
const xml = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&apos;').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g,'');
const value = x => x == null ? '' : typeof x === 'object' ? JSON.stringify(x) : String(x);
const csvCell = x => {
  let s = value(x);
  // Excel CSV import can interpret user controlled leading characters as formulas.
  if (/^[\s\uFEFF]*[=+@\-]/.test(s) && typeof x !== 'number') s = "'" + s;
  return '"' + s.replace(/"/g,'""') + '"';
};
function validate(table, rowIndices) {
  if (!table || !Array.isArray(table.columns) || !Array.isArray(table.rows)) throw Error('Tabla no válida.');
  if (table.columns.length > 24 || table.rows.length > 3000) throw Error('Tabla demasiado grande.');
  const indices = rowIndices == null ? table.rows.map((_,i)=>i) : rowIndices;
  if (!Array.isArray(indices) || indices.length > table.rows.length || indices.some(i=>!Number.isInteger(i)||i<0||i>=table.rows.length) || new Set(indices).size !== indices.length) throw Error('Selección de filas no válida.');
  const columns = table.columns.map(c => ({ key:String(c.key).slice(0,100),label:String(c.label||c.key).slice(0,150) }));
  return {columns,rows:indices.map(i=>table.rows[i])};
}
function toCSV(table, rowIndices) {
  const {columns,rows}=validate(table,rowIndices);
  return Buffer.from('\uFEFF' + [columns.map(c=>csvCell(c.label)).join(';'),...rows.map(row=>columns.map(c=>csvCell(row[c.key])).join(';'))].join('\r\n'),'utf8');
}
function crc32(buffer) {
  let c=-1;
  for(const b of buffer){c^=b;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xEDB88320:0);}
  return (c^-1)>>>0;
}
function zip(files) {
  let offset=0;const local=[],central=[];
  for(const [name, content] of Object.entries(files)) {
    const filename=Buffer.from(name,'utf8');const original=Buffer.isBuffer(content)?content:Buffer.from(content,'utf8');
    const packed=zlib.deflateRawSync(original);const crc=crc32(original);
    const head=Buffer.alloc(30);head.writeUInt32LE(0x04034b50,0);head.writeUInt16LE(20,4);head.writeUInt16LE(8,6);head.writeUInt16LE(8,8);head.writeUInt32LE(crc,14);head.writeUInt32LE(packed.length,18);head.writeUInt32LE(original.length,22);head.writeUInt16LE(filename.length,26);
    local.push(head,filename,packed);
    const h=Buffer.alloc(46);h.writeUInt32LE(0x02014b50,0);h.writeUInt16LE(20,4);h.writeUInt16LE(20,6);h.writeUInt16LE(8,8);h.writeUInt16LE(8,10);h.writeUInt32LE(crc,16);h.writeUInt32LE(packed.length,20);h.writeUInt32LE(original.length,24);h.writeUInt16LE(filename.length,28);h.writeUInt32LE(offset,42);central.push(h,filename);
    offset+=head.length+filename.length+packed.length;
  }
  const center=Buffer.concat(central);const end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50,0);end.writeUInt16LE(Object.keys(files).length,8);end.writeUInt16LE(Object.keys(files).length,10);end.writeUInt32LE(center.length,12);end.writeUInt32LE(offset,16);
  return Buffer.concat([...local,center,end]);
}
function columnRef(index){let s='';for(let n=index+1;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function toXLSX(table,rowIndices){
 const {columns,rows}=validate(table,rowIndices);
 const cell=(v,r,c,header=false)=>{
   const address=columnRef(c)+r;
   // All external textual values are inline strings, never formulas or hyperlinks.
   if (!header && typeof v==='number' && Number.isFinite(v)) return `<c r="${address}"><v>${v}</v></c>`;
   if (!header && typeof v==='boolean') return `<c r="${address}" t="b"><v>${v?1:0}</v></c>`;
   return `<c r="${address}" t="inlineStr"${header?' s="1"':''}><is><t xml:space="preserve">${xml(value(v))}</t></is></c>`;
 };
 const records=[`<row r="1">${columns.map((c,j)=>cell(c.label,1,j,true)).join('')}</row>`,...rows.map((record,i)=>`<row r="${i+2}">${columns.map((c,j)=>cell(record[c.key],i+2,j)).join('')}</row>`)].join('');
 const width=Math.max(1,columns.length);const last=columnRef(width-1);
 const sheet=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:${last}${rows.length+1}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><cols>${columns.map((_,i)=>`<col min="${i+1}" max="${i+1}" width="23" customWidth="1"/>`).join('')}</cols><sheetData>${records}</sheetData><autoFilter ref="A1:${last}${rows.length+1}"/></worksheet>`;
 return zip({
  '[Content_Types].xml':`<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`,
  '_rels/.rels':`<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
  'xl/workbook.xml':`<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Datos mIA" sheetId="1" r:id="rId1"/></sheets></workbook>`,
  'xl/_rels/workbook.xml.rels':`<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`,
  'xl/styles.xml':`<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF6A2340"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf xfId="0" numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf xfId="0" numFmtId="0" fontId="1" fillId="2" borderId="0" applyFill="1" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`,
  'xl/worksheets/sheet1.xml':sheet
 });
}
module.exports={toCSV,toXLSX,validate};
