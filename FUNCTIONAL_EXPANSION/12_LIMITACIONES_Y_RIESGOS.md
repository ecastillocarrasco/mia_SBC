# 12 — Limitaciones y riesgos conocidos

Honestidad sobre qué queda sin resolver, para que nadie asuma una cobertura
que no existe. `CLAUDE.md`: "nunca reportar un módulo como completo si hay
riesgos relevantes sin señalar".

## No implementado por falta de fuente de datos (correcto no inventar)

Igual que señalaba `AUDITORIA_MIA_SBC/13_GAPS_FUNCIONALES.md` y sigue
vigente tras esta expansión:

- **Finanzas**: sin fuente sincronizada. Ninguna tool nueva la simula.
- **Fichajes**: sin fuente sincronizada. `tendencia_metrica` cubre
  ausencias/bajas/vacaciones/permisos/plantilla/ETT — no horas de fichaje
  real porque ese dato no existe en el sistema.
- **Evaluación de desempeño, formación**: sin fuente. No hay tool ni mención
  de estos datos en ninguna tool nueva.
- **`gender` y `hire_date` como campos de empleado**: `SemanticFieldRegistry`
  los registra con `description` explícita de que no están disponibles en
  todos los empleados — se documenta la limitación en el propio catálogo en
  vez de ocultarla u omitirla silenciosamente.

## Infraestructura construida pero no cableada en producción

- `mia/query/` completo (`NormalizedDataset`, `UniversalQueryEngine`,
  `SemanticFieldRegistry`, `PeriodEngine`): probado de forma aislada
  (34 tests en `test_query_engine.py`), pero **ninguna tool lo invoca en su
  handler todavía**. Ver [02](02_UNIVERSAL_QUERY_ENGINE.md),
  [03](03_SEMANTIC_FIELD_REGISTRY.md), [04](04_PERIOD_ENGINE.md) y el
  roadmap de cableado en [13](13_ROADMAP_NEXT.md).
- Las 4 tools nuevas de `analitica/universal.py` consultan la BD
  directamente con SQLAlchemy (no a través de `UniversalQueryEngine`); solo
  consumen la capa analítica (`mia/analytics/`), que sí está en producción.

## Predictivo: explícitamente fuera de alcance

`PredictiveModel` sigue siendo contrato sin implementación. Un modelo
predictivo sobre personas empleadas es de alto riesgo bajo el Reglamento
(UE) 2024/1689 y requiere evaluación legal previa (documentación técnica,
supervisión humana, registro de decisiones) — no se entrena ni se sirve
nada aquí. Cualquier tool que prometa "predicción de rotación" o similar
debe declinar explícitamente (ver `14_casos_limite.yaml`, categoría
`fuera_de_alcance, predictivo_no_implementado`).

## Riesgos de la expansión de `max_tool_rounds`/`turn_budget_seconds`

Ver [08_CONVERSACION.md](08_CONVERSACION.md). El riesgo principal no
mitigado del todo: 8 rondas de herramientas con proveedores LLM lentos
podría acercarse al límite de 120s en el peor caso real (no solo en tests
con `FakeLLMProvider`, que no tiene la latencia de un proveedor real). No
hay telemetría de producción todavía que confirme el percentil 95 de
duración de un turno con 8 rondas.

## Gaps de prueba reconocidos

- Las 4 tools nuevas de `analitica/universal.py` no tienen fixtures de
  integración propias en esta expansión (requieren BD con empleados, turnos,
  ausencias, ETT poblados) — están cubiertas solo indirectamente por el
  arranque de la suite completa. Ver [06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md).
- El banco de 1000 prompts de `tests/evals/` no se ha ejecutado contra el
  motor conversacional real (requiere credenciales de LLM); solo se validó
  su forma y volumen.

## Riesgo de mantenimiento del banco de evaluación

1000 prompts en YAML son fáciles de dejar desactualizados si el vocabulario
de negocio cambia (p. ej. renombrar un departamento). El test
`test_total_prompt_count_meets_minimum` solo protege la cantidad, no la
vigencia del contenido — una revisión periódica manual sigue siendo
necesaria.
