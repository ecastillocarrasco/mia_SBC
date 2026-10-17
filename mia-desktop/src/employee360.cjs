'use strict';
// Contrato existente del mundo web: data.presentation.schema =
// mia.employee360.presentation. Nunca reutilizar perfiles de otra identidad.
const { requestedEmployee, getName, isNameMatch } = require('./identity.cjs');
const isObj=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
function view360(prompt, raw){
  const requested=requestedEmployee(prompt);
  const data=isObj(raw?.data)?raw.data:{};
  const original=isObj(data.presentation)?data.presentation:isObj(raw?.presentation)?raw.presentation:null;
  if(!requested||original?.schema!=='mia.employee360.presentation')return null;
  const employee=isObj(data.employee360?.empleado)?data.employee360.empleado:isObj(data.empleado)?data.empleado:null;
  const rootName=getName(employee);
  const heroName=typeof original.hero?.title==='string'?original.hero.title.trim():null;
  // Un título genérico no certifica identidad, incluso si tiene KPI.
  const heroMatched=!!heroName&&isNameMatch(requested,heroName);
  const rootMatched=!!rootName&&isNameMatch(requested,rootName);
  if((rootName&&!rootMatched) || (heroName&&!heroMatched && !rootMatched) || (!rootMatched&&!heroMatched)){
    return {ok:false,code:'EMPLOYEE360_IDENTITY_MISMATCH',message:'La ficha Employee360 recibida no identifica de forma inequívoca a la persona solicitada. No mostraré sus datos.'};
  }
  const sections=Array.isArray(original.sections)?original.sections:[];
  const cards=(Array.isArray(original.kpis)?original.kpis:[])
    .filter(x=>isObj(x) && typeof x.label==='string' && ['string','number','boolean'].includes(typeof x.value))
    .slice(0,16).map(x=>({label:x.label.slice(0,100),value:typeof x.value==='string'?x.value.slice(0,200):x.value,unit:typeof x.unit==='string'?x.unit.slice(0,30):''}));
  const tables=[];
  function flatObject(obj,title){
    if(tables.length>=8 || !isObj(obj))return;
    const rows=[];
    for(const [key,v] of Object.entries(obj)){
      if(!/^[\p{L}\p{N}_ -]{1,90}$/u.test(key))continue;
      if(!['string','number','boolean'].includes(typeof v))continue;
      rows.push({Campo:key.replace(/_/g,' '),Valor:typeof v==='string'?v.slice(0,1200):v});
      if(rows.length>=60)break;
    }
    if(rows.length)tables.push({title,columns:[{key:'Campo',label:'Campo'},{key:'Valor',label:'Valor'}],rows,total:rows.length,received:rows.length,complete:false,truncated:false});
  }
  if(employee)flatObject(employee,'Datos identificativos y profesionales');
  const root=isObj(data.employee360)?data.employee360:data;
  if(isObj(root.datos_laborales))flatObject(root.datos_laborales,'Datos laborales');
  const supported=new Set(['employment','organization','vacations','absence','documents','today','next']);
  for(const section of sections){
    if(!isObj(section)||!supported.has(section.id)||!isObj(section.data))continue;
    if(section.id==='organization'){
      // No generar listados de terceros de la sección de organización.
      const scalar={};for(const [k,v] of Object.entries(section.data))if(['string','number','boolean'].includes(typeof v)&&!/(?:empleados|personas|compa[nñ]eros|responsable_.*nombre)/i.test(k))scalar[k]=v;
      flatObject(scalar,section.title||'Organización');
    }else flatObject(section.data,typeof section.title==='string'?section.title.slice(0,140):'Apartado Employee360');
  }
  const name=rootMatched?rootName:heroName;
  const notice='Ficha Employee360 del backend vinculada a una identidad única. Se muestran los indicadores y campos estructurados disponibles; la completitud de todos los apartados no está garantizada.';
  return {ok:true,name,presentation:{tables,cards,notices:[notice],hasStructuredData:!!(tables.length||cards.length)},code:'EMPLOYEE360_VERIFIED',message:`He recuperado la ficha Employee360 de ${name}. Puedes consultar los apartados recibidos en la ventana de resultados.`};
}
module.exports={view360};
