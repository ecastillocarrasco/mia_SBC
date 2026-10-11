# 13 — Roadmap: próximos pasos

Orden sugerido por relación impacto/riesgo, no por fase original del plan.
Cada punto nace de una limitación ya documentada en
[12_LIMITACIONES_Y_RIESGOS.md](12_LIMITACIONES_Y_RIESGOS.md); ninguno es
especulativo.

## 1. Cablear `PeriodEngine` en las tools que ya reciben `desde`/`hasta`

`tendencia_metrica` y `analizar_departamento` reciben fechas explícitas como
parámetros Pydantic. Añadir un parámetro opcional de texto libre
(`periodo: str | None`) que, si viene informado, se resuelva con
`PeriodEngine.resolve()` antes de caer a `desde`/`hasta` — así el LLM puede
pasar "verano pasado" tal cual en vez de tener que calcular las fechas él
mismo. Riesgo: bajo (aditivo, con fallback al comportamiento actual si
`periodo` no se reconoce — `resolve()` devuelve `None` y no rompe nada).

## 2. Emitir `NormalizedDataset` desde tools de listado existentes

`plantilla`, `buscar_empleado`, `nominas_persona`, etc. podrían añadir un
`NormalizedDataset` a su `ToolResult` (sin quitar su `presentation` actual)
para que un follow-up conversacional pueda re-filtrar/re-agrupar sin volver
a tocar la BD. Empezar por una sola tool de bajo riesgo (p. ej.
`distribucion_plantilla`, ya nueva) antes de tocar tools con historial de
producción. Requiere decidir dónde vive el dataset intermedio en
`session_state` sin colisionar con `foco_*`.

## 3. Fixtures de integración para las 4 tools de `analitica/universal.py`

Construir un fixture de BD con empleados + turnos + ausencias + ETT
poblados (similar al que ya debe existir para `analitica/tools.py` original)
y escribir tests específicos para `analizar_departamento`,
`tendencia_metrica`, `comparar_universal`, `distribucion_plantilla` —
incluyendo casos límite (departamento sin ausencias, comparación con datos
parciales, franja de edad con fechas de nacimiento ausentes).

## 4. Runner de regresión contra el banco de 1000 prompts

Un script (fuera de `pytest`, con credenciales de LLM reales o un entorno
de staging) que itere `tests/evals/*.yaml`, ejecute cada prompt contra el
motor conversacional, registre qué tool(s) se invocaron y si hubo error, y
agregue un % de éxito por categoría — reproduciendo el indicador de
`AUDITORIA_MIA_SBC/01_RESUMEN_EJECUTIVO.md` de forma repetible en CI o antes
de cada despliegue mayor.

## 5. Telemetría de duración de turno con 8 rondas

Antes de considerar subir `max_tool_rounds` más allá de 8, medir en
producción (u observabilidad existente, `ObservabilitySettings`) el
percentil 95 de duración de un turno que agota las 8 rondas, para decidir
con datos reales si `turn_budget_seconds=120` es suficiente.

## 6. `SemanticFieldRegistry` como fuente de `description` de parámetros

Evaluar si los `Field(description=...)` de Pydantic en las tools existentes
deberían generarse (o al menos validarse) a partir de
`field_registry.by_name(...)`, para que el vocabulario de sinónimos no viva
duplicado entre el registro y cada tool.

## Explícitamente fuera de este roadmap

- Finanzas, fichajes, evaluación de desempeño, formación: bloqueados por
  falta de fuente de datos, no por falta de tiempo de ingeniería.
- Modelo predictivo: bloqueado por evaluación legal pendiente (Reglamento
  (UE) 2024/1689), no es una tarea de este roadmap técnico.
