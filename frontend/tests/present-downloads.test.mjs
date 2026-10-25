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

test('downloads: a preview table renders before the download button, never the full report', () => {
  const html = renderPresentation({
    type: 'download', title: 'Comparativo Pisos', format: 'pdf',
    url: '/api/reports/abc123', file_name: 'Comparativo Pisos.pdf',
    preview: {
      tables: [{
        title: 'Detalle por empleado', columns: ['Nombre', 'Horas'], rows: [['Ana', 40], ['Luis', 38]],
        total_rows: 2, truncated: false,
      }],
      charts: [],
    },
  });
  assert.match(html, /Detalle por empleado/);
  assert.match(html, /Ana/);
  assert.match(html, /mia-table/);
  assert.doesNotMatch(html, /Mostrando/); // not truncated -> no truncation note
  // the preview comes before the download button in the markup
  assert.ok(html.indexOf('mia-table') < html.indexOf('mia-download'));
});

test('downloads: a truncated preview table says so and keeps only the capped rows', () => {
  const html = renderPresentation({
    type: 'download', title: 'Informe', format: 'pdf', url: '/api/reports/abc123', file_name: 'Informe.pdf',
    preview: {
      tables: [{
        title: 'Detalle', columns: ['Nombre'], rows: [['Ana'], ['Luis']],
        total_rows: 90, truncated: true,
      }],
      charts: [],
    },
  });
  assert.match(html, /Mostrando 2 de 90 filas/);
});

test('downloads: a bar chart in the preview renders labels and values', () => {
  const html = renderPresentation({
    type: 'download', title: 'Informe', format: 'pdf', url: '/api/reports/abc123', file_name: 'Informe.pdf',
    preview: {
      tables: [],
      charts: [{ type: 'bar', title: 'Horas por departamento', labels: ['Pisos', 'Cocina'], series: [{ name: 'Horas', values: [120, 80] }] }],
    },
  });
  assert.match(html, /mia-charts-panel/);
  assert.match(html, /Horas por departamento/);
  assert.match(html, /Pisos/);
  assert.match(html, /Cocina/);
});

test('downloads: a donut chart in the preview renders a legend with percentages', () => {
  const html = renderPresentation({
    type: 'download', title: 'Informe', format: 'pdf', url: '/api/reports/abc123', file_name: 'Informe.pdf',
    preview: {
      tables: [],
      charts: [{ type: 'donut', title: 'Reparto', labels: ['A', 'B'], series: [{ name: 's', values: [25, 75] }] }],
    },
  });
  assert.match(html, /mia-chart-donut/);
  assert.match(html, /25%/);
  assert.match(html, /75%/);
});

test('downloads: an empty preview (no tables, no charts) adds nothing extra', () => {
  const html = renderPresentation({
    type: 'download', title: 'Informe', format: 'pdf', url: '/api/reports/abc123', file_name: 'Informe.pdf',
    preview: { tables: [], charts: [] },
  });
  assert.doesNotMatch(html, /mia-report-preview/);
  assert.match(html, /mia-download/);
});

test('downloads: no preview key at all behaves exactly like before (no crash, no empty section)', () => {
  const html = renderPresentation({
    type: 'downloads', title: 'Informe',
    items: [{ url: '/api/reports/abc123', format: 'pdf', file_name: 'Informe.pdf' }],
  });
  assert.doesNotMatch(html, /mia-report-preview/);
  assert.match(html, /mia-download-group/);
});
