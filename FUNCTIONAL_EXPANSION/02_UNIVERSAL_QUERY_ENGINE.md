# 02 — Universal Query Engine

Paquete: `src/mia/query/` (`dataset.py`, `engine.py`). Diagrama y detalle
completo en [`docs/UNIVERSAL_QUERY_ARCHITECTURE.md`](../docs/UNIVERSAL_QUERY_ARCHITECTURE.md#mia-query--capa-de-consulta-universal).
Este documento resume qué resuelve y cómo probarlo.

## Qué resuelve

Antes de esta capa, cada tool que necesitaba filtrar/agrupar/ordenar un
listado escribía su propia consulta SQLAlchemy para cada combinación de
criterios. Preguntas no previstas literalmente (p. ej. "empleados de IT con
más de 5 años y contrato indefinido, ordenados por salario") no tenían
camino sin programar una tool nueva.

`NormalizedDataset` + `UniversalQueryEngine` separan **"traer los datos"**
(sigue siendo SQLAlchemy, dentro de la tool, con sus permisos) de
**"operar sobre las filas ya traídas"** (filtrar, ordenar, agrupar, cruzar),
que pasa a ser un motor en memoria reutilizable y ya probado.

## Contrato

```python
ds = NormalizedDataset.from_dicts("Empleados de IT", rows, labels={"gross_salary": "Salario bruto"})

engine = UniversalQueryEngine()
ds = engine.filter(ds, [FilterClause("department_key", "eq", "it"),
                        FilterClause("years_tenure", "gte", 5),
                        FilterClause("contract_type", "eq", "indefinido")])
ds = engine.sort(ds, by="gross_salary", ascending=False)

presentation = ds.to_presentation()  # {"type": "table", "columns": [...], "rows": [...]}
```

Cada operación devuelve un `NormalizedDataset` nuevo (inmutabilidad
funcional); el original no se modifica, así que encadenar operaciones en un
follow-up conversacional no tiene efectos colaterales.

## Operaciones disponibles

`filter`, `select`/`project`, `sort`, `limit`, `group_by`, `pivot`, `join`,
`union`, `rank`, `add_percentage`, `percentage_change`. Tabla completa en el
documento de arquitectura.

## Estado de integración

**Construido y probado de forma aislada; ninguna tool lo invoca todavía.**
No se ha forzado su adopción en esta expansión porque reescribir las tools
de listado existentes (`plantilla`, `buscar_empleado`…) para emitir
`NormalizedDataset` es un cambio con superficie de regresión propia, fuera
del alcance de "no romper lo que ya funciona". Ver
[13_ROADMAP_NEXT.md](13_ROADMAP_NEXT.md) para el plan de cableado.

`tests/test_results_algebra.py` es anterior a esta expansión y cubre un
sistema distinto (la tool `operar_resultado` sobre la última tabla mostrada,
`conversation/tools.py:LAST_TABLE`); no debe confundirse con esta capa.

## Dónde está probado

`tests/test_query_engine.py` — filtros (todos los comparadores), sort,
limit/truncado, `group_by` con agregados, `pivot`, `join` (inner/left),
`union`, `rank`, `add_percentage`, `percentage_change`, además de
`SemanticFieldRegistry` y `PeriodEngine` (ver 03 y 04). Ejecutar:
`pytest tests/test_query_engine.py -q`.
