'use strict';
const { contextBridge, ipcRenderer } = require('electron');
function subscribe(channel, callback) {
  if (typeof callback !== 'function') return () => {};
  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}
contextBridge.exposeInMainWorld('miaDesktop', Object.freeze({
  getState: () => ipcRenderer.invoke('mia:get-state'),
  moveAvatar: (dx, dy) => ipcRenderer.send('mia:move-avatar', dx, dy),
  startDrag: () => ipcRenderer.send('mia:start-drag'),
  stopDrag: () => ipcRenderer.send('mia:stop-drag'),
  resizeBubble: (dx,dy,edge='se') => ipcRenderer.send('mia:resize-bubble', dx, dy, edge),
  avatarReady: () => ipcRenderer.send('mia:avatar-ready'),
  exportTable: (request) => ipcRenderer.invoke('mia:export-table',request),
  setPassthrough: (ignored) => ipcRenderer.send('mia:passthrough', Boolean(ignored)),
  openBubble: () => ipcRenderer.invoke('mia:open-bubble'),
  hideBubble: () => ipcRenderer.invoke('mia:hide-bubble'),
  hideAvatar: () => ipcRenderer.invoke('mia:hide-avatar'),
  openSettings: () => ipcRenderer.invoke('mia:open-settings'),
  openResults: (payload) => ipcRenderer.invoke('mia:open-results', payload),
  pickModel: () => ipcRenderer.invoke('mia:pick-model'),
  pickMiaLogo: () => ipcRenderer.invoke('mia:pick-mia-logo'),
  probeVoice: () => ipcRenderer.invoke('mia:probe-voice'),
  openDiagnostics: () => ipcRenderer.invoke('mia:open-diagnostics'),
  reportRendererError: code => ipcRenderer.send('mia:renderer-error',{code:typeof code==='string'?code:'UNEXPECTED_ERROR'}),
  saveSettings: (settings) => ipcRenderer.invoke('mia:save-settings', settings),
  sendPrompt: (prompt) => ipcRenderer.invoke('mia:send-prompt', prompt),
  recognizeOnce: () => ipcRenderer.invoke('mia:recognize-once'),
  setChatMicMode: mode => ipcRenderer.invoke('mia:set-chat-mic-mode',mode),
  stopDictation: () => ipcRenderer.send('mia:cancel-dictation'),
  playbackState: active => ipcRenderer.send('mia:playback-state',Boolean(active)),
  speak: text => ipcRenderer.invoke('mia:speak', text),
  avatarAction: name => ipcRenderer.send('mia:avatar-action', name),
  avatarContextMenu: () => ipcRenderer.send('mia:avatar-context-menu'),
  onMicrophoneRequest: cb => subscribe('mia:microphone-request', cb),
  onStopConversation: cb => subscribe('mia:stop-conversation',cb),
  onAvatarAction: cb => subscribe('mia:avatar-action', cb),
  onConfigChanged: cb => subscribe('mia:config-changed', cb),
  onVoiceStatus: cb => subscribe('mia:voice-status', cb),
  onModelChanged: (cb) => subscribe('mia:model-changed', cb),
  onResultsData: (cb) => subscribe('mia:results-data', cb),
  onAvatarVisibility: (cb) => subscribe('mia:avatar-visibility', cb),
  onStartupGreeting: (cb) => subscribe('mia:startup-greeting',cb),
  onAvatarCeremony: cb => subscribe('mia:avatar-ceremony',cb),
  ceremonyFinished: id => ipcRenderer.send('mia:ceremony-finished',id),
  onBrandingReady: (cb) => subscribe('mia:branding-ready',cb)
}));
