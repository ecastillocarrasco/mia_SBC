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
 * MSAL guarda en sessionStorage una marca de "hay una interacción en curso" (login/redirect) justo
 * antes de navegar, y la quita al volver (`handleRedirectPromise()`). Si esa vuelta nunca ocurre —
 * la página se recarga a medias, se cierra la pestaña durante el redirect, el intento anterior
 * falló antes de completarse — la marca se queda puesta PARA SIEMPRE: cualquier `loginRedirect()`
 * posterior falla al instante con `interaction_in_progress`, sin llegar nunca a Microsoft, de forma
 * indefinida hasta que algo limpie sessionStorage a mano. Se limpia solo el prefijo `msal.` (no
 * toca `mia.session_id`, la sesión de conversación de `client.js`, que vive en el mismo storage).
 */
function clearStuckMsalState() {
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith('msal.')) sessionStorage.removeItem(key);
    }
  } catch (error) {
    console.warn('[mIA Auth] No se pudo limpiar el estado de MSAL:', error);
  }
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

  // Todo lo que sigue puede fallar de verdad (tenant/client_id mal configurados, msal-browser sin
  // precargar en el dev server de Vite, login.microsoftonline.com inalcanzable...). Antes de este
  // try/catch, cualquier excepción aquí dejaba la cortina de pintura puesta PARA SIEMPRE (nunca se
  // llegaba a `loginRedirect`, nunca se llamaba a `dismissEntryGuard()`) hasta que el timeout de
  // seguridad del HTML la quitaba a los 18s y revelaba el portal sin sesión — nunca un error
  // visible. Ahora cualquier fallo real se muestra con la misma pantalla que un 401/403.
  try {
    if (!config.entra?.web_client_id || !config.entra?.scope) {
      throw new Error('Falta configurar el Client ID de mia_Login o el scope de la API mIA.');
    }
    const { PublicClientApplication } = await loadMsal();
    const msal = new PublicClientApplication({
      auth: {
        clientId: config.entra.web_client_id,
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
  } catch (error) {
    console.error('[mIA Auth] No se pudo iniciar el login con Entra ID:', error);
    // Se limpia PROACTIVAMENTE aquí, no solo al pulsar "Reintentar": así, si el error era
    // precisamente `interaction_in_progress`, el siguiente intento (automático o manual) ya
    // funciona sin que el usuario tenga que saber que existe sessionStorage.
    clearStuckMsalState();
    showAccessScreen('error');
    return neverResolves();
  }
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
    // `acquireTokenRedirect` navega fuera de la página: devolver `null` aquí (como antes) dejaba
    // que el llamador siguiera adelante EN ESE MISMO INSTANTE con "sin token" (ver ensureAuthorized,
    // que entonces llamaba a /api/auth/me sin cabecera Authorization y recibía 401) en vez de
    // esperar a la redirección real — la navegación no detiene la ejecución de JS de inmediato.
    console.warn('[mIA Auth] No se pudo renovar el token en silencio, reintentando con redirect:', error);
    await msal.acquireTokenRedirect({ scopes, account });
    return neverResolves();
  }
}

// El mundo 2D en producción (mia-2d.js, mia-enhance.js) son scripts clásicos (sin type="module"):
// no pueden hacer `import` de este módulo, así que leen el token a través de este global.
if (typeof window !== 'undefined') window.miaGetAccessToken = getAccessToken;

/**
 * Revela un botón de cerrar sesión ya presente en la página (oculto por defecto en el HTML,
 * `hidden`) y lo conecta a `signOut()`. Si el login está desactivado (dev/easyauth) no hace nada:
 * el botón se queda oculto, no hay ninguna sesión real que cerrar. Debe llamarse DESPUÉS de que
 * `ensureAuthenticated()`/`ensureAuthorized()` hayan confirmado que hay una cuenta con acceso —
 * nunca antes, para no revelarlo mientras la cortina de pintura sigue puesta.
 */
export function mountSignOutButton(target) {
  const button = typeof target === 'string' ? document.querySelector(target) : target;
  if (!button || !window.msalInstance) return;
  button.hidden = false;
  button.addEventListener('click', () => signOut());
}

/** Cierra la sesión MSAL y vuelve al índice. Usado por `mountSignOutButton()` y por el botón de
 * escape de la pantalla de acceso: con un token válido pero sin permisos, no hay otra forma de
 * "probar con otra cuenta". */
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

/**
 * Levanta la cortina de pintura síncrona que el `<script>` inline del `<head>` pone ANTES de que
 * este módulo cargue (ver `index.html` y `mia-2d.html`) — mientras está puesta, lo que ya hubiera
 * debajo (los enlaces del portal, o lo que mia-2d.js ya haya montado — ver el aviso en
 * mia-entry-v530.js sobre el orden de scripts clásicos) permanece oculto y, en el caso del
 * portal, SIN POSIBILIDAD DE CLIC real (la cortina cubre toda la página). Debe llamarse tanto al
 * revelar la UI real (login + autorización correctos) como al sustituirla por la pantalla de
 * acceso (`showAccessScreen`) — si no, el aviso se quedaría oculto debajo. En los puntos de
 * entrada sin cortina propia (3D, holograma) estas clases simplemente no existen y no hace nada.
 */
export function dismissEntryGuard() {
  for (const cls of ['mia-index-loading', 'mia2d-entry-loading']) {
    document.documentElement.classList.remove(cls);
  }
  for (const key of ['__miaIndexGuardTimeout', '__mia2dEntryGuardTimeout']) {
    if (window[key]) {
      clearTimeout(window[key]);
      window[key] = null;
    }
  }
  document.documentElement.style.overflow = '';
}

function showAccessScreen(kind, { displayName, email } = {}) {
  dismissEntryGuard();
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
  screen.querySelector('[data-action="retry"]').addEventListener('click', () => {
    // Defensa en profundidad: si el bloqueo venía de un intento de login anterior a este arreglo
    // (interaction_in_progress ya en sessionStorage), reintentar sin limpiar repetiría el mismo
    // error para siempre.
    if (isError) clearStuckMsalState();
    window.location.reload();
  });
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
