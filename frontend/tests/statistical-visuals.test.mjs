import test from 'node:test';
import assert from 'node:assert/strict';
import { buildStatisticalPresentation } from '../src/core/statistical-visuals.js';

// Regresión real (reportada en holograma/3D): una tabla de vacaciones con columnas de fecha
// ("Desde"/"Hasta", "19/01/2026") se graficaba como si esas fechas fueran importes -- la
// función interna asNumber() quitaba las barras y las convertía en un número gigante
// (19/01/2026 -> 19012026), que acababa sumado/promediado en los KPIs y en un donut.
function vacacionesTable() {
  return {
    type: 'table',
    title: 'Vacaciones',
    columns: ['Persona', 'Puesto', 'Departamento', 'Desde', 'Hasta', 'Días', 'Estado', 'Tipo'],
    rows: [
      ['Sandra Asencio Castillo', 'Gobernanta', 'Pisos', '19/01/2026', '23/01/2026', 5, 'Aceptada', 'Vacaciones'],
      ['Sandra Asencio Castillo', 'Gobernanta', 'Pisos', '06/04/2026', '10/04/2026', 5, 'Aceptada', 'Vacaciones'],
      ['Sandra Asencio Castillo', 'Gobernanta', 'Pisos', '22/06/2026', '23/06/2026', 2, 'Aceptada', 'Vacaciones'],
      ['Sandra Asencio Castillo', 'Gobernanta', 'Pisos', '25/06/2026', '26/06/2026', 2, 'Aceptada', 'Vacaciones'],
      ['Sandra Asencio Castillo', 'Gobernanta', 'Pisos', '14/09/2026', '18/09/2026', 5, 'Aceptada', 'Vacaciones'],
      ['Sandra Asencio Castillo', 'Gobernanta', 'Pisos', '21/09/2026', '25/09/2026', 5, 'Aceptada', 'Vacaciones'],
    ],
  };
}

test('las columnas de fecha nunca se grafican como importes (ni KPI ni chart3d sobre "Desde"/"Hasta")', () => {
  const result = buildStatisticalPresentation([vacacionesTable()], { query: 'vacaciones de Sandra en 2026' });
  assert.ok(result.html, 'debe seguir generando una visualización (con "Días", que sí es numérico)');
  assert.doesNotMatch(result.html, /19\.012\.026|19012026/, 'ninguna fecha debe aparecer convertida en número');
  assert.doesNotMatch(result.html, />Desde<|>Hasta</, 'Desde/Hasta no deben usarse como métrica de un gráfico');
  assert.ok(result.chart3d, 'debe quedar un gráfico 3D disponible');
  assert.notEqual(result.chart3d.title?.toLowerCase().includes('desde'), true);
  assert.notEqual(result.chart3d.title?.toLowerCase().includes('hasta'), true);
});

test('con las fechas descartadas, "Días" sigue siendo una métrica válida', () => {
  const result = buildStatisticalPresentation([vacacionesTable()], { query: 'vacaciones de Sandra en 2026' });
  assert.match(result.html, /D[ií]as/i);
  const total = result.chart3d?.rows?.reduce((sum, row) => sum + (row.value || 0), 0);
  assert.equal(total, 24); // 5+5+2+2+5+5
});
