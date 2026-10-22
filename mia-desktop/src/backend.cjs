'use strict';
const { normalizeBackendUrl } = require('./config.cjs');
const auth = require('./auth.cjs');
const { extractPresentation } = require('./presentation.cjs');
const { resolveEmployeeReply, selectedEmployeePresentation, getName, requestedEmployee } = require('./identity.cjs');
const { planPrompt, safeConversationContext, normalized } = require('./conversation.cjs');
const { view360 } = require('./employee360.cjs');
const {extractReport,isReportQuestion,validateDownloadUrl} = require('./report.cjs');
async function requestWithTimeout(url, opts, timeoutMs = 35000) {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try { return await fetch(url, { ...opts, redirect: 'error', signal: ctrl.signal }); }
  finally { clearTimeout(id); }
}
async function authHeaders() {
  const token = await auth.getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
function endpoint(base, pathname) {
  const checked = normalizeBackendUrl(base);
  if (checked !== base) throw Error('La dirección del backend no es válida.');
  return checked + pathname;
}
async function sendPrompt(base, prompt, session = null) {
  const explicitEmployee=requestedEmployee(prompt);
  if(session && explicitEmployee && normalized(explicitEmployee).split(' ').length>=2 && session.employeeSubject && normalized(explicitEmployee)!==normalized(session.employeeSubject)){
    // Una nueva persona solicitada NO debe heredar el expediente anterior.
    session.employeeSubject=null;session.backendContext=null;
  }
  const plan=planPrompt(prompt,session?.employeeSubject);
  if(plan.clarification) return {answer:plan.clarification,speechText:plan.clarification,status:'needs_clarification',presentation:null};
  // Solo en memoria; el servidor sigue siendo responsable de autenticar y autorizar.
  const previousContext=safeConversationContext(session?.backendContext);
  const request = JSON.stringify({ message: plan.message, context: { language: 'es', locale: 'es-ES', company: 'Sunset Beach Club', ...(previousContext||{}) } });
  const bearer = await authHeaders();
  for (const route of ['/api/mia/v4/chat','/api/mia/chat']) {
    let response;
    try { response = await requestWithTimeout(endpoint(base, route), {
      method: 'POST', headers: { 'Content-Type': 'application/json; charset=utf-8', Accept: 'application/json', ...bearer }, body: request
    }, 120000); }
    catch (e) { return { error: 'No se puede conectar con el backend mIA SBC: ' + (e.name === 'AbortError' ? 'tiempo de espera agotado.' : 'comprueba la dirección y el servicio.') }; }
    // Do not downgrade or fall back on authentication failures.
    if ([401,403].includes(response.status)) return { error: 'Acceso no autorizado. Debes iniciar sesión mediante el mecanismo corporativo de mIA SBC.' };
    if (response.status === 404 && route === '/api/mia/v4/chat') continue;
    if (!response.ok) return { error: `El backend mIA ha respondido con HTTP ${response.status}.` };
    try {
      const data = await response.json();
      const updatedContext=safeConversationContext(data.context || data.data?.context);
      if(session && updatedContext)session.backendContext=updatedContext;
      const special=view360(plan.message,data);
      if(special){
        if(!special.ok)return {error:special.message,identityBlocked:true,identityCode:special.code};
        if(session)session.employeeSubject=special.name;
        return {answer:special.message,speechText:special.message,status:'partial_verified',presentation:special.presentation,identitySelection:special.code};
      }
      const presentation=extractPresentation(data);
      const report=extractReport(data);
      if(report?.available){try{validateDownloadUrl(base,report);}catch{report.available=false;}}
      // Nunca presentaremos el éxito narrativo como confirmación de entrega del PDF.
      const reportPending=isReportQuestion(plan.message) && !report?.available;
      const checked=resolveEmployeeReply(plan.message,data,presentation);
      if(!checked.ok)return {error:checked.message,identityBlocked:true,identityCode:checked.code};
      // Never replay free-text narration or attached tables from an unverified
      // multi-employee backend response. Display only the selected record.
      if(checked.scope==='employee'){
        if(session){
          // Nunca elegimos personas de forma difusa; solo una coincidencia exacta
          // comprobada en la respuesta. No se persiste el registro personal.
          session.employeeSubject=getName(checked.row)||requestedEmployee(plan.message);
        }
        const safe=selectedEmployeePresentation(checked);
        if(!safe)return {error:'El registro no contiene campos que se puedan presentar de forma segura.',identityBlocked:true,identityCode:'EMPTY_EMPLOYEE_RECORD'};
        const notice=checked.selection==='MATCHED_LIST_ROW'
          ? 'He encontrado una única coincidencia en los datos recibidos. Te muestro su registro, pero no puedo afirmar que sea la ficha completa.'
          : 'He encontrado la ficha principal solicitada. Solo mostraré la información atribuible a esa persona.';
        return {answer:notice,speechText:notice,status:'partial_verified',presentation:safe,identitySelection:checked.selection};
      }
      const answer = data.answer || data.natural_answer || data.response || (data.status === 'error' ? 'El backend no pudo completar la consulta.' : 'Consulta completada.');
      return { answer: String(answer).slice(0, 12000), speechText: String(data.speech_text || answer).slice(0, 1400), status: data.status || 'ok', presentation, report, reportPending };
    } catch { return { error: 'El backend ha devuelto una respuesta no válida.' }; }
  }
  return { error: 'El backend no ofrece una ruta de conversación compatible.' };
}
async function speak(base, text) {
  let res;
  const bearer = await authHeaders();
  try { res = await requestWithTimeout(endpoint(base,'/api/mia/voice'), {
    method: 'POST', headers: { 'Content-Type': 'application/json; charset=utf-8', Accept: 'audio/mpeg', ...bearer },
    body: JSON.stringify({ text: String(text).slice(0, 1200), locale: 'es-ES' })
  }, 35000); }
  catch { return { error: 'No se puede conectar al servicio ElevenLabs de mIA SBC.' }; }
  if (!res.ok) return { error: res.status === 503 ? 'El backend de mIA no tiene disponible su servicio de voz (HTTP 503). Comprueba /api/mia/voice y los registros del backend/ElevenLabs.' : `No se ha podido obtener la voz mIA (HTTP ${res.status}).`, code:res.status };
  const mime = res.headers.get('content-type') || '';
  if (!mime.includes('audio/') && !mime.includes('application/octet-stream')) return { error: 'El servidor no ha devuelto audio.' };
  const bytes = Buffer.from(await res.arrayBuffer());
  if (!bytes.length || bytes.length > 6 * 1024 * 1024) return { error: 'Archivo de audio vacío o demasiado grande.' };
  return { ok: true, audioBase64: bytes.toString('base64'), mimeType: mime.includes('audio/') ? mime.split(';')[0] : 'audio/mpeg' };
}
module.exports = { sendPrompt, speak, endpoint };
