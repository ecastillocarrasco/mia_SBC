# 07 — Visualización: extensión de charts.py

Módulo: `src/mia/modules/rrhh/charts.py`. Compartido por pantalla (2D),
informes (PDF/Excel/PowerPoint) y las tools analíticas universales.

## Compatibilidad hacia atrás

`chart_spec(title, columns, rows)` mantiene exactamente la firma y el
comportamiento original para tablas de 2 columnas: mismas reglas de
"¿merece un gráfico?" (2–24 filas, sin duplicados, suma > 0, etiquetas no
numéricas largas), mismo criterio line/donut/bar. Ningún llamador existente
necesita cambios.

## Qué se añadió

| Tipo | Cuándo se elige | Función constructora |
|---|---|---|
| `grouped_bar` | 1 columna categórica + N≥2 columnas numéricas, etiquetas no temporales | `chart_spec_multi()` / `grouped_bar_chart()` |
| `line` multi-serie | igual que arriba pero con etiquetas temporales (comparativa en el tiempo) | `chart_spec_multi()` / `time_series_chart()` |
| `area` | serie temporal con énfasis en acumulado | `time_series_chart(chart_type="area")` |
| `histogram` | distribución de frecuencias de una sola variable numérica | `histogram_chart()` (bins configurables, por defecto 10) |
| `scatter` | correlación entre dos variables | `scatter_chart()` |
| `horizontal_bar` | ranking largo (>12 categorías) o `hint="ranking"` | `bar_chart(horizontal=True)` |
| `stacked_bar` | composición con `hint="composition"` y >8 categorías | vía `select_chart_type()` |

`chart_spec_multi(title, columns, rows)` es la nueva entrada para tablas con
3+ columnas: separa la columna de etiqueta, intenta convertir cada columna
numérica restante en una serie, descarta las que tengan algún valor no
numérico, y decide `grouped_bar` vs `line` multi-serie según si las
etiquetas son temporales (`_is_time_like`).

## `select_chart_type()` — elegir por intención, no por memoria

```python
select_chart_type(labels, num_series=1, hint="ranking")   # → "horizontal_bar"
select_chart_type(labels, num_series=1, hint="distribution")  # → "histogram"
select_chart_type(labels, num_series=1, hint="correlation")   # → "scatter"
select_chart_type(labels, num_series=2)                        # → "grouped_bar" (si no es temporal)
```

Una tool nueva no necesita repetir la heurística serie-temporal→línea,
pocas-categorías→donut, ranking-largo→horizontal_bar: pide el tipo por lo
que quiere comunicar (`hint`) y el motor decide.

## Dónde está probado

`tests/test_charts.py`: compatibilidad de `chart_spec()` (donut/bar/line
según forma de los datos, los `None` de retorno por filas insuficientes,
duplicados, cabecera no graficable, título de ficha de departamento),
`chart_spec_multi()` (grouped_bar vs line multi-serie, columnas no
numéricas descartadas), las 10 reglas de `select_chart_type()`, los
constructores específicos (`histogram_chart` incluyendo valores constantes
y lista vacía, `scatter_chart`, `grouped_bar_chart`) y `to_number()` (formato
decimal español, negativos, texto no numérico, booleanos). Ejecutar:
`pytest tests/test_charts.py -q`.
