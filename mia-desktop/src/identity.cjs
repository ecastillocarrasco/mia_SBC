'use strict';
// This is a *presentation-only* identity gate. Authentication, authorization,
// personal-data filtering and actual employee resolution belong to the backend.
// Never present another person's row or the unverified free-text answer as a
// substitute for a requested employee profile.
const FIELDS=['NombreCompleto','nombreCompleto','nombre_completo','Nombre_Empleado','FullName','Full_Name','EmployeeName','EmpleadoNombre','employee_name','Empleado','Empleada','Persona','Colaborador','name','Nombre'];
const isObj=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
function clean(s){return String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim();}
function requestedEmployee(q){
 const text=String(q||'').trim();
 const m=text.match(/\b(?:ficha(?:\s+(?:completa|personal|laboral))?|expediente|perfil|datos\s+personales)\s+(?:(?:de|del)\s+)?(?:(?:el|la|un|una)\s+)?(?:(?:emplead[oa]|trabajador[ao]|colaborador[ao])\s+(?:de\s+)?)?(.+)$/i);
 if(!m)return null;
 const name=m[1].replace(/\s+(?:por\s+favor|de\s+sunset|en\s+sunset|en\+?\s+sbc|con\s+todos\s+sus\s+datos).*$/i,'').replace(/[?.!,;]+$/,'').trim();
 if(!name||/^(?:completa|personal|laboral|su|sus|este|esta|el|ella)$/i.test(name)||/\b(todos|todas|personal|plantilla|departamento|empleados|trabajadores)\b/i.test(name))return null;
 return name;
}
function getName(row){
 if(!isObj(row))return null;
 // Some SBC repositories split first name and surname into separate columns.
 const first=typeof row.Nombre==='string'?row.Nombre.trim():'';
 const surnames=[row.Apellidos,row.apellidos,row.PrimerApellido,row.Apellido1,row.primer_apellido,row.SegundoApellido,row.Apellido2]
  .filter(x=>typeof x==='string'&&x.trim()).map(x=>x.trim());
 if(first&&surnames.length)return [first,...new Set(surnames)].join(' ');
 for(const key of FIELDS)if(typeof row[key]==='string'&&row[key].trim()&&!/^[0-9]+$/.test(row[key].trim()))return row[key].trim();
 return null;
}
function isNameMatch(requested,actual){
 const wanted=clean(requested),received=clean(actual);
 if(!wanted||!received)return false;
 if(wanted===received)return true;
 // Permit an additional middle/second surname only if there is exactly one
 // matching record. No edit-distance or fuzzy comparison of different names.
 const a=wanted.split(' '),b=received.split(' ');
 if(a.length<2||b.length<a.length||a[0]!==b[0])return false;
 let start=1;
 for(const token of a.slice(1)){
   const index=b.indexOf(token,start);if(index<0)return false;start=index+1;
 }
 return true;
}
function rowsFrom(table){
 if(Array.isArray(table))return table;
 if(!isObj(table))return [];
 for(const key of ['rows','filas','records','registros'])if(Array.isArray(table[key]))return table[key];
 return [];
}
function candidateGroups(raw,presentation){
 const data=isObj(raw)?raw:{};const d=isObj(data.data)?data.data:{};
 const primary=[d.empleado,d.employee,d.persona,d.ficha,d.perfil,d.employee360,d.empleado360,data.employee,data.empleado]
  .filter(isObj).filter(x=>getName(x));
 const tables=[d.table,d.tabla,...(Array.isArray(d.tables)?d.tables:[]),data.table,...(Array.isArray(d.empleados)?[d.empleados]:[]),...(Array.isArray(d.personas)?[d.personas]:[])];
 if(!tables.some(x=>rowsFrom(x).length)&&Array.isArray(presentation?.tables))tables.push(...presentation.tables);
 const tabular=tables.map(rowsFrom).filter(x=>x.length).map(rows=>rows.filter(x=>isObj(x)&&getName(x)));
 return {primary,tabular};
}
function selectedRow(row){
 const value={};
 for(const [key,v] of Object.entries(row)){
   if(!/^[\p{L}\p{N}_ -]{1,100}$/u.test(key))continue;
   if(v===null||['string','number','boolean'].includes(typeof v))value[key]=typeof v==='string'?v.slice(0,1200):v;
 }
 return value;
}
function blocked(code,message){return {ok:false,code,message};}
function resolveEmployeeReply(query,raw,presentation){
 const target=requestedEmployee(query);
 if(target===null)return {ok:true,scope:'general'};
 if(clean(target).split(' ').length<2)return blocked('FULL_NAME_REQUIRED','Indica el nombre y el primer apellido para solicitar una ficha personal.');
 const {primary,tabular}=candidateGroups(raw,presentation);
 if(primary.length){
   const distinct=[...new Set(primary.map(x=>clean(getName(x))))];
   if(distinct.length!==1||!isNameMatch(target,getName(primary[0])))
     return blocked('IDENTITY_MISMATCH','La ficha recibida no tiene una identidad única que coincida con la persona solicitada. No mostraré información de otras personas.');
   // Select only the explicitly identified primary record. Related tables and
   // original narration may refer to other employees and are NOT forwarded.
   return {ok:true,scope:'employee',selection:'PRIMARY_RECORD',row:selectedRow(primary[0])};
 }
 const rows=tabular.flat();
 if(!rows.length)return blocked('IDENTITY_NOT_VERIFIED','El servidor no ha enviado una ficha con identidad comprobable. No mostraré datos personales sin verificar a quién corresponden.');
 const matches=rows.filter(r=>isNameMatch(target,getName(r)));
 if(matches.length!==1)return blocked(matches.length?'AMBIGUOUS_EMPLOYEE':'IDENTITY_MISMATCH',
   matches.length?'El servidor ha devuelto varias posibles coincidencias. Para evitar confusiones, solicita una identificación más precisa.':'El servidor no ha devuelto ningún registro que coincida con la persona solicitada. No mostraré datos de otros empleados.');
 return {ok:true,scope:'employee',selection:'MATCHED_LIST_ROW',row:selectedRow(matches[0])};
}
function verifyEmployeeReply(query,raw,presentation){return resolveEmployeeReply(query,raw,presentation);}
function selectedEmployeePresentation(result){
 if(!result?.ok||result.scope!=='employee')return null;
 const row=result.row;
 const columns=Object.keys(row).slice(0,24).map(k=>({key:k,label:k.replace(/_/g,' ')}));
 if(!columns.length)return null;
 return {tables:[{title:'Registro individual verificado',rows:[row],columns,total:1,received:1,truncated:false,complete:false}],cards:[],notices:[result.selection==='MATCHED_LIST_ROW'?'Coincidencia única localizada en un listado. Esto NO acredita que sea una ficha completa.':'Se presenta únicamente el registro principal identificado, no las tablas de otras personas.'],hasStructuredData:true};
}
module.exports={requestedEmployee,verifyEmployeeReply,resolveEmployeeReply,selectedEmployeePresentation,clean,getName,isNameMatch};
