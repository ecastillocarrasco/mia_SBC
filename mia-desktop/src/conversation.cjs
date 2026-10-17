'use strict';
// Memoria conversacional efímera. Solo se conserva el nombre inequívoco
// identificado; jamás la ficha ni los registros personales del empleado.
function normalized(text){return String(text||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();}
function safeConversationContext(value){
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  try{const data=JSON.stringify(value);if(data.length>24000)return null;return JSON.parse(data);}
  catch{return null;}
}
function planPrompt(prompt,lastEmployee){
  const text=String(prompt||'').trim();const n=normalized(text);
  if(!lastEmployee||!normalized(lastEmployee).includes(' '))return {message:text};
  // Una fecha aislada es ambigua (nacimiento, alta, antigüedad, ...).
  if(/\bfecha\b/.test(n) && !/\b(nacimiento|alta|baja|incorporacion|contrato|antiguedad)\b/.test(n)
     && /^(?:si[, ]+)?(?:es (?:el|ella)[, ]*)?(?:dame|dime|muestrame|cual)/.test(n)){
    return {clarification:'¿Qué fecha necesitas de esa persona: nacimiento, incorporación u otra?'};
  }
  const asksProfile=/\b(ficha|expediente|perfil)\b/.test(n);
  const refersBack=/\b(su|sus|esa|ese|el|ella|mismo|misma)\b/.test(n) || /^si[, ]/.test(n);
  const explicitName=/(?:ficha|expediente|perfil)\s+(?:completa\s+)?(?:de|del)\s+([a-záéíóúñ]+\s+[a-záéíóúñ]+)/i.test(text);
  if(asksProfile&&refersBack&&!explicitName)return {message:`Dame la ficha completa de ${lastEmployee}.`,contextual:true};
  return {message:text};
}
module.exports={planPrompt,safeConversationContext,normalized};
