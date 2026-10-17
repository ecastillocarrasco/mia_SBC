const bridge = window.miaDesktop;
const el = id => document.getElementById(id);
const sizes = { small: [200, 275], medium: [250, 345], large: [330, 455] };
async function refresh() {
  const state = await bridge.getState(); if (!state) return;
  for (const key of ['shortcut', 'wakePhrase', 'hidePhrase','exitPhrase', 'backendBase', 'greetingName']) el(key).value = state.config[key];
  for (const key of ['alwaysOnTop', 'launchAtLogin', 'wakePhraseEnabled', 'autoSendDictation', 'voiceEnabled', 'voiceFallbackEnabled', 'subtleMovement','idleWalkCircle','idleBored','startupGreeting']) {
    el(key === 'launchAtLogin' ? 'login' : key).checked = Boolean(state.config[key]);
  }
  el('voiceMode').value=state.config.voiceMode||'once';
  el('size').value = Object.entries(sizes).reduce((best, [name, wh]) =>
    Math.abs(wh[0] - state.config.avatarWidth) < Math.abs(sizes[best][0] - state.config.avatarWidth) ? name : best, 'medium');
  el('miaLogoState').textContent=state.hasMiaLogo?'Logotipo personalizado instalado':'Firma mIA provisional';
  el('modelState').textContent = state.hasModel ? 'Modelo GLB disponible' : 'Sin modelo: mIA permanecerá invisible hasta cargar el GLB.';
  if (state.voiceStatus && !state.voiceStatus.active && state.config.wakePhraseEnabled && state.voiceStatus.message)
    el('feedback').textContent = state.voiceStatus.message;
}
el('model').addEventListener('click', async () => {
  const res = await bridge.pickModel();
  if (res.ok) { el('feedback').textContent = 'Modelo importado.'; await refresh(); }
  else if (!res.canceled) el('feedback').textContent = res.error || 'No se pudo importar el GLB.';
});
el('save').addEventListener('click', async () => {
  const rawBackend = el('backendBase').value.trim();
  try {
    const u = new URL(rawBackend);
    const local = ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname.toLowerCase());
    if (!(u.protocol === 'https:' || (u.protocol === 'http:' && local)) || u.username || u.password || u.pathname !== '/' || u.search || u.hash) throw Error();
  } catch { el('feedback').textContent = 'Dirección no válida: utiliza localhost HTTP o el servidor HTTPS de SBC.'; return; }
  const cfg = {
    shortcut: el('shortcut').value.trim(),
    alwaysOnTop: el('alwaysOnTop').checked, launchAtLogin: el('login').checked,
    avatarWidth: sizes[el('size').value][0], avatarHeight: sizes[el('size').value][1],
    wakePhraseEnabled: el('wakePhraseEnabled').checked,
    wakePhrase: el('wakePhrase').value.trim(),
    hidePhrase:el('hidePhrase').value.trim(),exitPhrase:el('exitPhrase').value.trim(),voiceMode:el('voiceMode').value,
    autoListenOnWake: false,
    autoListenOnShow: false,
    autoSendDictation: el('autoSendDictation').checked,
    backendBase: rawBackend, voiceEnabled: el('voiceEnabled').checked, voiceFallbackEnabled: el('voiceFallbackEnabled').checked,
    subtleMovement: el('subtleMovement').checked,
    idleWalkCircle:el('idleWalkCircle').checked, idleBored:el('idleBored').checked,
    startupGreeting:el('startupGreeting').checked, greetingName:el('greetingName').value.trim()
  };
  const result = await bridge.saveSettings(cfg);
  el('feedback').textContent = result.ok ? `Preferencias guardadas. Avatar: ${result.config.avatarWidth}×${result.config.avatarHeight} px. Los cambios de voz se aplican inmediatamente.` : result.error || 'No se pudo guardar.';
});
bridge.onVoiceStatus(status => {
  if (!status.active && status.message) el('feedback').textContent = status.message;
});
refresh();

el('chooseMiaLogo').addEventListener('click',async()=>{
  const result=await bridge.pickMiaLogo();
  if(result.ok){el('feedback').textContent='Logotipo original de mIA instalado en la aplicación.';await refresh();}
  else if(!result.canceled)el('feedback').textContent=result.error||'No se pudo importar el logotipo.';
});
el('probeVoice').addEventListener('click',async()=>{
  const out=el('diagnosticResult');out.textContent='Comprobando el motor de voz local Vosk + Whisper…';
  try{const r=await bridge.probeVoice();
    if(r.ok){out.textContent='Motor Vosk + faster-whisper preparado. Reconocimiento local español disponible.';}
    else out.textContent=(r.code||'ERROR')+': '+(r.error||'Error no especificado');
  }catch{out.textContent='No se ha podido ejecutar el diagnóstico. Consulta el registro.';}
});
el('openLogs').addEventListener('click',()=>bridge.openDiagnostics());
window.addEventListener('error',()=>bridge.reportRendererError('WINDOW_ERROR'));
window.addEventListener('unhandledrejection',()=>bridge.reportRendererError('UNHANDLED_REJECTION'));
