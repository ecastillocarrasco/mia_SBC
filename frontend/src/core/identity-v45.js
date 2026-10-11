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

export function welcomeText({ name = '' } = {}) {
  const salutation = name ? `¡Hola ${name}!` : '¡Hola!';
  return `${salutation} Soy Mía, tu asistente virtual. Estoy aquí para ayudarte con cualquier consulta. ¿Qué te gustaría saber?`;
}

export function getWelcomeText() {
  const isDev = Boolean(import.meta.env?.DEV);
  const devName = String(import.meta.env?.VITE_MIA_DEV_FIRST_NAME || DEFAULT_DEV_NAME);
  return welcomeText({ name: resolveWelcomeName({ account: activeIdentity(), development: isDev, devName }) });
}
