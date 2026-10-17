'use strict';
const DEFAULTS = Object.freeze({
  shortcut: 'CommandOrControl+Alt+M',
  alwaysOnTop: true,
  launchAtLogin: false,
  avatarWidth: 250,
  avatarHeight: 345,
  bubbleWidth: 500,
  bubbleHeight: 490,
  startupGreeting: true,
  greetingName: '',
  idleWalkCircle: true,
  idleBored: true,
  subtleMovement: true,
  backendBase: 'http://127.0.0.1:5001',
  voiceEnabled: true,
  voiceFallbackEnabled: true,
  wakePhrase: 'Hola mIA',
  hidePhrase: 'Oculta mIA',
  exitPhrase: 'Cierra mIA',
  voiceMode: 'once', // off | once | conversation
  wakePhraseEnabled: false,
  autoListenOnWake: false,
  autoListenOnShow: false,
  autoSendDictation: false
});
const VALID_SHORTCUT = /^(?:(?:CommandOrControl|Control|Ctrl|Alt|Shift|Meta|Super|Command)\+){1,4}(?:[A-Z0-9]|F(?:[1-9]|1[0-2]))$/i;
function normalizeBackendUrl(raw) {
  if (typeof raw !== 'string' || raw.length > 250) return DEFAULTS.backendBase;
  try {
    const u = new URL(raw.trim());
    if (u.username || u.password || u.search || u.hash || u.pathname !== '/') return DEFAULTS.backendBase;
    // Plain HTTP only accepted on loopback. HTTPS supports a manually configured SBC server.
    const isLocal = ['127.0.0.1','localhost','[::1]'].includes(u.hostname.toLowerCase());
    if (u.protocol !== 'https:' && !(u.protocol === 'http:' && isLocal)) return DEFAULTS.backendBase;
    return u.origin;
  } catch { return DEFAULTS.backendBase; }
}
function normalizeConfig(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) input = {};
  const shortcut = typeof input.shortcut === 'string' && VALID_SHORTCUT.test(input.shortcut.trim())
    ? input.shortcut.trim() : DEFAULTS.shortcut;
  const boundedSize = (value, d, min, max) => Number.isInteger(value) && value >= min && value <= max ? value : d;
  const bool = k => typeof input[k] === 'boolean' ? input[k] : DEFAULTS[k];
  // Wake phrase allows ordinary spoken Spanish; no executable content or command expansion.
  const phrase = typeof input.wakePhrase === 'string' && /^[\p{L}\p{M}\p{N} .,'-]{3,48}$/u.test(input.wakePhrase.trim())
    ? input.wakePhrase.trim() : DEFAULTS.wakePhrase;
  const voiceMode=['off','once','conversation'].includes(input.voiceMode)?input.voiceMode:DEFAULTS.voiceMode;
  const spoken = key => typeof input[key] === 'string' && /^[\p{L}\p{M}\p{N} .,'-]{3,48}$/u.test(input[key].trim()) ? input[key].trim() : DEFAULTS[key];
  return {
    shortcut, alwaysOnTop: bool('alwaysOnTop'), launchAtLogin: bool('launchAtLogin'),
    subtleMovement: bool('subtleMovement'),
    avatarWidth: boundedSize(input.avatarWidth, DEFAULTS.avatarWidth, 170, 390),
    avatarHeight: boundedSize(input.avatarHeight, DEFAULTS.avatarHeight, 235, 540),
    bubbleWidth: boundedSize(input.bubbleWidth, DEFAULTS.bubbleWidth, 390, 1000),
    bubbleHeight: boundedSize(input.bubbleHeight, DEFAULTS.bubbleHeight, 385, 850),
    startupGreeting: bool('startupGreeting'),
    greetingName: typeof input.greetingName === 'string' && /^[\p{L}\p{M} .'-]{0,40}$/u.test(input.greetingName.trim()) ? input.greetingName.trim() : DEFAULTS.greetingName,
    idleWalkCircle: bool('idleWalkCircle'),
    idleBored: bool('idleBored'),
    backendBase: normalizeBackendUrl(input.backendBase ?? DEFAULTS.backendBase),
    voiceEnabled: bool('voiceEnabled'), voiceFallbackEnabled: bool('voiceFallbackEnabled'),
    wakePhrase: phrase, hidePhrase:spoken('hidePhrase'),exitPhrase:spoken('exitPhrase'),voiceMode,
    wakePhraseEnabled: bool('wakePhraseEnabled'),
    // Legacy auto-listening preferences are deliberately disabled for privacy.
    autoListenOnWake: false,
    autoListenOnShow: false,
    autoSendDictation: bool('autoSendDictation')
  };
}
function clamp(n, low, high) { return Math.max(low, Math.min(high, n)); }
function placeNear(bounds, size, workArea) {
  const x = bounds.x >= workArea.x + workArea.width / 2
    ? bounds.x - size.width - 10 : bounds.x + bounds.width + 10;
  return {
    x: Math.round(clamp(x, workArea.x + 8, workArea.x + workArea.width - size.width - 8)),
    y: Math.round(clamp(bounds.y + bounds.height * .25 - size.height * .5, workArea.y + 8, workArea.y + workArea.height - size.height - 8))
  };
}
module.exports = { DEFAULTS, normalizeConfig, normalizeBackendUrl, clamp, placeNear };
