const bridge = window.miaDesktop;
const input = document.getElementById('prompt');
const thread = document.getElementById('thread');
const mailPrompt = document.getElementById('mailPrompt');
const send = document.getElementById('send');
const mic = document.getElementById('mic');
const voiceStatus = document.getElementById('voiceStatus');
const chatMicMode=document.getElementById('chatMicMode');
const micModeButtons=[...chatMicMode.querySelectorAll('.mic-mode-icon')];
let cfg = {}, recognizing = false, answering = false, audio = null, audioUrl = null;
let lastResult = null;
let pendingMailPrompt = null, mailPromptTimer = null;
let conversationActive=false,conversationTimer=null,captureEpoch=0;
let modeRevision=0,modeChanging=false;
const conversationToolbar=document.getElementById('conversationToolbar');
let utterance = null;
let playbackActive=false;
function setPlayback(active){if(playbackActive===Boolean(active))return;playbackActive=Boolean(active);bridge.playbackState(playbackActive);}
bridge.getState().then(state => {
  cfg = state?.config || {voiceMode:'off'};
  updateMicControls();
  // A saved conversational preference is PAUSED on every new chat session.
  // No recording begins until the user explicitly starts it in this window.
  if(cfg.voiceMode==='off')stateText('Micrófono completamente apagado. Puedes seguir escribiendo.');
  else if(cfg.voiceMode==='conversation')stateText('Modo conversación pausado. Pulsa Iniciar conversación.');
  else stateText(cfg.wakePhraseEnabled?'Dictado apagado. Solo se detectan comandos de activación.':'Pulsa Hablar para dictar una sola pregunta.');
});
function updateConversationBar(){conversationToolbar.hidden=!conversationActive;updateMicControls();}
function stopConversation(){
  ++captureEpoch;
  conversationActive=false;
  clearTimeout(conversationTimer); conversationTimer=null;
  bridge.stopDictation();
  updateMicControls();
}
function scheduleNextTurn(){
  if(!conversationActive || cfg.voiceMode!=='conversation' || document.hidden || modeChanging)return;
  clearTimeout(conversationTimer);
  conversationTimer=setTimeout(()=>{
    if(conversationActive && cfg.voiceMode==='conversation' && !recognizing && !answering && !document.hidden)dictate({continuation:true});
  },420);
}
function stateText(value) { voiceStatus.textContent = value; }
// La caja crece con el contenido (dictado incluido) hasta un máximo; a partir de ahí hace scroll
// en vez de empujar los botones de abajo. max-height debe coincidir con el de bubble.css.
const INPUT_MAX_HEIGHT = 140;
function autoResizeInput() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, INPUT_MAX_HEIGHT) + 'px';
}
input.addEventListener('input', autoResizeInput);
function updateMicControls(){
  const mode=cfg.voiceMode||'off';
  const status=mode==='off'?'off':recognizing?'listening':conversationActive?'conversation':'idle';
  for(const b of micModeButtons){
    const active=b.dataset.mode===mode;
    b.classList.toggle('active',active);
    b.setAttribute('aria-checked',active?'true':'false');
    b.classList.toggle('live',active&&(status==='listening'||status==='conversation'));
  }
  // While talking hands-free, 'Detener' must remain clickable even during an active capture.
  mic.disabled=modeChanging||mode==='off'||answering||(recognizing&&!conversationActive);
  mic.textContent=mode==='conversation'?(conversationActive?'■ Detener':'🎙 Iniciar conversación'):'🎙 Hablar una vez';
  conversationToolbar.hidden=!conversationActive;
}
async function setChatMode(mode){
  if(modeChanging||!['off','once','conversation'].includes(mode))return;
  ++modeRevision;
  stopConversation();
  modeChanging=true;
  cfg.voiceMode=mode;
  updateMicControls();
  if(mode==='off')stateText('Apagando micrófono y liberando el dispositivo…');
  try{
    const result=await bridge.setChatMicMode(mode);
    if(!result?.ok){cfg.voiceMode='off';bridge.stopDictation();stateText('Error al cambiar el modo. No se permite iniciar una nueva captura.');return;}
    cfg.voiceMode=result.mode;
    if(mode==='off')stateText('Micrófono desactivado. La captura y los comandos de voz están apagados.');
    else if(mode==='once')stateText(result.commandsEnabled?'En espera. Solo se detectan órdenes; pulsa Hablar para dictar.':'Micrófono preparado. Pulsa Hablar para una sola consulta.');
    else {stateText('Modo conversación iniciado de forma explícita.');conversationActive=true;}
  }catch{cfg.voiceMode='off';bridge.stopDictation();stateText('Error al cambiar el modo. La captura del chat permanece bloqueada.');}
  finally{modeChanging=false;updateMicControls();}
  // Pulsar el icono es la orden de "escúchame ahora": elegir modo y tener que pulsar un segundo
  // botón aparte para empezar a hablar es justo la confusión que se pidió evitar.
  if(mode==='conversation'&&conversationActive)dictate({continuation:true});
  else if(mode==='once'&&cfg.voiceMode==='once')dictate();
}
for(const b of micModeButtons) b.addEventListener('click',()=>setChatMode(b.dataset.mode));
function addMessage(text, type) {
  const el = document.createElement('div');
  el.className = `message ${type}`;
  el.textContent = text; // Sin HTML desde respuestas del backend.
  thread.appendChild(el); thread.scrollTop = thread.scrollHeight;
}
function hideMailPrompt() {
  clearTimeout(mailPromptTimer); mailPromptTimer = null; pendingMailPrompt = null;
  if (mailPrompt) { mailPrompt.hidden = true; mailPrompt.replaceChildren(); }
}
function mailQuery(c, action) {
  const sender = String(c?.de || 'el remitente del correo'), subject = String(c?.asunto || 'sin asunto');
  const target = `remitente «${sender}» y asunto «${subject}»`;
  const lookup = `Busca primero ese mensaje en mi buzón con correos_recientes (límite 10, incluir_texto=true), identifica la coincidencia exacta por remitente y asunto y después lee el correo usando la referencia que devuelva esa búsqueda. No llames a leer_correo hasta tener esa referencia; el remitente y el asunto no son referencias.`;
  return action === 'details'
    ? `Quiero ver el detalle y escuchar un resumen del correo nuevo con ${target}. ${lookup}`
    : `Resúmeme con detalle el contenido del correo nuevo con ${target}. ${lookup}`;
}
function chooseMail(action, c = pendingMailPrompt) {
  hideMailPrompt();
  bridge.resolveMailPrompt();
  if (action === 'dismiss') { void speakText('De acuerdo, seguimos con lo que estábamos.'); return; }
  input.value = mailQuery(c, action); autoResizeInput(); void submit();
}
function showMailPrompt(c) {
  if (!mailPrompt || !c) return;
  hideMailPrompt(); pendingMailPrompt = c;
  const title = document.createElement('strong'); title.textContent = `Correo nuevo · ${c.de || 'remitente desconocido'}`;
  const body = document.createElement('p'); body.textContent = `${c.asunto || '(sin asunto)'}\n¿Quieres un resumen, ver el detalle o seguir con lo que estabas haciendo?`;
  const actions = document.createElement('div'); actions.className = 'mail-prompt-actions';
  for (const [label, action] of [['Resumir correo', 'summary'], ['Ver detalle', 'details'], ['Ahora no', 'dismiss']]) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => chooseMail(action, c)); actions.appendChild(button);
  }
  mailPrompt.replaceChildren(title, body, actions); mailPrompt.hidden = false;
}
function consumeMailResponse(text) {
  if (!pendingMailPrompt) return null;
  const value = String(text || '').toLocaleLowerCase('es').normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  let action = 'other';
  if (/\b(no|ahora no|luego|continua|continuemos|sigamos|dejalo)\b/.test(value)) action = 'dismiss';
  else if (/\b(detalle|muestr|mostrar|abre|abrir|ver correo)\b/.test(value)) action = 'details';
  else if (/\b(resum|resumen|cuentame|que dice|contenido)\b/.test(value)) action = 'summary';
  const c = pendingMailPrompt;
  if (action === 'other') return { action, correo: c };
  hideMailPrompt(); bridge.resolveMailPrompt(); return { action, correo: c };
}
function stopAudio() {
  setPlayback(false);
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  utterance = null;
  if (audio) { audio.pause(); audio.src = ''; audio = null; }
  if (audioUrl) { URL.revokeObjectURL(audioUrl); audioUrl = null; }
  bridge.avatarAction('IDLE');
}
function speakWithSystemVoice(text, reason) {
  if (!cfg.voiceFallbackEnabled) { stateText(reason); bridge.avatarAction('IDLE'); scheduleNextTurn();return; }
  if (!('speechSynthesis' in window) || !window.SpeechSynthesisUtterance) {
    stateText(reason + ' No hay una voz local de respaldo disponible.');
    bridge.avatarAction('IDLE');scheduleNextTurn();return;
  }
  stopAudio();
  const voices=window.speechSynthesis.getVoices();
  const spanish=voices.filter(v=>String(v.lang).toLowerCase().startsWith('es'));
  const preferred=spanish.find(v=>/elvira|helena|lucia|lucía|dalia|monica|mónica|female/i.test(v.name)) || spanish[0] || null;
  if (!preferred) {
    stateText(reason + ' No hay voz española instalada en Windows.');
    bridge.avatarAction('IDLE');scheduleNextTurn();return;
  }
  const u = new SpeechSynthesisUtterance(String(text).slice(0,1400));
  u.lang='es-ES'; u.voice=preferred; u.rate=.97; u.pitch=1; u.volume=1;
  utterance=u;
  u.onstart=()=>{setPlayback(true);bridge.avatarAction('TALK');stateText('Voz local de Windows (respaldo). ElevenLabs no disponible.');};
  u.onend=()=>{setPlayback(false);if (utterance===u) {utterance=null;bridge.avatarAction('IDLE');stateText('Voz local de Windows · Lista para continuar.');scheduleNextTurn();}};
  u.onerror=()=>{setPlayback(false);if (utterance===u) {utterance=null;bridge.avatarAction('IDLE');stateText(reason + ' También falló la voz local de Windows.');scheduleNextTurn();}};
  stateText('ElevenLabs no disponible. Probando voz local de Windows…');
  window.speechSynthesis.speak(u);
}
async function speakText(text) {
  if (!cfg.voiceEnabled || !text) { bridge.avatarAction('IDLE');scheduleNextTurn(); return; }
  stateText('Solicitando voz mIA a ElevenLabs…');
  let reply;
  try { reply = await bridge.speak(text); }
  catch { reply = { error: 'No se pudo acceder al servicio de voz del backend SBC.' }; }
  if (reply.error || !reply.audioBase64) {
    speakWithSystemVoice(text, reply.error || 'No se ha podido recuperar la voz de mIA.');
    return;
  }
  stopAudio();
  try {
    const raw = atob(reply.audioBase64); const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    audioUrl = URL.createObjectURL(new Blob([bytes], { type: reply.mimeType || 'audio/mpeg' }));
    audio = new Audio(audioUrl);
    audio.addEventListener('playing', () => {setPlayback(true); bridge.avatarAction('TALK'); stateText('mIA está hablando · ElevenLabs'); });
    audio.addEventListener('ended', () => { stopAudio(); stateText('Micrófono apagado · Lista para escuchar.');scheduleNextTurn(); }, { once: true });
    audio.addEventListener('error', () => { stopAudio(); stateText('No se ha podido reproducir el audio de ElevenLabs.');scheduleNextTurn(); }, { once: true });
    await audio.play();
  } catch { stopAudio(); stateText('El equipo no ha podido reproducir el audio de ElevenLabs.');scheduleNextTurn(); }
}
async function submit() {
  let question = input.value.trim();
  if (!question || answering) return;
  const mailReply = consumeMailResponse(question);
  if (mailReply?.action === 'dismiss') { await speakText('De acuerdo, seguimos con lo que estábamos.'); return; }
  if (mailReply?.action === 'summary' || mailReply?.action === 'details') question = mailQuery(mailReply.correo, mailReply.action);
  input.value = question;
  stopAudio(); input.value = ''; autoResizeInput(); document.getElementById('transcription').hidden=true; addMessage(question, 'user');
  lastResult = null;
  answering = true; send.disabled = true; updateMicControls();
  bridge.avatarAction('THINK'); stateText('Consultando mIA SBC…');
  try {
    const reply = await bridge.sendPrompt(question);
    if (reply.error) {
      addMessage(reply.error, 'mia'); stateText('Error de conexión, autorización o verificación de identidad.'); bridge.avatarAction('IDLE');stopConversation();
    } else {
      addMessage(reply.answer || 'Sin respuesta.', 'mia');
      lastResult = { question, answer: reply.answer || '', presentation: reply.presentation || null, reportPending:!!reply.reportPending };
      if(reply.reportPending)addMessage('El backend no ha entregado un enlace de descarga verificable. El texto «PDF listo» no permite recuperar el archivo. Consulta la sección Documento generado de Resultados.','mia');
      const hasTables = !!reply.presentation?.tables?.length;
      const hasCalendars = !!reply.presentation?.calendars?.length;
      const hasCards = !!reply.presentation?.cards?.length;
      const hasReport = !!reply.report?.available;
      const wantsVisual = /\b(lista|listado|relaci[oó]n|tabla|todos|todas|empleados|personas|puestos|gr[aá]fic[ao]s?|informe|kpi|estad[ií]sticas|ficha|expediente|perfil)\b/i.test(question);
      if (hasTables || hasCards || hasCalendars || hasReport || wantsVisual) {
        bridge.openResults(lastResult);
        if (!hasTables && !hasCards && !hasCalendars && !hasReport && !reply.reportPending) {
          addMessage('Aviso: el servidor ha enviado texto, pero no los registros estructurados del listado. He abierto Resultados para que puedas comprobarlo.', 'mia');
        }
      }
      await speakText(reply.speechText || reply.answer);
    }
  } catch { addMessage('No se pudo completar la consulta. Comprueba el servidor mIA.', 'mia'); bridge.avatarAction('IDLE');stopConversation(); }
  finally { answering = false; send.disabled = false; updateMicControls(); input.focus(); }
}
async function dictate(options={}) {
  if (cfg.voiceMode==='off'||modeChanging) {stateText('Micrófono apagado: elige otro modo para hablar.');return;}
  if(options.continuation && (!conversationActive || cfg.voiceMode!=='conversation'))return;
  if(recognizing || answering)return;
  if(cfg.voiceMode==='conversation'&&!options.continuation){conversationActive=true;updateConversationBar();}
  const capturedMode=cfg.voiceMode;
  const epoch=captureEpoch;
  stopAudio(); recognizing = true;updateMicControls();
  stateText('Preparando Vosk + Whisper local…'); bridge.avatarAction('LISTEN');
  try {
    const result = await bridge.recognizeOnce();
    // A cancelled capture may finish asynchronously. Never insert or send stale audio.
    if(epoch!==captureEpoch || cfg.voiceMode!==capturedMode || document.hidden || modeChanging)return;
    if(cfg.voiceMode==='conversation' && !conversationActive)return;
    if (!result.ok) { if(result.code==='COMMAND_HANDLED'||result.code==='CANCELLED')return;stateText((result.code?'['+result.code+'] ':'')+(result.error || 'No se ha reconocido la frase.')+' · Configuración > Comprobar motor local.'); return; }
    input.value = result.text; autoResizeInput();
    const score = typeof result.confidence==='number' ? Math.round(result.confidence*100) : null;
    stateText('Dictado recibido' + (score===null ? '' : ` · confianza ${score}%`) + ': ' + result.text.slice(0,95));
    const alts=document.getElementById('alternatives');alts.replaceChildren();
    const options=(Array.isArray(result.alternatives)?result.alternatives:[]).filter(x=>x?.text&&x.text!==result.text).slice(0,3);
    for(const alt of options){const b=document.createElement('button');b.className='alt-option';b.type='button';b.textContent=alt.text;b.addEventListener('click',()=>{input.value=alt.text;autoResizeInput();input.focus();});alts.append(b);}
    document.getElementById('transcriptionInfo').textContent=options.length?'Otras transcripciones posibles · puedes elegir o corregir el texto:':'Revisa el texto reconocido antes de enviarlo.';
    document.getElementById('transcription').hidden=false;
    if ((cfg.autoSendDictation && capturedMode==='once') || (capturedMode==='conversation' && conversationActive)) await submit();
    else {input.focus();if(conversationActive)stateText('Transcripción pendiente de revisión. Corrige y pulsa Enviar para continuar.');}
  } catch { stateText('No se ha podido acceder al reconocimiento local. Revisa Configuración > Comprobar motor local.'); }
  finally { recognizing = false; updateMicControls(); if(!answering)bridge.avatarAction('IDLE'); }
}
send.addEventListener('click', submit);
mic.addEventListener('click',()=>{
  if(cfg.voiceMode==='conversation'&&conversationActive){stopConversation();stateText('Conversación detenida. No se enviará más audio.');return;}
  dictate();
});
document.getElementById('stopConversation').addEventListener('click',()=>{stopConversation();stopAudio();stateText('Conversación manos libres detenida.');});
input.addEventListener('keydown', ev => {
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); submit(); }
  if (ev.key === 'Escape') {ev.preventDefault();stopConversation();stateText('Escucha detenida. El chat sigue abierto.');}
});
document.getElementById('close').addEventListener('click', () => { stopConversation(); stopAudio(); bridge.hideBubble(); });
document.getElementById('minimize').addEventListener('click', () => { stopConversation(); stopAudio(); bridge.hideAvatar(); });
document.getElementById('settings').addEventListener('click', () => bridge.openSettings());
document.getElementById('preview').addEventListener('click', () => bridge.openResults(lastResult || { question: input.value.trim(), answer: 'Todavía no se ha recibido una respuesta a esta consulta.', presentation:null }));
// Solo solicitudes explícitas del menú «Hablar»; abrir mIA nunca inicia el dictado.
bridge.onMicrophoneRequest(() => {if(cfg.voiceMode!=='off')dictate();});
// Aviso de correo nuevo (main.cjs, mail-watch.cjs): deja la pregunta escrita, lista para que el
// usuario la confirme — nunca se envía sola, sin que el usuario pulse enviar.
bridge.onPrefillInput(text => { if (typeof text === 'string' && text.trim()) { input.value = text; autoResizeInput(); input.focus(); } });
bridge.onMailPrompt(showMailPrompt);
bridge.onStopConversation(()=>{stopConversation();stopAudio();});
bridge.onConfigChanged(value=>{
  const prev=cfg.voiceMode;
  cfg={...cfg,...value};
  if(prev!==cfg.voiceMode || cfg.voiceMode==='off'){stopConversation();bridge.stopDictation();}
  if(cfg.voiceMode==='conversation'&&!conversationActive)stateText('Modo conversación pausado. Pulsa Iniciar conversación.');
  updateMicControls();
});
bridge.onVoiceStatus(status => { if(status.active && !recognizing && cfg.voiceMode!=='off')stateText('Escucha de comandos activa, no de preguntas.');updateMicControls(); });
// Global Escape must not accidentally dismiss the chat window.
window.addEventListener('focus', () => input.focus());
document.addEventListener('visibilitychange', () => { if (document.hidden) {stopConversation();stopAudio();} });
input.focus(); autoResizeInput();

