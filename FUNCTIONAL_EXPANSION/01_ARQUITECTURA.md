# 01 — Arquitectura de la expansión funcional

## Objetivo

Que mIA pueda resolver cualquier pregunta razonable derivable de los datos
disponibles, aunque esa pregunta concreta no haya sido programada
literalmente — sin inventar datos, sin romper contratos protegidos, sin
depender de Legacy.

## Qué se añadió y por qué se divide así

Dos capas nuevas, independientes entre sí y de `conversation/` y
`modules/rrhh/`:

| Capa | Paquete | Responsabilidad |
|---|---|---|
| Consulta universal | `mia/query/` | Representar cualquier conjunto de filas de forma uniforme y operar sobre él (filtrar/ordenar/agrupar/cruzar) sin SQL dinámico |
| Analítica | `mia/analytics/` | Estadística descriptiva, detección de insights y comparación sobre datos ya resueltos |

Detalle completo con diagramas: [`docs/UNIVERSAL_QUERY_ARCHITECTURE.md`](../docs/UNIVERSAL_QUERY_ARCHITECTURE.md).

Encima de esas dos capas, 18 tools nuevas repartidas por todos los dominios
activos (empleados, turnos, vacaciones, nóminas, documentos, trabajo
temporal, informes y 4 analíticas universales en
`modules/rrhh/analitica/universal.py` — inventario completo en
[06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md)) que generalizan preguntas que
antes requerían varias tools especializadas o no tenían ninguna, más una
extensión de `charts.py` para que cualquier tool pida un tipo de gráfico
por intención (serie temporal, ranking, distribución, correlación) en vez
de recordar la regla cada vez.

## Por qué no "LLM genera SQL" ni "una tool por pregunta"

- **LLM generando SQL**: descartado — la superficie de inyección y el control
  de acceso por permiso (`Permission` enum, un permiso por tool) dejarían de
  ser auditables. `CLAUDE.md` exige rutas de ejecución observables y
  deterministas.
- **Una tool por pregunta**: no escala; ya hay 77 tools y seguir ese patrón
  para cada variación de lenguaje natural duplicaría lógica de negocio sin
  límite.

En su lugar, la capa de consulta universal es un **DSL tipado** (dataclasses
inmutables: `FilterClause`, `AggSpec`) que el código de una tool puede usar
internamente. El contrato con el LLM no cambia: sigue siendo "tool tipada
con permiso declarado", nunca una entrada de texto libre que se ejecuta.

## Qué NO cambia

- El flujo de un turno de conversación (`conversation/engine.py`): LLM elige
  tools, el código las ejecuta, el LLM narra el resultado. Ver
  `docs/arquitectura.md`.
- Los contratos protegidos (Employee360, vacaciones, nóminas…). Ver
  [`11_CONTRATOS_PROTEGIDOS.md`](11_CONTRATOS_PROTEGIDOS.md).
- Legacy sigue siendo solo referencia de lectura; nada nuevo importa de él.

## Índice de este directorio

1. **01_ARQUITECTURA.md** (este documento)
2. [02_UNIVERSAL_QUERY_ENGINE.md](02_UNIVERSAL_QUERY_ENGINE.md) — `mia/query/`
3. [03_SEMANTIC_FIELD_REGISTRY.md](03_SEMANTIC_FIELD_REGISTRY.md) — sinónimos → campo interno
4. [04_PERIOD_ENGINE.md](04_PERIOD_ENGINE.md) — lenguaje natural → rango de fechas
5. [05_ANALYTICS_ENGINES.md](05_ANALYTICS_ENGINES.md) — estadística, insights, comparación
6. [06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md) — las 4 tools analíticas universales
7. [07_VISUALIZACION.md](07_VISUALIZACION.md) — extensión de `charts.py`
8. [08_CONVERSACION.md](08_CONVERSACION.md) — `max_tool_rounds`, `history_turns`
9. [09_EVALUACION.md](09_EVALUACION.md) — banco de 1000+ prompts en `tests/evals/`
10. [10_COBERTURA_FUNCIONAL.md](10_COBERTURA_FUNCIONAL.md) — antes/después frente a la auditoría
11. [11_CONTRATOS_PROTEGIDOS.md](11_CONTRATOS_PROTEGIDOS.md) — qué se preservó intacto
12. [12_LIMITACIONES_Y_RIESGOS.md](12_LIMITACIONES_Y_RIESGOS.md) — qué no se implementó y por qué
13. [13_ROADMAP_NEXT.md](13_ROADMAP_NEXT.md) — próximos pasos
