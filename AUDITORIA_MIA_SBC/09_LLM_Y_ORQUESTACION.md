# 09 - LLM y Orquestación

## Proveedor LLM

| Parámetro | Valor por defecto |
|---|---|
| Provider | OpenAI (configurable: azure_openai, fake) |
| Modelo | `gpt-4.1-mini` |
| Base URL | `https://api.openai.com/v1` |
| Timeout | 45 segundos por llamada |
| Max output tokens | 1200 tokens |
| Max tool rounds | 4 rondas de herramientas por turno |
| Turn budget | 75 segundos totales por turno |
| Web search | Activado por defecto (si el proveedor lo soporta) |

---

## System Prompt y Persona

La clase `Persona` en `conversation/persona.py` gestiona:
- Nombre: mIA
- Contexto: asistente de RRHH de Sunset Beach Club
- Tono: profesional pero cercano
- Idioma: español
- Avatar states: 16 estados definidos (reposo, escuchando, pensando, hablando, sonriendo, etc.)
- Reglas de lo que se dice en voz alta (no importes, no promesas)

El system prompt incluye:
- Identidad y contexto de la empresa
- Reglas de las tools activas en el turno (rules_for_prompt)
- Guía de estados del avatar
- Instrucciones de formato de respuesta (texto natural, no Markdown excesivo)
- Reglas por dominio (NOM-002, SEL-001, NOM-003, NOM-004, VAC-003, etc.)

---

## Tool Calling

| Aspecto | Implementación |
|---|---|
| Formato | Tool use nativo del proveedor (OpenAI function calling) |
| Validación de parámetros | Pydantic — antes de ejecutar el handler |
| Verificación de permisos | Antes de ejecutar — usuario sin permiso no llama a la tool |
| Max rondas | 4 (configurable `max_tool_rounds`) |
| Ejecución | Determinista — no es el LLM quien ejecuta, es código Python |
| Paralela | No declarado explícitamente (una tool a la vez por round) |
| Auditoría | AuditEvent por cada tool ejecutada |
| Estado de sesión | Las tools pueden actualizar `session_state` (foco, última tabla, última población) |

---

## Structured Output

No se usa `structured_output` de la API directamente. En su lugar:
- El LLM recibe el resultado de las tools como JSON en el mensaje de tool result
- El LLM genera texto libre como respuesta conversacional
- El objeto `presentation` es generado por el código de la tool, no por el LLM

---

## Enrutado / Orquestación

### Routing determinista (NO basado en LLM)

El `orchestrator.select_modules()` usa comparación de keywords normalizada:
```python
normalized = normalize_key(message)
if any(normalize_key(k) in normalized for k in keywords):
    selected.add(module)
```

- El módulo `rrhh` se incluye siempre (es el único con tools activas)
- El módulo `finanzas` se añade si el mensaje contiene "factura", "contabilidad", "presupuesto", etc.
- No hay llamada extra al LLM para decidir el enrutado
- Tiempo adicional de enrutado: O(1) — comparación de strings

---

## Historial Conversacional

| Parámetro | Valor |
|---|---|
| Historial máximo | 12 turnos (configurable `history_turns`) |
| Persistencia | PostgreSQL (ConversationTurn) |
| Estado de sesión | JSON en ConversationSession.state |
| Qué se guarda | Mensajes usuario/asistente, tool_calls, presentation, speech, avatar_state, latency |
| Foco conversacional | Persona, departamento, periodo, última tabla, última población — persistidos en session.state |

---

## Riesgos del LLM

### ¿Puede el LLM inventar datos?

- **No en dominios con tools**: el motor solo permite al LLM llamar a tools (que devuelven datos reales de BD). El LLM no puede inventar empleados, turnos o nóminas.
- **Sí en consultas generales**: el LLM responde directamente preguntas sin tool (tiempo, traducciones, conocimiento general). Aquí puede alucinar.
- **Riesgo mitigado**: la persona prohíbe citar importes numéricos sin tool, y el guard elimina promesas del texto.

### ¿Puede el LLM perder filas?

- El `summary` que recibe el LLM está limitado a `MAX_ROWS_FOR_MODEL` filas. Exceder ese límite hace que el resumen diga "hay N personas" sin listarlas todas.
- La `presentation` siempre tiene los datos completos para el frontend, independientemente del límite del LLM.
- En estadísticas salariales, la muestra se limita a `MAX_PEOPLE=150` personas (para evitar timeouts de lectura de PDFs).

### ¿Puede llamar a tools sin permiso?

- No. El ToolRegistry filtra las tools disponibles para cada usuario antes de enviárselas al LLM. Una tool sin permiso es invisible para el modelo.

### ¿Pueden encadenarse demasiadas tools?

- Max 4 rondas de tools + budget de 75 segundos. Pasado el presupuesto, el motor responde con lo que haya obtenido.
- Riesgo: respuesta incompleta en consultas muy complejas que requieran muchas tools.

---

## Retries y Robustez LLM

- Timeout por llamada: 45 segundos
- No hay retry explícito en el código visto (el proveedor puede gestionar internamente)
- Si el LLM falla, el SSE stream termina con error y el frontend lo muestra al usuario
- Si SharePoint falla en una tool, la tool devuelve `SOURCE_UNAVAILABLE` y el LLM responde indicando que la fuente no está disponible
