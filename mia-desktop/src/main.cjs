'use strict';
const { app, BrowserWindow, Tray, Menu, dialog, ipcMain, globalShortcut, screen, nativeImage, protocol, net, shell } = require('electron');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { normalizeConfig, clamp, placeNear } = require('./config.cjs');
const { computeResizeBounds } = require('./bubble-resize.cjs');
const speech = require('./voice.cjs');
const backend = require('./backend.cjs');
const tableExport = require('./export.cjs');
const diagnostics = require('./diagnostics.cjs');
const {VisibilityGate} = require('./visibility.cjs');

protocol.registerSchemesAsPrivileged([{
  scheme: 'mia', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true }
}]);

// La voz se reproduce solo dentro de la interfaz local y bajo preferencia del usuario.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
if (!app.requestSingleInstanceLock()) app.exit(0);
let avatarWin, bubbleWin, settingsWin, resultsWin, tray;
let config = normalizeConfig();
let registeredShortcut = null;
let wakeProcess = null;
let wakeGeneration=0;
const visibility = new VisibilityGate();
let confirmationOpen=false;
let microphoneInUse = false;
const activePlaybackSenders=new Set();
let greetingTriggered = false;
let ceremonySequence=0, ceremonyBusy=false;
const ceremonies=new Map();
let lastResultsPayload = null;
const conversationSession={backendContext:null,employeeSubject:null};
let logoDownloadBusy = false;
let bubbleResizePending = null;
let lastVoiceStatus = { message: 'Micrófono desactivado.', active: false };
const ui = name => path.join(__dirname, 'ui', `${name}.html`);
const configFile = () => path.join(app.getPath('userData'), 'desktop-settings.json');
const modelFile = () => path.join(app.getPath('userData'), 'avatar.glb');
const bundledModelFile = () => path.join(app.getAppPath(), 'assets', 'mIA_SBC_V4_84_ANIMACIONES.glb');
const bundledBrandFile = () => path.join(app.getAppPath(), 'assets', 'branding', 'sunset-logo.png');
const cachedBrandFile = () => path.join(app.getPath('userData'), 'sunset-logo.png');
const customMiaLogoFile = () => path.join(app.getPath('userData'), 'mia-logo.png');
const bundledMiaLogoFile = () => path.join(app.getAppPath(), 'assets', 'branding', 'mia-logo.png');
function currentMiaLogoFile(){
  if(fs.existsSync(customMiaLogoFile()))return customMiaLogoFile();
  if(fs.existsSync(bundledMiaLogoFile()))return bundledMiaLogoFile();
  return null;
}
function currentBrandFile() {
  if (fs.existsSync(bundledBrandFile())) return bundledBrandFile();
  if (fs.existsSync(cachedBrandFile())) return cachedBrandFile();
  return null;
}
async function cacheBrandLogo() {
  if (currentBrandFile() || logoDownloadBusy) return;
  logoDownloadBusy = true;
  try {
    const res = await net.fetch('https://www.sunsetbeachclub.com/img/logo.png', { method:'GET' });
    if (!res.ok) return;
    const bytes = Buffer.from(await res.arrayBuffer());
    if (bytes.length < 100 || bytes.length > 2500000 || !bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return;
    await fsp.mkdir(path.dirname(cachedBrandFile()), { recursive:true });
    await fsp.writeFile(cachedBrandFile(), bytes);
    for (const win of [bubbleWin,settingsWin,resultsWin]) if (win && !win.isDestroyed()) win.webContents.send('mia:branding-ready',true);
  } catch (e) { console.warn('El logotipo oficial no ha podido descargarse:', e.message); }
  finally { logoDownloadBusy=false; }
}
function currentModel() {
  if (fs.existsSync(modelFile())) return modelFile();
  if (fs.existsSync(bundledModelFile())) return bundledModelFile();
  return null;
}
function readConfig() {
  try { config = normalizeConfig(JSON.parse(fs.readFileSync(configFile(), 'utf8'))); }
  catch { config = normalizeConfig(); }
}
async function writeConfig() {
  await fsp.mkdir(path.dirname(configFile()), { recursive: true });
  const tmp = `${configFile()}.tmp`;
  await fsp.writeFile(tmp, JSON.stringify(config, null, 2), { mode: 0o600 });
  await fsp.rename(tmp, configFile());
}
function applyLoginSetting() {
  if (process.platform === 'win32') app.setLoginItemSettings({ openAtLogin: config.launchAtLogin, path: process.execPath });
}
function safeWindowExtras(win) {
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', e => e.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
}
function createWindow(name, options) {
  const win = new BrowserWindow({
    show: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      devTools: !app.isPackaged
    },
    ...options
  });
  safeWindowExtras(win);
  win.webContents.on('render-process-gone',()=>diagnostics.record('renderer_gone',{mode:'ui',code:'RENDER_PROCESS_GONE'}));
  win.webContents.on('did-fail-load',()=>diagnostics.record('window_load_failed',{mode:'ui',code:'LOAD_FAILED'}));
  win.on('unresponsive',()=>diagnostics.record('window_unresponsive',{mode:'ui',code:'UNRESPONSIVE'}));
  win.loadFile(ui(name));
  return win;
}
function workAreaForAvatar() {
  return screen.getDisplayMatching(avatarWin.getBounds()).workArea;
}
function positionAvatar() {
  const area = screen.getPrimaryDisplay().workArea;
  avatarWin.setBounds({
    x: area.x + area.width - config.avatarWidth - 20,
    y: area.y + area.height - config.avatarHeight - 4,
    width: config.avatarWidth,
    height: config.avatarHeight
  });
}
function broadcastVoiceStatus(message, active = false) {
  lastVoiceStatus = { message, active };
  for (const win of [bubbleWin, settingsWin]) {
    if (win && !win.isDestroyed()) win.webContents.send('mia:voice-status', { message, active });
  }
}
function avatarAction(name) {
  if (avatarWin && !avatarWin.isDestroyed()) avatarWin.webContents.send('mia:avatar-action', name);
}
function stopWake() {
  wakeGeneration++;
  const previous = wakeProcess; wakeProcess = null;
  if (previous && !previous.killed) previous.kill();
}
function performCeremony(kind,text){
  if(!avatarWin || avatarWin.isDestroyed() || !avatarWin.isVisible())return Promise.resolve(false);
  const id=++ceremonySequence;
  return new Promise(resolve=>{
    const timer=setTimeout(()=>{ceremonies.delete(id);resolve(false);},14500);
    ceremonies.set(id,{resolve,timer});
    avatarWin.webContents.send('mia:avatar-ceremony',{
      id,animation:kind,text,voiceEnabled:config.voiceEnabled,
      fallbackEnabled:config.voiceFallbackEnabled
    });
  });
}
async function spokenHide(){
  if(ceremonyBusy)return;
  ceremonyBusy=true;stopWake();speech.cancelDictation();
  if(bubbleWin&&!bubbleWin.isDestroyed())bubbleWin.webContents.send('mia:stop-conversation');
  try{await performCeremony('FAREWELL','Hasta luego. Cuando me necesites, aquí estaré.');}
  finally{ceremonyBusy=false;hideAvatar();}
}
async function spokenShow(){
  if(ceremonyBusy || !visibility.acceptVoiceShow())return;
  const wasHidden=!avatarWin?.isVisible();
  if(!wasHidden && bubbleWin?.isVisible())return;
  ceremonyBusy=true;
  // Wake command only shows the assistant. It must never start dictation.
  try{
    if(!openBubble({source:'wake',autoDictate:false}))return;
    stopWake();
    await performCeremony('JOY_GREET','¡Hola! ¡Qué alegría verte! ¿En qué puedo ayudarte?');
  }finally{
    ceremonyBusy=false;
    startWake();
  }
}
function exitDesktop() {
  diagnostics.record('voice_command',{mode:'wake',code:'EXIT_CONFIRMED'});
  app.isQuitting=true; stopWake(); speech.cancelDictation(); speech.shutdown(); app.quit();
}
function onSpokenCommand(command){
  if(ceremonyBusy||app.isQuitting)return;
  if(command==='SHOW'){spokenShow().catch(()=>{ceremonyBusy=false;startWake();});return;}
  if(command==='HIDE'){spokenHide().catch(()=>{ceremonyBusy=false;hideAvatar();});return;}
  if(command==='EXIT'&&!confirmationOpen){
    confirmationOpen=true;stopWake();
    dialog.showMessageBox({type:'question',title:'Cerrar mIA Desktop',message:'¿Quieres cerrar mIA Desktop por completo?',buttons:['Cancelar','Cerrar mIA'],defaultId:0,cancelId:0,noLink:true})
      .then(async r=>{
        confirmationOpen=false;
        if(r.response!==1){startWake();return;}
        ceremonyBusy=true;
        try{
          if(!avatarWin.isVisible())focusAvatar();
          await performCeremony('FAREWELL','Hasta pronto. ¡Ha sido un placer ayudarte!');
        }finally{exitDesktop();}
      }).catch(()=>{confirmationOpen=false;ceremonyBusy=false;startWake();});
  }
}

