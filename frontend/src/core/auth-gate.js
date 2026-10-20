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
 *
 * Autenticación (¿tiene un token válido?) y autorización (¿tiene algún permiso asignado?) son
 * cosas distintas: `ensureAuthorized()` cubre la segunda, llamando a `GET /api/auth/me` justo
 * después de un login real. Si la cuenta no tiene ningún permiso, o si la comprobación falla,
 * sustituye TODA la página por una pantalla de acceso con el lenguaje visual de mIA — nunca deja
 * que el mundo (boot loader, avatar, chat…) se quede montado sin avisar de que no sirve para nada.
 */

import './access-screen.css';

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
 *
 * `interactive` (por defecto `true`): si es `false` y no hay ya una cuenta MSAL cacheada
 * (`sessionStorage`, compartida entre páginas del mismo origen), esta función NUNCA lanza su
 * propio `loginRedirect` — en vez de eso navega de vuelta al índice (`import.meta.env.BASE_URL`)
 * para que el login real ocurra ahí. Motivo: cada página tiene su propia `redirectUri`
 * (`window.location.pathname`), y Entra ID exige cada una dada de alta por separado
 * (AADSTS500113 si no lo está) — los 3 mundos (2D/3D/holograma) usan `interactive: false` para
 * que SOLO la URI del índice necesite registrarse, nunca la de cada mundo. El índice
 * (`landing-3d-v48.js`) sigue llamando con el valor por defecto (`true`): ahí sí debe iniciar el
 * login real.
 */
export async function ensureAuthenticated({ interactive = true } = {}) {
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

  if (!interactive) {
    window.location.href = import.meta.env.BASE_URL;
    return neverResolves();
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

/** Cierra la sesión MSAL y vuelve al índice. Botón de escape en la pantalla de acceso: con un
 * token válido pero sin permisos, no hay otra forma de "probar con otra cuenta" (no hay logout
 * en ningún otro sitio de mIA todavía). */
export async function signOut() {
  const msal = window.msalInstance;
  if (!msal) {
    window.location.reload();
    return;
  }
  try {
    await msal.logoutRedirect({ postLogoutRedirectUri: window.location.origin + import.meta.env.BASE_URL });
  } catch (error) {
    console.error('[mIA Auth] No se pudo cerrar sesión:', error);
    window.location.reload();
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Mismo mecanismo que `install2DEntry()` usa para revelar el mundo 2D real: mientras la cortina
 * de pintura esté puesta, lo que mia-2d.js ya haya montado por debajo (ver el aviso en
 * mia-entry-v530.js sobre el orden de scripts clásicos) permanece oculto. Al mostrar esta
 * pantalla hay que levantarla igual, o nunca se vería. En los otros 3 puntos de entrada (todo
 * módulo, sin scripts clásicos) esta clase simplemente no existe y la llamada no hace nada. */
function liftPaintGuard() {
  document.documentElement.classList.remove('mia2d-entry-loading');
  if (window.__mia2dEntryGuardTimeout) {
    clearTimeout(window.__mia2dEntryGuardTimeout);
    window.__mia2dEntryGuardTimeout = null;
  }
  document.documentElement.style.overflow = '';
}

function showAccessScreen(kind, { displayName, email } = {}) {
  liftPaintGuard();
  const base = import.meta.env.BASE_URL;
  const isError = kind === 'error';
  const screen = document.createElement('div');
  screen.className = `mia-access${isError ? ' mia-access--error' : ''}`;
  screen.setAttribute('role', 'alert');
  const who = displayName
    ? `<p class="mia-access__who">Has iniciado sesión como <strong>${escapeHtml(displayName)}</strong>${
        email ? ` (${escapeHtml(email)})` : ''
      }.</p>`
    : '';
  screen.innerHTML = `
    <div class="mia-access__card">
      <img class="mia-access__logo" src="${base}assets/loading/sunset-beach-club-logo.png" alt="Sunset Beach Club" />
      <div class="mia-access__eyebrow">${isError ? 'NO SE HA PODIDO VERIFICAR' : 'ACCESO RESTRINGIDO'}</div>
      <h1>${isError ? 'Algo ha ido <em>mal</em> comprobando tu acceso' : 'No tienes acceso a <em>mIA</em>'}</h1>
      <p class="mia-access__body">${
        isError
          ? 'No hemos podido comprobar tu acceso a mIA. Puede ser un problema pasajero de conexión.'
          : 'Tu cuenta ha iniciado sesión correctamente, pero todavía no tiene ningún rol asignado en mIA.'
      }</p>
      ${who}
      <p class="mia-access__body">${
        isError
          ? 'Puedes reintentarlo; si el problema persiste, contacta con el administrador.'
          : 'Contacta con el administrador de tu organización para que te asigne acceso.'
      }</p>
      <div class="mia-access__actions">
        <button type="button" class="mia-access__btn" data-action="retry">Reintentar</button>
        <button type="button" class="mia-access__btn mia-access__btn--ghost" data-action="signout">Cerrar sesión y probar con otra cuenta</button>
      </div>
    </div>`;
  document.body.replaceChildren(screen);
  screen.querySelector('[data-action="retry"]').addEventListener('click', () => window.location.reload());
  screen.querySelector('[data-action="signout"]').addEventListener('click', () => signOut());
}

/**
 * Debe llamarse justo después de `ensureAuthenticated()`. Si el login está desactivado (modo
 * dev/easyauth, `window.msalInstance` nunca se inicializó) no hace nada — mismo comportamiento
 * que hoy. Con login real, comprueba contra `GET /api/auth/me` si la cuenta tiene algún permiso:
 * si no tiene ninguno, o si la comprobación falla (red, 401/403 inesperado...), sustituye toda la
 * página por la pantalla de acceso correspondiente y la promesa NUNCA se resuelve — igual que
 * `ensureAuthenticated()` tras un `loginRedirect`, para que nada monte UI real después de esto.
 */
export async function ensureAuthorized() {
  if (!window.msalInstance) return;
  let payload;
  try {
    const token = await getAccessToken();
    const response = await fetch('/api/auth/me', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'omit',
    });
    if (!response.ok) {
      showAccessScreen('error');
      return neverResolves();
    }
    payload = await response.json();
  } catch (error) {
    console.error('[mIA Auth] No se pudo comprobar el acceso:', error);
    showAccessScreen('error');
    return neverResolves();
  }
  if (!payload.has_access) {
    showAccessScreen('unauthorized', { displayName: payload.display_name, email: payload.email });
    return neverResolves();
  }
}
