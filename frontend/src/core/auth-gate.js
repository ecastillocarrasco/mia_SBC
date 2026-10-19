/**
 * mIA — puerta de autenticación compartida por los 4 puntos de entrada del front-end (portal
 * `index.html`, 2D, 3D, holograma). Consulta `GET /api/auth/config` (público, sin sesión) para
 * saber si el backend exige login real contra Entra ID (`MIA_AUTH__MODE=entra`) o no
 * (`dev`/`easyauth`: no-op, mismo comportamiento que hoy, sin tocar nada).
 *
 * Si hace falta iniciar sesión y no hay ya una cuenta MSAL activa, `ensureAuthenticated()`
 * redirige a Microsoft (`loginRedirect`) y la promesa NUNCA se resuelve en ese caso: la
 * navegación sustituye a la página actual, así que no hay "código después" que ejecutar — el
 * llamador debe awaitarla ANTES de montar cualquier UI (`MiaBootLoader`, el avatar, el chat…),
 * nunca en paralelo con el arranque real.
 *
 * Esto es la puerta de UX (a dónde se manda al usuario), NO el límite de seguridad real: el
 * backend ya rechaza con 401/403 cualquier llamada sin un token válido
 * (`mia.api.deps.get_user`/`require()`), con o sin esta puerta. Si esta puerta fallara o se
 * saltara por completo, ningún dato sensible se expone solo por eso.
 */

let msalModulePromise = null;

function loadMsal() {
  if (!msalModulePromise) msalModulePromise = import('@azure/msal-browser');
  return msalModulePromise;
}

async function fetchAuthConfig() {
  const response = await fetch('/api/auth/config', { credentials: 'omit' });
  if (!response.ok) throw new Error(`/api/auth/config respondió ${response.status}`);
  return response.json();
}

/** Promesa que nunca se resuelve: usada tras lanzar una navegación real (loginRedirect). */
function neverResolves() {
  return new Promise(() => {});
}

/**
 * Debe llamarse ANTES de montar cualquier UI real. Devuelve la cuenta MSAL activa, o `null` si
 * el login está desactivado (modo dev/easyauth) — en ese caso el llamador continúa exactamente
 * como hoy, sin ningún cambio de comportamiento.
 */
export async function ensureAuthenticated() {
  let config;
  try {
    config = await fetchAuthConfig();
  } catch (error) {
    // Fallo transitorio contactando al propio backend de mIA: nunca bloquea el arranque por
    // esto — mismo principio que el resto de mIA, "fail open" solo hacia el comportamiento que
    // YA existía antes de esta puerta, nunca hacia saltarse un login que sí se pudo comprobar.
    console.error('[mIA Auth] No se pudo leer /api/auth/config, continuando sin puerta de login:', error);
    return null;
  }
  if (!config.requires_login) return null;

  const { PublicClientApplication } = await loadMsal();
  const msal = new PublicClientApplication({
    auth: {
      clientId: config.entra.client_id,
      authority: `https://login.microsoftonline.com/${config.entra.tenant_id}`,
      redirectUri: window.location.origin + window.location.pathname,
    },
    cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
  });
  await msal.initialize();
  window.msalInstance = msal;

  const redirectResult = await msal.handleRedirectPromise();
  if (redirectResult?.account) msal.setActiveAccount(redirectResult.account);

  window.__miaAuthScope = config.entra.scope;

  const account = msal.getActiveAccount() || msal.getAllAccounts()[0] || null;
  if (account) {
    msal.setActiveAccount(account);
    return account;
  }

  await msal.loginRedirect({ scopes: [config.entra.scope] });
  return neverResolves();
}

/**
 * Token de acceso para adjuntar como `Authorization: Bearer <token>` en las llamadas a la API de
 * mIA. `null` si el login está desactivado o si todavía no hay cuenta activa (no debería ocurrir
 * tras un `ensureAuthenticated()` exitoso, salvo que el llamador no haya esperado a que termine).
 */
export async function getAccessToken() {
  const msal = window.msalInstance;
  if (!msal) return null;
  const account = msal.getActiveAccount();
  if (!account) return null;
  const scopes = [window.__miaAuthScope || msal.getConfiguration().auth.clientId + '/.default'];
  try {
    const result = await msal.acquireTokenSilent({ scopes, account });
    return result.accessToken;
  } catch (error) {
    console.warn('[mIA Auth] No se pudo renovar el token en silencio, reintentando con redirect:', error);
    await msal.acquireTokenRedirect({ scopes, account });
    return null; // La página está navegando; no hay token que devolver todavía.
  }
}

// El mundo 2D en producción (mia-2d.js, mia-enhance.js) son scripts clásicos (sin type="module"):
// no pueden hacer `import` de este módulo, así que leen el token a través de este global.
if (typeof window !== 'undefined') window.miaGetAccessToken = getAccessToken;