function startWake() {
  stopWake();
  if (!config.wakePhraseEnabled || config.voiceMode==='off' || microphoneInUse || activePlaybackSenders.size || ceremonyBusy || app.isQuitting){if(config.voiceMode==='off')speech.shutdown();else speech.releaseIdle();return;}
  const myGeneration=wakeGeneration;
  wakeProcess = speech.watchWake(config.wakePhrase, command => {
    if(myGeneration!==wakeGeneration)return;
    // voice.cjs ya registra el evento una sola vez.
    onSpokenCommand(command);
  }, status => {
    if(myGeneration!==wakeGeneration)return;
    broadcastVoiceStatus(status.message,status.active);
    if(!status.active)stopWake();
  },{hidePhrase:config.hidePhrase,exitPhrase:config.exitPhrase});
}
function requestMicrophone() {
  if (!bubbleWin || bubbleWin.isDestroyed()) return;
  const send = () => bubbleWin && !bubbleWin.isDestroyed() && bubbleWin.webContents.send('mia:microphone-request');
  if (bubbleWin.webContents.isLoading()) bubbleWin.webContents.once('did-finish-load', send);
  else send();
}
function focusAvatar() {
  if (!avatarWin || avatarWin.isDestroyed()) return;
  visibility.show();
  avatarWin.setIgnoreMouseEvents(false);
  avatarWin.showInactive();
  avatarWin.webContents.send('mia:avatar-visibility', true);
}
function hideAvatar() {
  if (!avatarWin || avatarWin.isDestroyed()) return;
  visibility.hide();
  speech.cancelDictation();
  microphoneInUse=false;
  if(bubbleWin && !bubbleWin.isDestroyed())bubbleWin.webContents.send('mia:stop-conversation');
  if (bubbleWin && !bubbleWin.isDestroyed()) bubbleWin.hide();
  avatarWin.hide();
  avatarWin.webContents.send('mia:avatar-visibility', false);
  startWake();
}
function positionCompanion(win) {
  if (!avatarWin || !win || win.isDestroyed()) return;
  const pos = placeNear(avatarWin.getBounds(), win.getBounds(), workAreaForAvatar());
  win.setPosition(pos.x, pos.y);
}
function openBubble(options = {}) {
  if(options.source==='wake' && !visibility.acceptVoiceShow())return false;
  focusAvatar();
  if (!bubbleWin || bubbleWin.isDestroyed()) {
    bubbleWin = createWindow('bubble', {
      width: config.bubbleWidth, height: config.bubbleHeight, minWidth: 390, minHeight: 385,
      frame: false, transparent: true, hasShadow: true, resizable: true,
      skipTaskbar: true, alwaysOnTop: config.alwaysOnTop
    });
    bubbleWin.on('close', e => { if (!app.isQuitting) { e.preventDefault(); speech.cancelDictation(); bubbleWin.webContents.send('mia:stop-conversation'); bubbleWin.hide(); startWake(); } });
    bubbleWin.on('resize', () => {
      const bounds=bubbleWin.getBounds();
      if (bubbleResizePending) clearTimeout(bubbleResizePending);
      bubbleResizePending=setTimeout(() => {config.bubbleWidth=bounds.width; config.bubbleHeight=bounds.height; writeConfig().catch(console.warn);},450);
    });
  }
  positionCompanion(bubbleWin);
  // Keep the small wake-phrase recognizer running while the chat is open:
  // otherwise HIDE and EXIT commands could never be heard from the bubble.
  // Dictation (and playback) temporarily take exclusive control of the mic.
  const explicitTalk=options.autoDictate===true && options.userGesture===true;
  if(explicitTalk)stopWake();
  bubbleWin.show(); bubbleWin.focus();
  if (explicitTalk) requestMicrophone();
  else if (!wakeProcess && !microphoneInUse && !activePlaybackSenders.size) startWake();
  return true;
}
function openSettings() {
  if (!settingsWin || settingsWin.isDestroyed()) {
    settingsWin = createWindow('settings', {
      title: 'mIA Desktop | Configuración', width: 580, height: 800,
      minWidth: 470, minHeight: 650, autoHideMenuBar: true
    });
    settingsWin.on('closed', () => { settingsWin = null; });
  }
  settingsWin.show(); settingsWin.focus();
  return true;
}
function openResults(payload = {}) {
  // Esta ventana recibe únicamente la respuesta devuelta por el backend ya consultado.
  const sanitized = {
    question: typeof payload.question === 'string' ? payload.question.slice(0,2000) : '',
    answer: typeof payload.answer === 'string' ? payload.answer.slice(0,12000) : '',
    presentation: payload.presentation && typeof payload.presentation === 'object' ? payload.presentation : null
  };
  if (!resultsWin || resultsWin.isDestroyed()) {
    resultsWin = createWindow('results', {
      title: 'mIA Desktop | Resultados', width: 920, height: 690,
      minWidth: 620, minHeight: 460, autoHideMenuBar: true,
      backgroundColor: '#f8f5f3'
    });
    resultsWin.on('closed', () => { resultsWin = null; });
  }
  lastResultsPayload = sanitized;
  resultsWin.show(); resultsWin.focus();
  const send = () => { if (resultsWin && !resultsWin.isDestroyed()) resultsWin.webContents.send('mia:results-data', sanitized); };
  if (resultsWin.webContents.isLoading()) resultsWin.webContents.once('did-finish-load', send);
  else send();
  return true;
}

