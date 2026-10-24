// Fase H: la distribución de producción (`npm run build`) debe incluir los scripts/estilos
// clásicos (sin type="module") del mundo 2D real — mia-2d.js/mia-enhance.js/mia-2d.css/
// mia-enhance.css. Vite nunca los procesa ni los copia por sí solo (viven fuera del grafo de
// módulos, referenciados por rutas absolutas en mia-2d.html); el plugin `copy-classic-world-2d-
// assets` de vite.config.js los copia a dist/ en cada build. Esta prueba ejecuta el build REAL y
// comprueba el resultado REAL — no asume que un `dist/` ya construido manualmente sigue vigente —
// para detectar si alguno de estos recursos esenciales vuelve a faltar en la compilación.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');

const REQUIRED_DIST_ASSETS = [
  'dist/src/worlds/2d/mia-2d.js',
  'dist/src/worlds/2d/mia-enhance.js',
  'dist/src/worlds/2d/mia-2d.css',
  'dist/src/worlds/2d/mia-enhance.css',
];

test('npm run build ships the classic 2D world scripts/styles in dist/, with real content', () => {
  // `npx` resuelve a `npx.cmd` en Windows, que `execFileSync` no ejecuta de forma fiable sin una
  // shell; se invoca el propio binario de Vite con el mismo intérprete de Node del test, que
  // funciona igual en cualquier plataforma.
  const viteBin = resolve(root, 'node_modules/vite/bin/vite.js');
  execFileSync(process.execPath, [viteBin, 'build'], { cwd: root, stdio: 'pipe' });

  for (const rel of REQUIRED_DIST_ASSETS) {
    const full = resolve(root, rel);
    assert.ok(existsSync(full), `falta en dist/ tras el build: ${rel}`);

    const content = readFileSync(full, 'utf8');
    // Vite sirve el HTML de la portada como fallback cuando una ruta no existe en el servidor de
    // vista previa — si el recurso compilado fuera ese fallback (en vez del fichero real), este es
    // exactamente el síntoma que delató el hueco original de empaquetado.
    assert.ok(
      !content.trim().toLowerCase().startsWith('<!doctype html'),
      `${rel} contiene HTML (probable fallback de SPA), no el recurso real`,
    );
    assert.ok(content.length > 200, `${rel} parece vacío o truncado (${content.length} bytes)`);
  }

  const js = readFileSync(resolve(root, 'dist/src/worlds/2d/mia-2d.js'), 'utf8');
  assert.ok(js.includes('MIA_UI_BUILD'), 'mia-2d.js compilado no contiene su marcador de build esperado');
  assert.ok(js.includes('MIA_JOBS_API'), 'mia-2d.js compilado no incluye el Job Manager de la Fase H');

  const css = readFileSync(resolve(root, 'dist/src/worlds/2d/mia-2d.css'), 'utf8');
  assert.ok(css.includes('mia-job-card'), 'mia-2d.css compilado no incluye los estilos del Job Manager de la Fase H');
});