// Redimensionamiento completo del panel sin marco: bordes y cuatro esquinas.
// Las dimensiones se guardan de forma persistente en el proceso principal.
for (const grip of document.querySelectorAll('[data-resize]')) {
  let resizing = null;
  const finish = () => { resizing = null; };
  grip.addEventListener('pointerdown', ev => {
    if (ev.button !== 0) return;
    resizing = { id: ev.pointerId, x: ev.screenX, y: ev.screenY, edge: grip.dataset.resize };
    grip.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  grip.addEventListener('pointermove', ev => {
    if (!resizing || resizing.id !== ev.pointerId) return;
    const dx = Math.round(ev.screenX - resizing.x);
    const dy = Math.round(ev.screenY - resizing.y);
    if (!dx && !dy) return;
    const edge = resizing.edge;
    bridge.resizeBubble(edge.includes('e') || edge.includes('w') ? dx : 0,
                        edge.includes('n') || edge.includes('s') ? dy : 0, edge);
    resizing.x = ev.screenX;
    resizing.y = ev.screenY;
  });
  grip.addEventListener('pointerup', finish);
  grip.addEventListener('pointercancel', finish);
  grip.addEventListener('lostpointercapture', finish);
}

window.addEventListener('error',()=>window.miaDesktop.reportRendererError('WINDOW_ERROR'));
window.addEventListener('unhandledrejection',()=>window.miaDesktop.reportRendererError('UNHANDLED_REJECTION'));

bridge.onCalendarConfirmation(prompt => {if(!/^confirma cambio [1-9]\d*$/.test(prompt||''))return;input.value=prompt;autoResizeInput();if(!answering)void submit();else stateText('Confirmación preparada: envíala al terminar la consulta actual.');});