function registerShortcut(shortcut) {
  if (registeredShortcut) globalShortcut.unregister(registeredShortcut);
  registeredShortcut = null;
  if (!globalShortcut.register(shortcut, () => {
    if (!avatarWin.isVisible()) openBubble();
    else if (bubbleWin && bubbleWin.isVisible()) hideAvatar();
    else openBubble();
  })) return false;
  registeredShortcut = shortcut;
  return true;
}
function trayImage(){
  const candidate=currentMiaLogoFile()||path.join(app.getAppPath(),'assets','tray.png');
  const img=nativeImage.createFromPath(candidate);
  return img.isEmpty()?nativeImage.createFromPath(path.join(app.getAppPath(),'assets','tray.png')):img.resize({width:32,height:32});
}
function createTray() {
  tray = new Tray(trayImage());
  tray.setToolTip('mIA Desktop SBC');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Mostrar mIA', click: () => openBubble() },
    { label: 'Escribir a mIA', click: () => openBubble() },
    { label: 'Hablar con mIA', click: () => openBubble({ autoDictate: true, userGesture: true }) },
    { label: 'Minimizar mIA a la bandeja', click: hideAvatar },
    { type: 'separator' },
    { label: 'Configuración…', click: openSettings },
    { label: 'Abrir carpeta de diagnósticos', click: () => shell.openPath(diagnostics.folder()).catch(()=>{}) },
    { type: 'separator' },
    { label: 'Salir de mIA Desktop', click: () => { app.isQuitting = true; app.quit(); } }
  ]));
  tray.on('double-click', openBubble);
}
function ownSender(event, allowed) {
  return allowed.some(w => w && !w.isDestroyed() && w.webContents.id === event.sender.id);
}
function setupIPC() {
  ipcMain.handle('mia:get-state', event => {
    if (!ownSender(event, [avatarWin, bubbleWin, settingsWin, resultsWin])) return null;
    return { config: { ...config }, hasModel: Boolean(currentModel()), hasBrand: Boolean(currentBrandFile()), hasMiaLogo:Boolean(currentMiaLogoFile()), mode: 'desktop-v0.3.2', backendConnected: false, voiceStatus: lastVoiceStatus, avatarBounds:avatarWin.getBounds() }; 
  });
  let dragSession = null;
  let dragTimer = null;
  function stopDragging(){ if(dragTimer) clearInterval(dragTimer); dragTimer=null; dragSession=null; }
  ipcMain.on('mia:start-drag', event => {
    if (!ownSender(event,[avatarWin])) return;
    stopDragging();
    avatarWin.setIgnoreMouseEvents(false);
    dragSession={cursor:screen.getCursorScreenPoint(), bounds:avatarWin.getBounds(), started:Date.now()};
    dragTimer=setInterval(()=>{
      if(!dragSession || avatarWin.isDestroyed() || Date.now()-dragSession.started>12000) {stopDragging();return;}
      const now=screen.getCursorScreenPoint(); const ds=screen.getDisplayNearestPoint(now);const w=ds.workArea;
      avatarWin.setPosition(Math.round(clamp(dragSession.bounds.x+now.x-dragSession.cursor.x,w.x,w.x+w.width-dragSession.bounds.width)),
        Math.round(clamp(dragSession.bounds.y+now.y-dragSession.cursor.y,w.y,w.y+w.height-dragSession.bounds.height)));
      if (bubbleWin && bubbleWin.isVisible()) positionCompanion(bubbleWin);
    },25);
  });
  ipcMain.on('mia:stop-drag', event => {if(ownSender(event,[avatarWin]))stopDragging();});
  ipcMain.on('mia:move-avatar', (event, dx, dy) => {
    if (!ownSender(event, [avatarWin]) || !Number.isFinite(dx) || !Number.isFinite(dy)) return;
    if (Math.abs(dx) > 120 || Math.abs(dy) > 120) return;
    const b = avatarWin.getBounds(); const w = workAreaForAvatar();
    avatarWin.setPosition(
      Math.round(clamp(b.x + dx, w.x, w.x + w.width - b.width)),
      Math.round(clamp(b.y + dy, w.y, w.y + w.height - b.height))
    );
    if (bubbleWin && bubbleWin.isVisible()) positionCompanion(bubbleWin);
  });
  ipcMain.on('mia:resize-bubble', (event, dx, dy, edge = 'se') => {
    if (!ownSender(event, [bubbleWin]) || !Number.isFinite(dx) || !Number.isFinite(dy)) return;
    if (Math.abs(dx) > 110 || Math.abs(dy) > 110) return;
    if (!['n','s','e','w','ne','nw','se','sw'].includes(edge)) return;
    const bounds = bubbleWin.getBounds();
    const area = screen.getDisplayMatching(bounds).workArea;
    const next = computeResizeBounds(bounds, area, dx, dy, edge);
    if (next.x !== bounds.x || next.y !== bounds.y || next.width !== bounds.width || next.height !== bounds.height)
      bubbleWin.setBounds(next);
  });
  ipcMain.on('mia:passthrough', (event, ignore) => {
    if (ownSender(event, [avatarWin]) && typeof ignore === 'boolean')
      avatarWin.setIgnoreMouseEvents(ignore, { forward: true });
  });
  ipcMain.handle('mia:open-bubble', event => ownSender(event, [avatarWin, bubbleWin]) && openBubble());
  ipcMain.handle('mia:hide-bubble', event => {
    if (ownSender(event, [bubbleWin])) { speech.cancelDictation(); bubbleWin.webContents.send('mia:stop-conversation'); bubbleWin.hide(); startWake(); return true; }
    return false;
  });
  ipcMain.handle('mia:hide-avatar', event => {
    if (ownSender(event, [avatarWin, bubbleWin, settingsWin])) { hideAvatar(); return true; }
    return false;
  });
  ipcMain.handle('mia:open-settings', event => ownSender(event, [bubbleWin, settingsWin, avatarWin]) && openSettings());
  ipcMain.handle('mia:open-results', (event, payload) => ownSender(event, [bubbleWin]) && openResults(payload));
  ipcMain.on('mia:avatar-action', (event, action) => {
    if (ownSender(event, [bubbleWin]) && ['IDLE','GREET','LISTEN','THINK','TALK','WALK_CIRCLE','BORED'].includes(action)) avatarAction(action);
  });
  ipcMain.on('mia:avatar-context-menu', event => {
    if (!ownSender(event, [avatarWin])) return;
    Menu.buildFromTemplate([
      { label: 'Escribir a mIA', click: () => openBubble() },
      { label: 'Hablar con mIA', click: () => openBubble({ autoDictate: true, userGesture: true }) },
      { type: 'separator' },
      { label: 'Minimizar a la bandeja', click: hideAvatar },
      { label: 'Configuración...', click: openSettings }
    ]).popup({ window: avatarWin });
  });
  ipcMain.on('mia:ceremony-finished',(event,id)=>{
    if(!ownSender(event,[avatarWin])||!Number.isInteger(id))return;
    const pending=ceremonies.get(id);if(!pending)return;
    clearTimeout(pending.timer);ceremonies.delete(id);pending.resolve(true);
  });
  ipcMain.on('mia:playback-state',(event,active)=>{
    if(!ownSender(event,[bubbleWin,avatarWin]) || typeof active!=='boolean')return;
    if(active){activePlaybackSenders.add(event.sender.id);stopWake();}
    else {activePlaybackSenders.delete(event.sender.id);if(!activePlaybackSenders.size)startWake();}
  });
  ipcMain.on('mia:cancel-dictation',event=>{if(ownSender(event,[bubbleWin]))speech.cancelDictation();});
  // The chat mode is authoritative for capture. OFF closes the native audio stream.
  ipcMain.handle('mia:set-chat-mic-mode', async (event,mode)=>{
    if(!ownSender(event,[bubbleWin]) || !['off','once','conversation'].includes(mode))
      return {ok:false,error:'Modo de micrófono no autorizado.'};
    speech.cancelDictation();
    stopWake();
    config=normalizeConfig({...config,voiceMode:mode});
    speech.setEnabled(mode!=='off');
    await writeConfig();
    if(settingsWin&&!settingsWin.isDestroyed())settingsWin.webContents.send('mia:config-changed',{...config});
    broadcastVoiceStatus(mode==='off'?'Micrófono completamente desactivado.':
      mode==='once'?'Micrófono listo: solo escucha al pulsar Hablar.':'Conversación autorizada desde el chat.');
    if(mode!=='off' && !microphoneInUse)startWake();
    return {ok:true,mode,commandsEnabled:mode!=='off'&&config.wakePhraseEnabled};
  });
  ipcMain.handle('mia:recognize-once', async event => {
    if (!ownSender(event, [bubbleWin])) return { ok: false, error: 'No autorizado.' };
    if(config.voiceMode==='off')return {ok:false,code:'MIC_OFF',error:'El micrófono está desactivado. Cambia el modo en Configuración.'};
    if (microphoneInUse) return { ok: false, error: 'El micrófono ya está ocupado.' };
    stopWake(); microphoneInUse = true;
    avatarAction('LISTEN');
    broadcastVoiceStatus('Preparando reconocimiento local Vosk + Whisper…', true);
    try {
      const result=await speech.recognizeOnce(config.wakePhrase, () => broadcastVoiceStatus('Micrófono preparado. Habla ahora.', true));
      if(config.voiceMode==='off')return {ok:false,code:'MIC_OFF',error:'El micrófono se ha desactivado. No se procesará el dictado.'};
      if(result.ok && result.command){
        setImmediate(()=>onSpokenCommand(result.command));
        return {ok:false,code:'COMMAND_HANDLED',error:'Orden de escritorio ejecutada, sin enviarla al chat.'};
      }
      if(result.ok && typeof result.text==='string'){
        const spoken=result.text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[.?!,]/g,'').trim();
        const norm=p=>p.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[.?!,]/g,'').trim();
        if(spoken===norm(config.hidePhrase) && (result.confidence??0)>=.72){
          setImmediate(()=>onSpokenCommand('HIDE'));return {ok:false,code:'HIDDEN',error:'mIA ejecutará la despedida y se ocultará.'};
        }
        if(spoken===norm(config.exitPhrase) && (result.confidence??0)>=.88){
          setImmediate(()=>onSpokenCommand('EXIT'));return {ok:false,code:'EXIT_CONFIRM',error:'Confirma si deseas cerrar mIA Desktop.'};
        }
      }
      return result;
    }
    finally { microphoneInUse = false; broadcastVoiceStatus('Micrófono en reposo.'); if(!ceremonyBusy)avatarAction('IDLE'); if(!ceremonyBusy)startWake(); }
  });
  ipcMain.handle('mia:speak', async (event, text) => {
    if (!ownSender(event, [bubbleWin, avatarWin]) || !config.voiceEnabled || typeof text !== 'string' || !text.trim())
      return { error: 'Voz desactivada o solicitud no autorizada.' };
    const started=Date.now();
    try { const out=await backend.speak(config.backendBase,text); diagnostics.record('backend_tts',{mode:'tts',code:out.error?'REQUEST_FAILED':'OK',httpStatus:out.code,durationMs:Date.now()-started});return out; }
    catch(e){diagnostics.record('backend_tts',{mode:'tts',code:'UNHANDLED_ERROR'});throw e;}
  });
  ipcMain.handle('mia:send-prompt', async (event, text) => {
    if (!ownSender(event, [bubbleWin]) || typeof text !== 'string' || text.trim().length > 2000) return { error: 'Entrada no válida.' };
    if (!text.trim()) return { error: 'Escribe o dicta una consulta.' };
    const started=Date.now();
    try { const out=await backend.sendPrompt(config.backendBase,text.trim(),conversationSession);diagnostics.record('backend_chat',{mode:'backend',code:out.identityBlocked?out.identityCode:(out.error?'REQUEST_FAILED':(out.identitySelection||'OK')),durationMs:Date.now()-started});return out; }
    catch(e){diagnostics.record('backend_chat',{mode:'backend',code:'UNHANDLED_ERROR'});throw e;}
  });
  ipcMain.on('mia:avatar-ready', event => {
    if(!ownSender(event,[avatarWin]) || greetingTriggered || !visibility.canAutoShow()) return;
    greetingTriggered=true;
    if(config.startupGreeting) {
      const h=new Date().getHours(); const salutation=h<13?'Buenos días':h<21?'Buenas tardes':'Buenas noches';
      const welcome=`${salutation}${config.greetingName ? ', '+config.greetingName : ''}. Soy Mía, estoy aquí para ayudarte.`;
      avatarWin.webContents.send('mia:startup-greeting',{text:welcome, voiceEnabled:config.voiceEnabled, fallbackEnabled:config.voiceFallbackEnabled});
    }
  });
  ipcMain.handle('mia:export-table', async (event, request) => {
    if(!ownSender(event,[resultsWin]) || !lastResultsPayload || !request || typeof request !== 'object')return {ok:false,error:'Exportación no autorizada.'};
    const {tableIndex, rowIndices, format} = request;
    const tables=lastResultsPayload.presentation?.tables;
    if(!Array.isArray(tables) || !Number.isInteger(tableIndex) || tableIndex<0 || tableIndex>=tables.length || !['csv','xlsx'].includes(format))return {ok:false,error:'Tabla o formato incorrectos.'};
    try {
      const content=format==='csv'?tableExport.toCSV(tables[tableIndex],rowIndices):tableExport.toXLSX(tables[tableIndex],rowIndices);
      const selected=await dialog.showSaveDialog(resultsWin,{title:'Exportar tabla autorizada de mIA',defaultPath:`mia-sbc-listado.${format}`,filters:[{name:format==='csv'?'CSV para Excel':'Excel',extensions:[format]}]});
      if(selected.canceled || !selected.filePath)return {ok:false,canceled:true};
      await fsp.writeFile(selected.filePath, content, {flag:'w'});
      return {ok:true,rows:rowIndices?.length??tables[tableIndex].rows.length, partial:tables[tableIndex].truncated || tables[tableIndex].total>tables[tableIndex].received};
    }catch(e){return {ok:false,error:e.message};}
  });
  ipcMain.handle('mia:probe-voice', async event => {
    if(!ownSender(event,[settingsWin]))return {ok:false,error:'No autorizado.'};
    if(config.voiceMode==='off')return {ok:false,code:'MIC_OFF',error:'Activa temporalmente el micrófono para realizar el diagnóstico.'};
    return speech.probe();
  });
  ipcMain.handle('mia:open-diagnostics', async event => {
    if(!ownSender(event,[settingsWin]))return false;
    await shell.openPath(diagnostics.folder());
    return true;
  });
  ipcMain.on('mia:renderer-error', (event, info) => {
    if(!ownSender(event,[avatarWin,bubbleWin,settingsWin,resultsWin]))return;
    diagnostics.record('renderer_error',{mode:'ui',code:typeof info?.code==='string'?info.code:'UNEXPECTED_ERROR'});
  });
  ipcMain.handle('mia:pick-mia-logo', async event => {
    if(!ownSender(event,[settingsWin]))return {ok:false,error:'No autorizado.'};
    const choice=await dialog.showOpenDialog(settingsWin,{title:'Selecciona el logotipo original de mIA (PNG)',properties:['openFile'],filters:[{name:'Imagen PNG',extensions:['png']}]});
    if(choice.canceled||!choice.filePaths[0])return {ok:false,canceled:true};
    try{
      const source=choice.filePaths[0];const data=await fsp.readFile(source);
      const png=Buffer.from([137,80,78,71,13,10,26,10]);
      if(data.length<80||data.length>5*1024*1024||!data.subarray(0,8).equals(png))throw Error('Selecciona un PNG válido de hasta 5 MB.');
      await fsp.mkdir(path.dirname(customMiaLogoFile()),{recursive:true});
      await fsp.writeFile(customMiaLogoFile()+'.tmp',data,{mode:0o600});
      await fsp.rename(customMiaLogoFile()+'.tmp',customMiaLogoFile());
      if(tray&&!tray.isDestroyed())tray.setImage(trayImage());
      for(const win of [bubbleWin,settingsWin,resultsWin])if(win&&!win.isDestroyed())win.webContents.send('mia:branding-ready',true);
      diagnostics.record('branding',{mode:'ui',code:'MIA_LOGO_UPDATED'});
      return {ok:true};
    }catch(e){diagnostics.record('branding',{mode:'ui',code:'MIA_LOGO_ERROR'});return {ok:false,error:'No se ha podido importar el PNG. Comprueba el formato y permisos.'};}
  });
  ipcMain.handle('mia:pick-model', async event => {
    if (!ownSender(event, [settingsWin])) return { ok: false, error: 'No autorizado.' };
    const choice = await dialog.showOpenDialog(settingsWin, {
      title: 'Selecciona el GLB original de mIA SBC',
      properties: ['openFile'],
      filters: [{ name: 'Modelo glTF binario', extensions: ['glb'] }]
    });
    if (choice.canceled || !choice.filePaths[0]) return { ok: false, canceled: true };
    const from = choice.filePaths[0];
    try {
      const stats = await fsp.stat(from);
      if (!stats.isFile() || stats.size < 20 || stats.size > 200 * 1024 * 1024) throw Error('El archivo debe ser un GLB de hasta 200 MB.');
      const f = await fsp.open(from, 'r');
      const buf = Buffer.alloc(4); try { await f.read(buf, 0, 4, 0); } finally { await f.close(); }
      if (buf.toString('ascii') !== 'glTF') throw Error('El archivo no parece un GLB válido.');
      await fsp.mkdir(path.dirname(modelFile()), { recursive: true });
      const temp = `${modelFile()}.temp`;
      await fsp.copyFile(from, temp);
      await fsp.rename(temp, modelFile());
      avatarWin.webContents.send('mia:model-changed', true);
      return { ok: true };
    } catch (error) { return { ok: false, error: error.message }; }
  });
  ipcMain.handle('mia:save-settings', async (event, values) => {
    if (!ownSender(event, [settingsWin])) return { ok: false, error: 'No autorizado.' };
    const prior = config;
    const proposed = normalizeConfig({ ...config, ...values });
    const spoken=[proposed.wakePhrase,proposed.hidePhrase,proposed.exitPhrase].map(x=>x.toLocaleLowerCase('es'));
    if(new Set(spoken).size!==3)return {ok:false,error:'Las tres frases de voz deben ser distintas.'};
    if (proposed.shortcut !== prior.shortcut && !registerShortcut(proposed.shortcut)) {
      registerShortcut(prior.shortcut);
      return { ok: false, error: 'El atajo de teclado está ocupado o no es válido.' };
    }
    config = proposed;
    avatarWin.setAlwaysOnTop(config.alwaysOnTop);
    if (bubbleWin && !bubbleWin.isDestroyed()) bubbleWin.setAlwaysOnTop(config.alwaysOnTop);
    const old=avatarWin.getBounds(); const area=screen.getDisplayMatching(old).workArea;
    avatarWin.setBounds({x:Math.round(clamp(old.x+(old.width-config.avatarWidth)/2,area.x,area.x+area.width-config.avatarWidth)),
      y:Math.round(clamp(old.y+old.height-config.avatarHeight,area.y,area.y+area.height-config.avatarHeight)),
      width:config.avatarWidth,height:config.avatarHeight});
    if(bubbleWin&&!bubbleWin.isDestroyed()){ bubbleWin.setSize(config.bubbleWidth,config.bubbleHeight); if(bubbleWin.isVisible())positionCompanion(bubbleWin); }
    applyLoginSetting();
    await writeConfig();
    avatarWin.webContents.send('mia:config-changed', { subtleMovement: config.subtleMovement, idleWalkCircle:config.idleWalkCircle, idleBored:config.idleBored });
    if(bubbleWin && !bubbleWin.isDestroyed())bubbleWin.webContents.send('mia:config-changed',{...config});
    speech.setEnabled(config.voiceMode!=='off');
    startWake();
    return { ok: true, config: { ...config } };
  });
}

