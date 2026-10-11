# 05 — Analytics engines: estadística, insights, comparación

Paquete: `src/mia/analytics/` (`stats.py`, `insights.py`, `comparison.py`).
A diferencia de `mia/query/`, **esta capa sí está en producción
conversacional** — la consumen las 4 tools de
[06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md).

## Principio de diseño

El código calcula, el LLM narra. Ninguno de estos módulos llama al LLM ni
depende de `conversation/`; reciben números ya extraídos por una tool
(listas de floats, `TimePoint`, un dict grupo→valor) y devuelven estructuras
tipadas y serializables. El LLM lee esas estructuras y redacta la respuesta,
pero nunca inventa ni recalcula un número.

## `stats.py` — estadística determinista

| Función | Devuelve |
|---|---|
| `descriptive(values)` | count, sum, mean, median, min, max, range, stddev, variance, cv%, percentiles p10/p25/p75/p90 (con ≥4 muestras), moda (si hay duplicados) |
| `frequency_distribution(values)` | total, valores únicos, top-N con conteo y % |
| `time_series_stats(points)` | min/max/first/last, variación total, variación periodo a periodo (MoM), mayor subida/bajada, tendencia lineal simple (con ≥3 puntos), media móvil de ventana 3, acumulado |
| `detect_outliers(values, method)` | IQR (por defecto) o z-score (umbral 2.5); devuelve vallas/umbral y la lista de atípicos con etiqueta |
| `detect_abrupt_changes(points, threshold_pct)` | cambios entre periodos consecutivos por encima de un umbral porcentual |

Todas protegen contra muestra insuficiente devolviendo una nota en vez de
lanzar una excepción o fabricar un resultado (p. ej. percentiles solo con
≥4 valores, outliers solo con ≥4).

## `insights.py` — detección automática de hechos relevantes

`InsightEngine` no inventa: cada `Insight` lleva `type`, `importance`
(0–1), `text` (frase lista para mostrar) y `data` (los números que la
sustentan, para trazabilidad). Tres generadores:

- `from_time_series(points, label, unit)` — tendencia, variación total,
  máximo/mínimo, mayor incremento/caída puntual, cambios bruscos (vía
  `detect_abrupt_changes` con umbral 25%).
- `from_distribution(groups, label, metric, unit)` — líder y rezagado,
  concentración (si el top-1 supera el 40% del total), outliers (IQR, con
  ≥4 grupos).
- `from_comparison(a_label, a_value, b_label, b_value, ...)` — quién gana y
  por cuánto, en una frase.

`top_insights(insights, n)` ordena por importancia y recorta — así una tool
puede pedir "los 3 hechos más relevantes" sin tener que implementar el
ranking.

## `comparison.py` — A vs B y multi-grupo

- `MetricComparison` — una métrica, dos entidades; `winner` respeta
  `higher_is_better` (`True`/`False`/`None` para neutral, p. ej.
  antigüedad no tiene "mejor").
- `ComparisonResult` — N métricas entre dos entidades; `to_table()` da el
  formato de tabla del frontend directamente; `key_insights()` redacta
  frases para las diferencias ≥5%.
- `MultiGroupComparison` — N grupos sobre las mismas métricas;
  `ranking(metric)` ordena respetando si menor-es-mejor; `to_table()`
  añade columnas "Mejor"/"Peor" por fila.

## Módulo predictivo (sin implementación, deliberadamente)

`PredictiveModel`/`PredictionRequest` siguen al final de
`analytics/__init__.py` como contrato puro (`ABC`, sin lógica). Un modelo
predictivo sobre personas empleadas es de alto riesgo bajo el Reglamento
(UE) 2024/1689 (sistemas de IA en el ámbito laboral) y exige evaluación
legal previa — fuera del alcance de esta expansión. Vive en `analytics/`, no
en `conversation/` ni en `modules/rrhh/`, para poder auditarlo o
desactivarlo sin tocar el LLM ni los dominios transaccionales. Regla
explícita en el propio módulo: la nacionalidad y cualquier proxy de origen
étnico no se usan como variable predictiva bajo ningún concepto.

## Dónde está probado

`tests/test_analytics.py`: estadística descriptiva (incluye casos límite:
lista vacía, sin duplicados, muestra pequeña sin percentiles), distribución
de frecuencias, series temporales (tendencia, variación, `None` filtrado),
outliers IQR, cambios bruscos, los tres generadores de `InsightEngine`,
`top_insights`, `MetricComparison` (ganador con `higher_is_better` en sus
tres valores), `ComparisonResult.to_table`/`key_insights`,
`MultiGroupComparison.ranking`/`to_table`. Ejecutar:
`pytest tests/test_analytics.py -q`.
