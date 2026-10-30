import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dist', { recursive: true });
await copyFile('../frontend/src/core/calendar-view.css', 'dist/calendar-view.css');
for (const name of ['avatar', 'bubble', 'settings', 'results']) {
  await build({
    entryPoints: [`src/ui/${name}.js`],
    outfile: `dist/${name}.js`,
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: ['chrome120'],
    minify: false,
    logLevel: 'warning'
  });
}
console.log('Renderer compilado en dist/');