app.on('second-instance', () => { if (avatarWin) openBubble(); });
app.on('window-all-closed', () => { /* El proceso permanece residente en la bandeja. */ });
app.on('will-quit', () => { speech.cancelDictation(); stopWake(); speech.shutdown(); globalShortcut.unregisterAll(); });
app.whenReady().then(async () => {
  readConfig();
  diagnostics.init(app.getPath('userData'), app.getVersion());
  speech.configure(app.getPath('userData'));
  speech.setEnabled(config.voiceMode!=='off');
  protocol.handle('mia', async request => {
    const u = new URL(request.url);
    if (u.hostname !== 'assets' || request.method !== 'GET') return new Response('Not found', { status: 404 });
    const isLogo=u.pathname==='/sunset-logo.png';
    const isMiaLogo=u.pathname==='/mia-logo.png';
    if(!isLogo && !isMiaLogo && u.pathname!=='/avatar.glb') return new Response('Not found',{status:404});
    const file=isLogo?currentBrandFile():isMiaLogo?currentMiaLogoFile():currentModel();
    if(!file) return new Response('Not found',{status:404});
    try {return new Response(await fsp.readFile(file),{status:200,headers:{'content-type':isLogo||isMiaLogo?'image/png':'model/gltf-binary','access-control-allow-origin':'*','cache-control':'no-store'}});}
    catch{return new Response('Asset unavailable',{status:404});}
  });
  avatarWin = createWindow('avatar', {
    width: config.avatarWidth, height: config.avatarHeight,
    transparent: true, frame: false, hasShadow: false, resizable: false,
    skipTaskbar: true, alwaysOnTop: config.alwaysOnTop,
    focusable: true, roundedCorners: false
  });
  positionAvatar();
  avatarWin.once('ready-to-show', () => {if(visibility.canAutoShow())focusAvatar();});
  avatarWin.webContents.once('did-finish-load', () => {if(visibility.canAutoShow() && !avatarWin.isVisible())focusAvatar();});
  avatarWin.on('close', e => { if (!app.isQuitting) { e.preventDefault(); hideAvatar(); } });
  applyLoginSetting();
  createTray();
  setupIPC();
  if (!registerShortcut(config.shortcut)) {console.warn('Atajo no disponible:', config.shortcut);diagnostics.record('shortcut',{mode:'ui',code:'REGISTER_FAILED'});}
  if (app.isPackaged) app.setAppUserModelId('es.sunsetbeachclub.mia.desktop');
  startWake();
  cacheBrandLogo().catch(console.warn);
}).catch(e => { diagnostics.record('startup',{mode:'ui',code:'STARTUP_ERROR'});dialog.showErrorBox('mIA Desktop','No se ha podido iniciar mIA Desktop. Consulta los diagnósticos.');app.quit(); });
