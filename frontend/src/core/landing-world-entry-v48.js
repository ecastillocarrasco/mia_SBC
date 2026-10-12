/**
 * mIA V4.8 — Monta una vista dentro del MISMO documento tras el click real.
 *
 * No simula eventos ni altera permisos. Conserva la activacion del usuario
 * mientras los imports asincronos cargan la experiencia. Compatible con
 * links normales en nuevas pestanas, Ctrl/Cmd+click y fallback a ruta directa.
 */
export function installInlineWorldEntry({
  link, markup, loadStyles, loadApp,
  doc = document, win = window,
  parseWorld = (html) => new DOMParser().parseFromString(html, 'text/html'),
  onError = (error) => console.error('[mIA V4.8] Entrada 3D:', error),
} = {}) {
  if (!link || typeof markup !== 'string' || typeof loadStyles !== 'function'
      || typeof loadApp !== 'function') throw new TypeError('Entrada 3D no configurada');
  let entering = false;
  const handler = async (event) => {
    if (event.defaultPrevented || entering || event.button !== 0 || event.ctrlKey
        || event.metaKey || event.shiftKey || event.altKey
        || link.target === '_blank' || link.hasAttribute('download')) return;
    event.preventDefault();
    entering = true;
    const href = link.href;
    try {
      // Parsear ANTES de mutar, para poder regresar limpiamente en caso de fallo.
      const worldDoc = parseWorld(markup);
      if (!worldDoc.querySelector('#canvas-root') || !worldDoc.querySelector('#composer'))
        throw new Error('La plantilla del mundo 3D no contiene sus controles');

      // Todos los pasos que dan lugar a un nuevo documento (location.assign,
      // href, iframe navegando) se evitan: el click deja activacion en ESTE documento.
      win.history.pushState({ miaInlineWorld: '3d' }, '', href);
      const landingStyles = [...doc.querySelectorAll('link[rel="stylesheet"]')]
        .filter((style) => /landing\.css(?:\?|$)/.test(style.getAttribute('href') || ''));
      landingStyles.forEach((style) => { style.disabled = true; });
      doc.title = worldDoc.title || 'mIA · Mundo 3D';
      const meta = doc.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = '#ffffff';
      doc.body.replaceChildren(...[...worldDoc.body.childNodes]
        .filter((node) => !(node.nodeType === 1 && node.tagName === 'SCRIPT'))
        .map((node) => doc.importNode(node, true)));
      doc.body.className = worldDoc.body.className;
      doc.body.dataset.miaInlineEntry = '3d';
      // Scripts embebidos en la plantilla quedan inertes al importarlos.
      // Los estilos + entrypoint se cargan por imports para Vite dev/build.
      await loadStyles();
      await loadApp();
    } catch (error) {
      onError(error);
      win.location.assign(href);
    }
  };
  link.addEventListener('click', handler);
  return () => link.removeEventListener('click', handler);
}
