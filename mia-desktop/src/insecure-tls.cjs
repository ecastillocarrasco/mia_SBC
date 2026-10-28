'use strict';
// SOLO PARA PRUEBAS: permite hablar con un backend mIA que sirve un certificado TLS
// autofirmado (p. ej. mia-pre.sunsetbeachclub.local mientras no tenga un certificado de una CA
// de confianza). Nunca se activa por si sola: exige MIA_DESKTOP_INSECURE_TLS=1 en el entorno del
// proceso, explicito en cada arranque, nunca persistido en la configuracion del usuario ni
// expuesto en Ajustes, para que no pueda quedarse encendido sin que alguien lo decida esa sesion.
//
// Primera version usaba un dispatcher de undici (Agent con rejectUnauthorized:false), pero ese
// paquete no es una dependencia real de la app (solo aparecia por casualidad como dependencia
// transitiva de una herramienta de desarrollo) y no viaja en el instalador: funcionaba en local
// sin empaquetar y fallaba siempre en la app instalada. En su lugar, se activa
// NODE_TLS_REJECT_UNAUTHORIZED solo durante el `await` de cada peticion fetch concreta hacia el
// backend y se restaura justo despues (incluso si la peticion falla) — no depende de ningun
// modulo adicional, solo de Node. Sigue sin tocar NADA fuera de esa ventana: las llamadas reales
// de @azure/msal-node hacia login.microsoftonline.com no pasan por aqui.
let warned = false;
async function withInsecureTls(run) {
  if (process.env.MIA_DESKTOP_INSECURE_TLS !== '1') return run();
  if (!warned) {
    warned = true;
    console.warn('[mIA Desktop] MIA_DESKTOP_INSECURE_TLS=1: validacion de certificado TLS DESACTIVADA al hablar con el backend configurado. Solo para pruebas en red de confianza; nunca debe usarse asi en produccion.');
  }
  const previous = process.env.NODE_TLS_REJECT_UNAUTHORIZED;
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
  try {
    return await run();
  } finally {
    if (previous === undefined) delete process.env.NODE_TLS_REJECT_UNAUTHORIZED;
    else process.env.NODE_TLS_REJECT_UNAUTHORIZED = previous;
  }
}
module.exports = { withInsecureTls };
