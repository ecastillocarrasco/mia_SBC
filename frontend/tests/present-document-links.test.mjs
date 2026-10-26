import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPresentation } from '../src/core/present.js';

// Bug real en preprod 2026-10-26: abrir el CV de un candidato daba 401 ("Necesitas iniciar
// sesión") porque /api/documents/cv/... se renderizaba como <a href> directo, que no puede
// mandar el token Authorization. Mismo patrón que los botones de /api/reports/...: debe ser un
// botón con data-download-url, recogido por el listener de clic de cada mundo.

test('document links: a /api/documents/... value in a table cell renders an authenticated button, not a bare link', () => {
  const html = renderPresentation({
    type: 'table', title: 'Candidatos',
    columns: ['nombre', 'documento'],
    rows: [{ nombre: 'Pedro Santiago', documento: '/api/documents/cv/1080' }],
  });
  assert.match(html, /data-download-url="\/api\/documents\/cv\/1080"/);
  assert.doesNotMatch(html, /href="\/api\/documents\/cv\/1080"/);
});

test('document links: a document card for an /api/ url renders an authenticated button, not a bare link', () => {
  const html = renderPresentation({
    type: 'table', title: 'Ficha',
    columns: ['campo'],
    rows: [],
    documents: [{ url: '/api/documents/cv/1080', title: 'CV' }],
  });
  assert.match(html, /data-download-url="\/api\/documents\/cv\/1080"/);
  assert.doesNotMatch(html, /href="\/api\/documents\/cv\/1080"/);
});

test('document links: a genuine external URL still renders as a plain link, not a download button', () => {
  const html = renderPresentation({
    type: 'table', title: 'Candidatos',
    columns: ['nombre', 'linkedin'],
    rows: [{ nombre: 'Pedro Santiago', linkedin: 'https://linkedin.com/in/pedro-santiago' }],
  });
  assert.match(html, /href="https:\/\/linkedin\.com\/in\/pedro-santiago"/);
  assert.doesNotMatch(html, /data-download-url/);
});
