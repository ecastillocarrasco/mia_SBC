import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPresentation } from '../src/core/present.js';

test('downloads: one format renders the single-button "download" presentation unchanged', () => {
  const html = renderPresentation({
    type: 'download', title: 'Costes por departamento', format: 'pdf',
    url: '/api/reports/abc123', file_name: 'Costes por departamento.pdf',
  });
  assert.match(html, /mia-download/);
  assert.match(html, /\/api\/reports\/abc123/);
  assert.match(html, /Descargar Costes por departamento\.pdf/);
});

test('downloads: several formats requested in one call render one button per format', () => {
  const html = renderPresentation({
    type: 'downloads', title: 'Costes por departamento',
    items: [
      { url: '/api/reports/abc123', format: 'pdf', file_name: 'Costes por departamento.pdf' },
      { url: '/api/reports/def456', format: 'xlsx', file_name: 'Costes por departamento.xlsx' },
    ],
  });
  assert.match(html, /mia-download-group/);
  assert.match(html, /\/api\/reports\/abc123/);
  assert.match(html, /\/api\/reports\/def456/);
  assert.match(html, /Descargar Costes por departamento\.pdf/);
  assert.match(html, /Descargar Costes por departamento\.xlsx/);
});

test('downloads: an item with an unsafe URL is dropped, not rendered as a dead/dangerous link', () => {
  const html = renderPresentation({
    type: 'downloads', title: 'Informe',
    items: [
      { url: '/api/reports/abc123', format: 'pdf', file_name: 'Informe.pdf' },
      { url: 'javascript:alert(1)', format: 'xlsx', file_name: 'Informe.xlsx' },
    ],
  });
  assert.match(html, /\/api\/reports\/abc123/);
  assert.doesNotMatch(html, /javascript:/);
});

test('downloads: every item failing the URL safety check renders nothing', () => {
  const html = renderPresentation({
    type: 'downloads', title: 'Informe',
    items: [{ url: 'javascript:alert(1)', format: 'pdf', file_name: 'Informe.pdf' }],
  });
  assert.equal(html, '');
});
