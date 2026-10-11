# 08 — Conversación: más rondas de herramientas, más historial

## Cambio

`src/mia/settings.py` (`LLMSettings`):

| Parámetro | Antes | Ahora | Motivo |
|---|---|---|---|
| `max_tool_rounds` | 4 | 8 | Una consulta multidominio (p. ej. «ficha de Ana + sus vacaciones + su última nómina») o un follow-up encadenado puede necesitar más de 4 llamadas a herramientas antes de poder responder |
| `turn_budget_seconds` | 75.0 | 120.0 | Duplicar las rondas sin ampliar el presupuesto de tiempo habría recortado la octava ronda antes de completarla |
| `history_turns` (en `Settings`, no en `LLMSettings`) | 12 | 20 | Más turnos de contexto disponibles para resolver follow-ups que referencian algo dicho varios mensajes atrás |

`src/mia/conversation/engine.py` recibe estos valores inyectados desde
`api/services.py` (`max_tool_rounds=settings.llm.max_tool_rounds`); su
propio default (`max_tool_rounds: int = 4`) solo se usa si se instancia el
motor sin pasar el parámetro (p. ej. en un test aislado), así que no hacía
falta tocarlo para que el cambio de `settings.py` tenga efecto en la app
real.

## Por qué no más todavía

8 rondas y 120s son un punto intermedio: suficiente para las consultas
multidominio de esta expansión sin multiplicar por dos el peor caso de
latencia de un turno que falla (p. ej. un proveedor LLM lento + varias
herramientas). Subir más estos límites sin datos de uso real sería
optimizar a ciegas — contradice el principio de rendimiento como requisito
de primera clase de `CLAUDE.md`.

## Riesgo de regresión y cómo se mitigó

Ambos valores son límites superiores, no comportamiento: una conversación
que hoy resuelve todo en 2 rondas sigue haciéndolo en 2 rondas. El único
riesgo era una regresión de *configuración* (valor mal escrito, tipo
incorrecto). Se verificó ejecutando la suite completa tras el cambio:
362 tests preexistentes pasan sin modificación.

## Pendiente de esta fase, no abordado aquí

El objetivo original también mencionaba "estado de sesión tipado" y
"resolución de follow-ups con datasets intermedios". `session_state` (dict
libre en `ConversationSession.state`, vía `ToolContext`) no se tipó en esta
expansión: ya soporta `foco_persona`/`foco_departamento`/`foco_periodo` de
forma consistente entre tools (incluidas las 4 nuevas, ver
[06_NUEVAS_TOOLS.md](06_NUEVAS_TOOLS.md)), y tipar un dict que ya funciona
sin tests que cubran la migración es más riesgo de regresión que beneficio
inmediato. Queda en [13_ROADMAP_NEXT.md](13_ROADMAP_NEXT.md).
