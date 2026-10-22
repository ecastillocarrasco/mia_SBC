'use strict';
// Puerta de autenticación de mIA Desktop (equivalente de frontend/src/core/auth-gate.js para
// Electron). Consulta GET /api/auth/config (público, sin sesión) para saber si el backend exige
// login real contra Entra ID (MIA_AUTH__MODE=entra) o no (dev/easyauth: no-op).
//
// A diferencia de la web (MSAL.js, redirect de navegador completo), aquí se usa @azure/msal-node
// con el flujo que Microsoft recomienda para apps nativas de escritorio: acquireTokenInteractive
// abre el NAVEGADOR DEL SISTEMA (nunca una ventana embebida de Electron — Microsoft desaconseja
// los webviews embebidos para login desde hace años) con un redirect de loopback
// (http://localhost, sin puerto fijo) que la propia librería captura sola.
//
// El token cacheado se persiste cifrado (Electron safeStorage) en userData, para no pedir login
// cada vez que se abre la app — con refresco silencioso vía acquireTokenSilent.
const fs = require('node:fs');
const path = require('node:path');
const { PublicClientApplication } = require('@azure/msal-node');

let pca = null;
let authConfig = null;
let cachePath = null;

function makeCachePlugin() {
  return {
    beforeCacheAccess: async (cacheContext) => {
      if (!cachePath || !fs.existsSync(cachePath)) return;
      try {
        const raw = fs.readFileSync(cachePath);
        const { safeStorage } = require('electron');
        const text = safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(raw) : raw.toString('utf8');
        cacheContext.tokenCache.deserialize(text);
      } catch (e) {
        console.warn('[mIA Auth] No se pudo leer la caché de sesión, se pedirá login de nuevo:', e);
      }
    },
    afterCacheAccess: async (cacheContext) => {
      if (!cachePath || !cacheContext.cacheHasChanged) return;
      try {
        const text = cacheContext.tokenCache.serialize();
        const { safeStorage } = require('electron');
        const out = safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(text) : Buffer.from(text, 'utf8');
        fs.writeFileSync(cachePath, out, { mode: 0o600 });
      } catch (e) {
        console.warn('[mIA Auth] No se pudo guardar la caché de sesión:', e);
      }
    },
  };
}

async function fetchAuthConfig(base) {
  const response = await fetch(base + '/api/auth/config');
  if (!response.ok) throw new Error(`/api/auth/config respondió ${response.status}`);
  return response.json();
}

async function interactiveLogin() {
  const { shell } = require('electron');
  return pca.acquireTokenInteractive({
    scopes: [authConfig.entra.scope],
    openBrowser: async (url) => { await shell.openExternal(url); },
    successTemplate: '<h1>Sesión iniciada</h1><p>Ya puedes volver a mIA Desktop y cerrar esta pestaña.</p>',
    errorTemplate: '<h1>No se ha podido iniciar sesión</h1><p>%s: %s</p><p>Vuelve a mIA Desktop e inténtalo de nuevo.</p>',
  });
}

/**
 * Debe llamarse ANTES de crear la ventana del avatar. No lanza si el backend no es alcanzable
 * (fail-open hacia el comportamiento previo a esta puerta, igual que auth-gate.js); si el login
 * es necesario y falla o se cancela, se propaga el error para que el llamador decida (mostrar un
 * diálogo y reintentar, o salir) en vez de dejar la app a medio arrancar con un token inválido.
 */
async function ensureAuthenticated(userDataPath, base) {
  try {
    authConfig = await fetchAuthConfig(base);
  } catch (error) {
    console.error('[mIA Auth] No se pudo leer /api/auth/config, continuando sin puerta de login:', error);
    authConfig = { requires_login: false };
    return null;
  }
  if (!authConfig.requires_login) return null;

  cachePath = path.join(userDataPath, 'mia-auth-cache.bin');
  console.log('[mIA Auth] cache de sesion en', cachePath);
  // Por defecto, el mismo client_id que la web (authConfig.entra.client_id, de /api/auth/config)
  // -- funciona, pero Microsoft desaconseja compartir un Registro de la aplicación entre una SPA
  // y un cliente nativo. Con MIA_DESKTOP_ENTRA_CLIENT_ID definido (Registro de la aplicación
  // propio, plataforma "Mobile and desktop applications"), se usa ese en su lugar. El scope y el
  // tenant siguen siendo los mismos: siguen siendo la API expuesta por el Registro de la
  // aplicación de la web (el "recurso"), no cambian por tener un cliente nativo distinto pidiendo
  // el token.
  const clientId = process.env.MIA_DESKTOP_ENTRA_CLIENT_ID || authConfig.entra.client_id;
  pca = new PublicClientApplication({
    auth: {
      clientId,
      authority: `https://login.microsoftonline.com/${authConfig.entra.tenant_id}`,
    },
    cache: { cachePlugin: makeCachePlugin() },
  });
  // msal-node (a diferencia de msal-browser) no tiene pca.getConfiguration(): se registra el
  // valor ya calculado en vez de intentar leerlo de vuelta de la instancia.
  console.log('[mIA Auth] clientId en uso:', clientId,
    process.env.MIA_DESKTOP_ENTRA_CLIENT_ID ? '(MIA_DESKTOP_ENTRA_CLIENT_ID)' : '(compartido con la web)');

  const accounts = await pca.getTokenCache().getAllAccounts();
  if (accounts.length > 0) {
    console.log('[mIA Auth] cuenta ya cacheada, sin login interactivo:', accounts[0].username);
    return accounts[0];
  }

  const result = await interactiveLogin();
  return result.account;
}

/** Token de acceso para `Authorization: Bearer <token>`. `null` si el login está desactivado. */
async function getAccessToken() {
  if (!pca || !authConfig?.requires_login) return null;
  const accounts = await pca.getTokenCache().getAllAccounts();
  if (!accounts.length) return null;
  try {
    const result = await pca.acquireTokenSilent({ account: accounts[0], scopes: [authConfig.entra.scope] });
    return result.accessToken;
  } catch (error) {
    console.warn('[mIA Auth] No se pudo renovar el token en silencio, pidiendo login interactivo:', error);
    const result = await interactiveLogin();
    return result.accessToken;
  }
}

module.exports = { ensureAuthenticated, getAccessToken };
