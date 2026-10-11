# 11 - Testing y Robustez

## Inventario de Tests

| Fichero | Tipo | Cobertura |
|---|---|---|
| `test_admin.py` | unitario | endpoints admin |
| `test_auth.py` | integración | autenticación, roles, UserContext |
| `test_chat.py` | integración | motor de conversación, SSE stream |
| `test_compat.py` | compat | compatibilidad de rutas |
| `test_consulta_cruzada.py` | dominio | consulta_cruzada con múltiples criterios |
| `test_conversation_followups.py` | dominio | seguimiento conversacional (foco, referencias anteriores) |
| `test_domains.py` | dominio | herramientas de empleados, turnos, vacaciones, documentos, correo |
| `test_guard.py` | unitario | guard (promesas imposibles, importes en voz) |
| `test_health.py` | unitario | endpoint /health |
| `test_i18n.py` | unitario | internacionalización |
| `test_legacy_view.py` | compat | vistas del sistema anterior |
| `test_llm_provider.py` | integración | proveedor LLM (fake) |
| `test_mappers.py` | unitario | mappers de SharePoint → BD |
| `test_migrations.py` | integración | esquema de BD y migraciones |
| `test_orchestrator.py` | unitario | orquestador multi-módulo |
| `test_phase4_domains.py` | dominio | herramientas de dominio ampliadas (ETT, nóminas, analitica) |
| `test_phase4_sources.py` | integración | fuentes de datos |
| `test_phase4b.py` | dominio | herramientas adicionales |
| `test_phase4c_calendars.py` | dominio | calendarios (historico, tipos, plantillas, auditoría) |
| `test_reports_render.py` | unitario | renderizado de informes PDF/Excel/PPTX |
| `test_reports_route.py` | integración | rutas de informes |
| `test_results_algebra.py` | unitario | operar_resultado, cruzar_resultados |
| `test_rules.py` | unitario | rules_for_prompt |
| `test_salary_stats.py` | unitario | estadisticas_salariales, ranking_salarial, _stats() |
| `test_schema_limits.py` | unitario | límites del esquema de BD |
| `test_sharepoint_auth.py` | integración | autenticación SharePoint |
| `test_sharepoint_client.py` | integración | cliente SharePoint |
| `test_shift_rules.py` | unitario | reglas de turnos |
| `test_speech.py` | unitario | speech extractor, guard en voz |
| `test_sync.py` | integración | sincronización de SharePoint → BD |
| `test_tools.py` | integración | tools de múltiples dominios |
| `test_vacaciones.py` | dominio | vacaciones, saldos, conflictos, reincorporaciones |
| `test_voice.py` | unitario | voz (ElevenLabs provider) |
| `parity/` | parity | tests de paridad con sistema anterior |
| `fakes/` | fixtures | stubs y fakes para tests |

---

## Relación Funcionalidad → Test

| Funcionalidad | Test(s) |
|---|---|
| Panel RRHH | test_phase4_domains.py |
| Consulta cruzada | test_consulta_cruzada.py |
| Vacaciones / conflictos | test_vacaciones.py |
| Estadísticas salariales | test_salary_stats.py |
| Operaciones sobre resultados | test_results_algebra.py |
| Guard (promesas/importes) | test_guard.py |
| Motor de conversación | test_chat.py |
| Autenticación | test_auth.py |
| Sincronización SP | test_sync.py |
| Calendarios / histórico turnos | test_phase4c_calendars.py |
| Informes PDF/Excel/PPTX | test_reports_render.py |
| Orquestador | test_orchestrator.py |
| Speech / voz | test_speech.py, test_voice.py |
| Mappers SP | test_mappers.py |
| Seguimientos conversacionales | test_conversation_followups.py |

---

## Funciones Críticas sin Test Evidente

| Funcionalidad | Riesgo |
|---|---|
| `parse_concepts()` (nóminas) | Medio — parser regex nuevo, sin tests unitarios dedicados |
| `parse_employer_ss()` (nóminas) | Medio — idem |
| `conflictos_vacaciones` | Bajo — hay test_vacaciones.py que cubre vacaciones pero puede no cubrir esta función nueva |
| `proximos_jubilacion` | Bajo — función nueva, sin test visto |
| `boletines_faltantes_tt` | Bajo — función nueva |
| `variacion_coste_tt` | Bajo — función nueva |
| `anomalias_nominas` | Bajo — función nueva |
| Frontend Presentation Director | No hay tests automatizados de frontend |
| Avatar states | Solo en test_speech.py parcialmente |

---

## Manejo de Errores

### SharePoint caído
- Las tools devuelven `ToolStatus.SOURCE_UNAVAILABLE` con mensaje descriptivo
- El LLM recibe el error y responde al usuario que la fuente no está disponible
- No hay fallback silencioso ni datos inventados

### LLM timeout
- `timeout_seconds=45` por llamada, `turn_budget_seconds=75` por turno
- Si se agota el presupuesto, el motor responde con lo que haya obtenido hasta ese momento
- Si el LLM no responde, el SSE stream termina con error

### Sin resultados (NOT_FOUND)
- Las tools devuelven `ToolStatus.NOT_FOUND` con mensaje explicativo
- El LLM responde "no hay datos" de forma natural

### Error de validación de parámetros
- Pydantic valida antes de ejecutar el handler
- `ToolStatus.INVALID_ARGUMENTS` con detalle del error
- El LLM puede reintentar con parámetros corregidos (hasta max_tool_rounds)

### PDF ilegible
- Las tools de importes capturan excepciones de parsing y devuelven error parcial
- No invalida el conjunto: otros PDFs del grupo siguen procesándose
- El resumen informa cuántos fueron ilegibles

### Datos obsoletos (freshness)
- Cada tool llama a `deps.freshness()` y añade al resultado información de cuándo se sincronizaron los datos
- Si han pasado más de `stale_after_minutes` sin sincronizar, el LLM puede avisar al usuario

---

## Infraestructura de Tests

- `conftest.py`: fixtures de BD en memoria (SQLite), cliente HTTP de test, usuario dev
- `hr_seed.py`: datos de prueba (empleados, turnos, vacaciones, nóminas ficticios)
- `fakes/`: stubs de SharePoint y LLM para tests sin conectividad real
- Todos los tests usan la BD en memoria — no contaminan la BD de desarrollo
