import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';
await mkdir('dist', { recursive: true });
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
