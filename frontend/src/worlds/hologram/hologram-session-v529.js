/** Aislamiento por mundo y traspaso EXPLICITO, una sola vez, misma pestaña. */
const HG_SESSION_KEY = 'mia.world.hologram.session.v529';
const HG_HANDOFF_KEY = 'mia.world.pending-handoff.v529';
const HG_HANDOFF_MAX_MS = 120000;
const hgSafeObject = (x) => x && typeof x === 'object' && !Array.isArray(x);
function hgReadJSON(key) {
  try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return null; }
}
export function readHologramWorldContext() {
  try {
    const transfer = hgReadJSON(HG_HANDOFF_KEY);
    if (hgSafeObject(transfer)) {
      if (transfer.from === 'hologram' || Date.now() - Number(transfer.at || 0) > HG_HANDOFF_MAX_MS) {
        sessionStorage.removeItem(HG_HANDOFF_KEY);
      } else if ((transfer.to === 'any' || transfer.to === 'hologram') &&
                 hgSafeObject(transfer.context) && Number(transfer.at) <= Date.now()) {
        sessionStorage.removeItem(HG_HANDOFF_KEY);
        return {context: transfer.context, source: 'world-switch'};
      }
    }
    const saved = hgReadJSON(HG_SESSION_KEY);
    if (hgSafeObject(saved?.context)) return {context:saved.context, source:'same-world'};
  } catch { /* navegador sin sessionStorage */ }
  return {context:{},source:'new'};
}
export function saveHologramWorldContext(context) {
  if (!hgSafeObject(context)) return;
  try { sessionStorage.setItem(HG_SESSION_KEY, JSON.stringify({context,at:Date.now()})); }
  catch { /* sesión en memoria */ }
}
export function handoffHologramOnNavigation(context, destination = 'any') {
  if (!hgSafeObject(context)) return;
  saveHologramWorldContext(context);
  try {
    sessionStorage.setItem(HG_HANDOFF_KEY, JSON.stringify({
      from:'hologram',to:destination,at:Date.now(),context,
    }));
  } catch { /* no bloquear la navegación */ }
}
/** No activa transferencias con descargas, enlaces externos ni eventos ordinarios. */
export function bindHologramWorldNavigation(root, getContext) {
  root.addEventListener('click', (event) => {
    const anchor = event.target?.closest?.('a[href]');
    if (!anchor || anchor.download || (anchor.target && anchor.target !== '_self') ||
        event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    let parsed;
    try { parsed = new URL(anchor.href); } catch { return; }
    if (parsed.origin !== location.origin || !/\/(?:index|mia-2d)\.html$|\/src\/worlds\/(?:2d|3d|hologram)\/index\.html$/i.test(parsed.pathname)) return;
    const to = /\/mia-2d\.html$|\/src\/worlds\/2d\/index\.html$/i.test(parsed.pathname)
      ? '2d' : /\/src\/worlds\/hologram\/index\.html$/i.test(parsed.pathname)
      ? 'hologram' : 'any';
    if (to !== 'hologram') handoffHologramOnNavigation(getContext(),to);
  }, true);
}
