/**
 * mIA SBC V4.5 — Welcome identity, privacy-safe and future MSAL ready.
 * There is NO authentication in this module. The signed-in MSAL account must
 * be supplied by the future authentication layer.
 */
const DEFAULT_DEV_NAME = 'Enrique';

function textName(value) {
  if (typeof value !== 'string') return '';
  const valueClean = value.trim().replace(/\s+/g, ' ');
  if (!valueClean) return '';
  // Never interpolate arbitrary HTML or a raw email address into the welcome.
  const candidate = valueClean.includes('@') ? valueClean.split('@')[0].split(/[._-]/)[0] : valueClean.split(' ')[0];
  if (!/^[\p{L}][\p{L}'’-]{0,39}$/u.test(candidate)) return '';
  return candidate.charAt(0).toLocaleUpperCase('es-ES') + candidate.slice(1).toLocaleLowerCase('es-ES');
}

export function firstNameFromAccount(account) {
  if (!account || typeof account !== 'object') return '';
  const claims = account.idTokenClaims ?? account.claims ?? {};
  return textName(claims.given_name) || textName(account.givenName) ||
    textName(account.name) || textName(account.displayName) ||
    textName(claims.name) || textName(account.username) || '';
}

export function resolveWelcomeName({ account = null, development = false, devName = DEFAULT_DEV_NAME } = {}) {
  return firstNameFromAccount(account) || (development ? textName(devName) : '');
}

/**
 * Forward-looking adapter. Production MUST NOT guess a name or force an
 * arbitrary MSAL account if several are available.
 */
export function activeIdentity(win = typeof window === 'undefined' ? null : window) {
  if (!win) return null;
  try {
    const host = win.miaAuth ?? win.mIAAuth;
    const supplied = host?.getActiveAccount?.() ?? host?.activeAccount ?? host?.account;
    if (supplied) return supplied;
    const msal = win.msalInstance;
    if (msal?.getActiveAccount) return msal.getActiveAccount() ?? null;
  } catch { /* future auth provider may not be ready yet */ }
  return null;
}

// Varias formulaciones equivalentes en tono y contenido: se elige una al azar en cada
// saludo para que no suene siempre a la misma frase grabada. Todas mantienen el nombre
// real (o ninguno, si no hay cuenta activa) y la invitación a preguntar.
const WELCOME_TEMPLATES_WITH_NAME = [
  (name) => `¡Hola ${name}! Soy mIA, tu asistente virtual. Estoy aquí para ayudarte con cualquier consulta. ¿Qué te gustaría saber?`,
  (name) => `¡Hola ${name}! Qué alegría verte por aquí. Soy mIA, ¿en qué puedo ayudarte hoy?`,
  (name) => `Bienvenido de nuevo, ${name}. Soy mIA, tu asistente virtual. Dime qué necesitas y te ayudo.`,
  (name) => `¡Hola, ${name}! Aquí estoy para lo que necesites. ¿Qué te gustaría consultar?`,
  (name) => `${name}, un placer tenerte por aquí otra vez. Soy mIA. ¿Qué te gustaría saber?`,
];
const WELCOME_TEMPLATES_NO_NAME = [
  () => '¡Hola! Soy mIA, tu asistente virtual. Estoy aquí para ayudarte con cualquier consulta. ¿Qué te gustaría saber?',
  () => '¡Hola! Soy mIA. ¿En qué puedo ayudarte hoy?',
  () => 'Bienvenido. Soy mIA, tu asistente virtual. Dime qué necesitas y te ayudo.',
];

// Un único número aleatorio por carga de página (no por llamada): getWelcomeText() se
// invoca dos veces en 3D/Holograma (precarga del audio + reproducción real) y deben
// coincidir para reutilizar el audio ya precargado — variar en cada llamada forzaría a
// pedir el audio dos veces y perdería la precarga en paralelo con el GLB pesado.
let sessionPickSeed = null;
function stablePick(count) {
  if (sessionPickSeed === null) sessionPickSeed = Math.floor(Math.random() * 97);
  return sessionPickSeed % count;
}

export function welcomeText({ name = '', pick = null } = {}) {
  const templates = name ? WELCOME_TEMPLATES_WITH_NAME : WELCOME_TEMPLATES_NO_NAME;
  const chooser = pick || stablePick;
  const index = Math.min(Math.max(0, chooser(templates.length)), templates.length - 1);
  return templates[index](name);
}

export function getWelcomeText() {
  const isDev = Boolean(import.meta.env?.DEV);
  const devName = String(import.meta.env?.VITE_MIA_DEV_FIRST_NAME || DEFAULT_DEV_NAME);
  return welcomeText({ name: resolveWelcomeName({ account: activeIdentity(), development: isDev, devName }) });
}
