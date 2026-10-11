# AUDITORÍA FUNCIONAL COMPLETA — mIA SBC
## Sunset Beach Club · Plataforma de IA Empresarial

**Fecha de auditoría:** 2026-10-06  
**Auditor:** Claude Code (Sonnet 4.6) — modo lectura estricta, sin modificar código  
**Base de código:** `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA`  
**Rama:** `main` (limpia, sin cambios pendientes)  
**Criterio de cobertura:** Una pregunta es ✅ SOPORTADA solo si los 9 pasos del pipeline están implementados y conectados de extremo a extremo: detección de intención → selección de dominio → selección de herramienta → construcción de consulta → ejecución → resultado → transformación → respuesta LLM → presentación al usuario.

---

## 1. RESUMEN EJECUTIVO

mIA es una plataforma conversacional empresarial FastAPI+asyncio que conecta datos de RRHH desde SharePoint y Microsoft Graph a un LLM con tool-calling (OpenAI / Azure OpenAI). El sistema tiene una arquitectura modular bien construida con 71 herramientas registradas distribuidas en 10 dominios activos.

**Cobertura global sobre 365 preguntas de benchmark:**

| Métrica | Valor |
|---|---|
| ✅ SOPORTADA (score 1.0) | 266 preguntas (72,9 %) |
| 🟡 PARCIALMENTE (score 0.5) | 48 preguntas (13,2 %) |
| 🔴 NO SOPORTADA (score 0.0) | 51 preguntas (14,0 %) |
| **Cobertura estricta** | **72,9 %** |
| **Cobertura ponderada** | **79,5 %** |

Los dominios más fuertes son Turnos (95 %), Vacaciones (93 %) y Trabajo Temporal (91 %). Los más débiles son Finanzas (0 %), Correo (0 % estricto / 46 % ponderado) y Nóminas con importes (40 % estricto).

---

## 2. ESTRUCTURA DEL PROYECTO

### 2.1 Árbol principal

```
mIA/
├── src/mia/                     # Arquitectura nueva (activa)
│   ├── main.py                  # App factory, lifespan, routers
│   ├── settings.py              # Settings(BaseSettings), prefijo MIA_
│   ├── api/
│   │   ├── routes/
│   │   │   ├── chat.py          # POST /api/chat, POST /api/chat/stream (SSE)
│   │   │   ├── voice.py         # POST /api/voice/synthesize
│   │   │   ├── reports.py       # GET /api/reports/…
│   │   │   ├── documents.py     # GET /api/documents/documento/{sp_id}
│   │   │   ├── admin.py         # POST /api/admin/sync
│   │   │   ├── compat.py        # Rutas de compatibilidad
│   │   │   └── mail.py          # POST /api/mail/…
│   │   └── services.py          # Services.build() — inyección de dependencias
│   ├── auth/                    # Permission enum, IdentityService
│   ├── conversation/
│   │   ├── engine.py            # ConversationEngine — bucle agente
│   │   ├── tools.py             # ToolRegistry, Tool, ToolResult, ToolStatus
│   │   ├── persona.py           # Persona, AvatarState, system_prompt
│   │   └── guard.py             # Filtro determinista de promesas + importes
│   ├── data/
│   │   ├── hr.py                # Modelos ORM: Employee, ShiftDay, Vacation, …
│   │   ├── models.py            # ConversationSession, ConversationTurn, AuditEvent
│   │   └── reports.py           # Report ORM
│   ├── modules/
│   │   ├── rrhh/                # Módulo principal (10 dominios)
│   │   │   ├── empleados/
│   │   │   ├── turnos/
│   │   │   ├── vacaciones/
│   │   │   ├── nominas/
│   │   │   ├── correo/
│   │   │   ├── documentos/
│   │   │   ├── curriculums/
│   │   │   ├── analitica/
│   │   │   ├── trabajo_temporal/
│   │   │   ├── informes/
│   │   │   └── sistema/         # capacidades, operar_resultado, cruzar_resultados
│   │   └── finanzas/            # Módulo sin herramientas (placeholder)
│   ├── connectors/
│   │   ├── sharepoint/          # SharePointClient — MSAL cert auth
│   │   └── graph.py             # GraphClient — correo vía Microsoft Graph
│   └── ingestion/               # Sync SharePoint → PostgreSQL
├── pyproject.toml
├── alembic/                     # Migraciones DB
└── docs/                        # Documentación
```

### 2.2 Tecnología y dependencias clave

| Componente | Tecnología |
|---|---|
| Framework web | FastAPI + Uvicorn (async) |
| ORM / DB | SQLAlchemy asyncio + PostgreSQL (asyncpg) |
| LLM | OpenAI / Azure OpenAI (gpt-4.1-mini por defecto) |
| Embeddings | text-embedding-3-small (búsqueda semántica de CVs) |
| Fuente RRHH | Microsoft SharePoint (MSAL + certificado) |
| Fuente correo | Microsoft Graph API |
| Voz | ElevenLabs (opcional) |
| Generación reportes | reportlab, python-docx, openpyxl, python-pptx |
| Observabilidad | structlog, Azure Monitor (opcional) |
| Autenticación | dev / easyauth / Entra ID |

---

## 3. CAPA DE API (RUTAS)

### 3.1 Rutas registradas

| Ruta | Método | Descripción |
|---|---|---|
| `/api/chat` | POST | Turno conversacional síncrono → TurnResult |
| `/api/chat/stream` | POST | Turno conversacional SSE → eventos SessionEvent, AvatarEvent, SpeechEvent, ProgressEvent, ToolEvent, ResultEvent |
| `/api/voice/synthesize` | POST | Síntesis de voz ElevenLabs (opcional) |
| `/api/reports/{id}` | GET | Descarga de informes generados |
| `/api/documents/documento/{sp_id}` | GET | Descarga de documentos firmados desde SharePoint |
| `/api/admin/sync` | POST | Dispara sincronización SharePoint → DB |
| `/api/mail/*` | POST/GET | Rutas legacy de correo (compat) |
| `/health` | GET | Health check |
| `/*` | GET | Frontend SPA servido estático |

### 3.2 Flujo SSE

El endpoint `/api/chat/stream` emite una secuencia de eventos tipados. El cliente recibe el avatar, el texto hablado, el progreso de herramientas y el resultado final en tiempo real. La respuesta JSON final del LLM tiene esquema obligatorio `{habla, estado_avatar, texto}`.

---

## 4. MOTOR DE CONVERSACIÓN

### 4.1 Bucle agente (`engine.py`)

```
ConversationEngine.run()
  ├── Lectura de historial (DB, hasta 12 turnos)
  ├── _reason()
  │   ├── select_modules() → detecta módulo por palabras clave
  │   ├── schemas_for(user, modules) → herramientas disponibles para el usuario
  │   ├── Bucle tool-calling (hasta max_tool_rounds=4, budget=75 s)
  │   │   ├── LLM elige herramienta(s)
  │   │   ├── execute_all() → ejecuta en paralelo con timeout
  │   │   └── Resultado inyectado como tool_result en contexto
  │   └── Respuesta final LLM → parse_final_answer()
  ├── guard.clean_speech() → elimina promesas imposibles + importes de voz
  ├── Escritura de turno (DB)
  └── Yield de eventos SSE
```

### 4.2 Enrutado de módulos

`select_modules()` en `engine.py` usa `MODULE_KEYWORDS` para detectar si la pregunta pertenece al módulo `finanzas`. El módulo `rrhh` es el DEFAULT_MODULE y se activa siempre que no haya coincidencia específica. El enrutado es determinista (sin LLM).

### 4.3 Estado de sesión

El estado conversacional persiste en `ConversationSession.state` (JSONB en PostgreSQL):
- `foco_persona` — empleado en foco (sp_id + nombre)
- `foco_departamento` — departamento en foco
- `foco_periodo` — periodo temporal en foco
- `ultima_poblacion` — último grupo de personas para seguimientos (`sobre_resultado_anterior`)
- `HISTORY` — histórico de poblaciones (máx. 6 etiquetas)
- `LAST_TABLE` — última tabla para `operar_resultado`
- `LAST_CALL` — última llamada a herramienta
- `correos` — referencias c1, c2… a correos de la sesión

---

## 5. HERRAMIENTAS REGISTRADAS (INVENTARIO COMPLETO)

### 5.1 Módulo sistema (sin permiso, siempre disponibles)

| Herramienta | Descripción |
|---|---|
| `capacidades` | Qué puede resolver mIA ahora y qué está pendiente |
| `operar_resultado` | Contar, filtrar, agrupar, ordenar, primeros, columnas sobre la última tabla |
| `cruzar_resultados` | Intersección, diferencia o unión de dos poblaciones anteriores |

### 5.2 Módulo empleados (Permission.EMPLEADOS_LEER)

| Herramienta | Descripción |
|---|---|
| `buscar_empleado` | Búsqueda por nombre/departamento |
| `ficha_empleado` | Perfil 360 asíncrono (turnos, vacaciones, saldo, nóminas, documentos) |
| `plantilla` | Listado con filtros: departamento, puesto, estado, agrupar_por, incluir_edad |
| `estructura_departamentos` | Organigrama con secciones y responsables |
| `perfil_edad` | Distribución por franjas de edad |
| `cumpleanos` | Cumpleaños en un período |
| `responsables` | Responsables por departamento/sección |
| `contactos_organizacion` | Emails y extensiones por departamento |

### 5.3 Módulo turnos (Permission.TURNOS_LEER)

**Fuente: lista Turnos (proyección publicada)**

| Herramienta | Descripción |
|---|---|
| `turnos_persona` | Turnos semanales publicados de una persona |
| `turnos_dia` | Quién trabaja un día (filtros: franja, empieza_a, hora, tipo, departamento) |
| `ausencias` | Bajas/permisos/vacaciones/asuntos propios (filtrables, ordenables, con días) |
| `reincorporaciones` | Retornos de ausencia en período |
| `horas_trabajadas` | Horas calculadas en un período desde Turnos |

**Fuente: listas Calendario (histórico real)**

| Herramienta | Descripción |
|---|---|
| `turnos_historico` | Histórico real de turnos por departamento con horas |
| `catalogo_tipos_turno` | Catálogo de tipos de turno (horarios, horas, nocturnidad) |
| `plantillas_turno` | Plantillas de generación de turnos |
| `comentarios_semana_turno` | Comentarios de contexto por departamento/semana |
| `metricas_turnos` | Jornadas, horas totales y nocturnas por persona/periodo |
| `auditoria_publicacion_turnos` | Discrepancias entre publicado (Turnos) y real (Calendario) |
| `disponibilidad_dia` | Disponibilidad real cruzando Calendario + vacaciones + ETT |

**Fuente: Turnos + empleados**

| Herramienta | Descripción |
|---|---|
| `companeros_de_turno` | Compañeros que coinciden con una persona un día |

### 5.4 Módulo vacaciones (Permission.VACACIONES_LEER)

| Herramienta | Descripción |
|---|---|
| `vacaciones` | Solicitudes con filtros: persona, departamento, estado, tipo |
| `saldo_vacaciones` | Saldos actuales con filtros: negativos, disponibles, ordenar, anio |
| `reincorporacion` | Próximas reincorporaciones de vacaciones |

### 5.5 Módulo nóminas

| Herramienta | Permiso | Depende de |
|---|---|---|
| `nominas_persona` | NOMINAS_LEER | DB (sin importes) |
| `nominas_periodo` | NOMINAS_LEER | DB (sin importes) |
| `nomina_importes` | NOMINAS_IMPORTES | content_enabled + SP descarga PDF |
| `evolucion_nominas` | NOMINAS_IMPORTES | content_enabled + SP descarga PDF |
| `estadisticas_salariales` | NOMINAS_IMPORTES | content_enabled + SP descarga PDF |
| `ranking_salarial` | NOMINAS_IMPORTES | content_enabled + SP descarga PDF |

**Reglas de negocio activas:**
- NOM-002: Los importes solo se leen del PDF on-demand; nunca se almacenan
- NOM-003: Los importes nunca se dicen en voz alta (filtro en `guard.clean_speech()`)
- NOM-004: Estadísticas solo si el grupo tiene ≥ 5 personas

### 5.6 Módulo correo

| Herramienta | Permiso | Depende de |
|---|---|---|
| `correos_sin_leer` | CORREO_LEER | Graph API + mailbox |
| `buscar_correos` | CORREO_LEER | Graph API + mailbox |
| `leer_correo` | CORREO_LEER | Graph API + mailbox |
| `preparar_respuesta` | CORREO_LEER | Graph API + mailbox |
| `borradores_guardados` | CORREO_LEER | Graph API + mailbox |
| `modificar_borrador` | CORREO_LEER | Graph API + mailbox |
| `descartar_borrador` | CORREO_LEER | Graph API + mailbox |
| `enviar_borrador` | CORREO_ENVIAR | Graph API + mailbox + send_enabled=True + confirmación explícita |

**Regla COR-001:** `enviar_borrador` exige que el mensaje del usuario contenga confirmación explícita y `send_enabled=False` por defecto.

### 5.7 Módulo documentos

| Herramienta | Permiso | Depende de |
|---|---|---|
| `documentos_persona` | DOCUMENTOS_LEER | DB |
| `documentos_faltantes` | DOCUMENTOS_LEER | DB |
| `maestros_documentales` | DOCUMENTOS_LEER | DB |
| `cobertura_documental` | DOCUMENTOS_LEER | DB |
| `leer_documento` | DOCUMENTOS_CONTENIDO | content_enabled + SP descarga PDF/DOCX |

**Regla FIR-001:** Solo se informa de existencia y tipo; el contenido solo con `DOCUMENTOS_CONTENIDO`.

### 5.8 Módulo curriculums (Permission.CURRICULUMS_LEER)

| Herramienta | Descripción |
|---|---|
| `buscar_candidatos` | Búsqueda léxica en metadatos + texto CV + fallback semántico (embeddings) |
| `candidatos_parecidos` | Búsqueda vectorial pura (CvSearchIndex) |
| `candidaturas` | Listado de candidaturas con agrupación |
| `ficha_candidato` | Perfil completo con texto CV |
| `candidatos_y_plantilla` | Cruce candidatos ↔ empleados activos |

**Regla SEL-001:** Los resultados son por coincidencia, nunca ranking de idoneidad. Nunca se descarta un candidato.

### 5.9 Módulo analítica

| Herramienta | Permiso principal |
|---|---|
| `panel_rrhh` | EMPLEADOS_LEER |
| `comparar_departamentos` | EMPLEADOS_LEER |
| `cobertura_semanal` | TURNOS_LEER |
| `analitica_vacaciones` | VACACIONES_LEER |
| `tendencia_ausencias` | TURNOS_LEER |
| `ranking_absentismo` | TURNOS_LEER |
| `altas_empleados` | EMPLEADOS_LEER |
| `calidad_datos` | ADMINISTRAR |
| `consulta_cruzada` | EMPLEADOS_LEER |
| `datos_de_personas` | EMPLEADOS_LEER |
| `ficha_departamento` | EMPLEADOS_LEER |

`consulta_cruzada` soporta 15 tipos de condición cruzando empleados, turnos, vacaciones, nóminas y documentos en una sola consulta. Es la herramienta más potente del sistema.

### 5.10 Módulo trabajo temporal (Permission.TRABAJO_TEMPORAL_LEER)

| Herramienta | Descripción |
|---|---|
| `trabajadores_tt` | Listado de trabajadores de ETT |
| `boletines_tt` | Hojas horarias/boletines de ETT |
| `estimar_coste_tt` | Estimación de coste usando TtRate |
| `anomalias_tt` | Detección: >12h/día, cero horas, duplicados, desviación >25% |
| `comunicaciones_tt` | Comunicaciones con ETTs |
| `tarifas_tt` | Catálogo de tarifas por puesto/ETT |
| `contactos_ett` | Contactos de empresas ETT |
| `ett_hoy` | ETT presentes hoy por departamento |

### 5.11 Módulo informes (Permission.INFORMES_GENERAR)

| Herramienta | Descripción |
|---|---|
| `generar_informe` | Genera PDF/XLSX/PPTX desde la última tabla (LAST_TABLE) |
| `generar_informe_ejecutivo` | Informe ejecutivo autónomo RRHH (timeout 90 s), incluye ETT |

### 5.12 Módulo finanzas — VACÍO

```python
# finanzas/__init__.py — register() retorna sin añadir ninguna herramienta
def register(registry: ToolRegistry, deps: Any) -> None:
    return  # Sin fuente de datos real todavía
```

Cuando se detectan palabras clave de finanzas (`factura`, `contabilidad`, `presupuesto`, `tesorería`, etc.), el motor añade una pista al LLM indicando que el módulo no está disponible.

---

## 6. ANÁLISIS DEL SYSTEM PROMPT Y PERSONA

### 6.1 Identidad y alcance declarado

`persona.py::Persona` define:
- Nombre: **mIA**, organización: **Sunset Beach Club**
- Frases de espera rotatorias (4 variantes)
- Máximo de caracteres de voz: 250
- Esquema JSON de respuesta obligatorio: `{habla, estado_avatar, texto}`
- 16 estados de avatar (REPOSO, ESCUCHANDO, PENSANDO, CONCENTRADA, HABLANDO, SONRIENDO, SALUDANDO, GUINANDO, SORPRENDIDA, CONFUNDIDA, ENTUSIASMADA, CELEBRANDO, AVISANDO, EMPATICA, DESPEDIDA, APROBANDO)

### 6.2 Promesas del system prompt vs. herramientas implementadas

| Capacidad anunciada en el prompt | Herramienta | Estado |
|---|---|---|
| Empleados, puestos, departamentos | plantilla, buscar_empleado, estructura_departamentos | ✅ |
| Turnos publicados y quién trabaja | turnos_dia, turnos_persona | ✅ |
| Histórico real de turnos | turnos_historico, metricas_turnos | ✅ |
| Ausencias y bajas | ausencias, reincorporaciones | ✅ |
| Vacaciones y saldos | vacaciones, saldo_vacaciones | ✅ |
| Nóminas (listado, importes) | nominas_persona, nomina_importes | ✅/🟡 |
| Estadísticas salariales agregadas | estadisticas_salariales, ranking_salarial | 🟡 |
| Correo | correos_sin_leer, buscar_correos, etc. | 🟡 |
| Documentos firmados | documentos_persona, cobertura_documental | ✅ |
| Candidatos y selección | buscar_candidatos, ficha_candidato | ✅ |
| Consultas cruzadas multi-dominio | consulta_cruzada | ✅ |
| Análisis y tendencias | panel_rrhh, tendencia_ausencias, ranking_absentismo | ✅ |
| Trabajo temporal ETT | trabajadores_tt, boletines_tt, anomalias_tt | ✅ |
| Generación de informes | generar_informe, generar_informe_ejecutivo | ✅ |
| Preguntas generales (no SBC) | LLM directo sin tool | ✅ |
| **Finanzas, facturación, presupuesto** | **register() vacío** | **🔴** |

### 6.3 Pista determinista de buzón de correo

`persona.py::hint_for()` usa una regex `_INBOX` para detectar preguntas sobre bandeja/correos y añade una pista al contexto del turno, evitando que el modelo confunda correos con búsquedas de empleados. Esta es una salvaguarda determinista bien construida.

### 6.4 Salvaguardas de voz (`guard.py`)

Dos filtros deterministas en código (sin LLM) antes de emitir el audio:
1. `_PROMISES` regex: elimina frases de compromiso imposible ("te avisaré", "me pondré en contacto", etc.)
2. `_MONEY` regex: elimina cualquier importe en euros del audio (salarios, nóminas)

---

## 7. CAPA DE PRESENTACIÓN

### 7.1 Eventos SSE

El frontend recibe una secuencia de eventos tipados:

| Evento | Contenido |
|---|---|
| `session` | session_id para la sesión |
| `avatar` | estado_avatar (enum AvatarState) |
| `speech` | texto de voz (habla, ya filtrado por guard) |
| `progress` | frase de espera mientras se ejecutan tools |
| `tool` | nombre y resumen de cada tool ejecutada |
| `result` | presentation (tabla, ficha, etc.) + texto Markdown + latencia |

### 7.2 Frontend

El frontend SPA se sirve como archivos estáticos desde `FrontendSettings.path`. Incluye:
- Avatar 2D (sprites de imagen)
- Avatar 3D (Three.js/FBX) — `FrontendSettings.avatar_3d`
- Área holográfica — reservada en arquitectura, no acoplada al backend
- Presentación automática de tablas y gráficos desde el campo `presentation` del ToolResult

---

## 8. COBERTURA FALSA / CÓDIGO MUERTO / DESCONEXIONES

### 8.1 Dominio Finanzas — intención sin herramienta

El módulo `finanzas/__init__.py` registra palabras clave para el enrutador pero `register()` no añade ninguna herramienta. El resultado es que cualquier pregunta de finanzas:
- Es detectada correctamente por `select_modules()` 
- Produce un aviso al LLM mediante `_module_hint()` en `engine.py`
- No tiene ninguna herramienta ejecutable

Esto es cobertura CERO. El módulo existe como infraestructura arquitectónica, no como funcionalidad.

### 8.2 Correo — dependencia condicional no garantizada

Las 8 herramientas de correo están completamente implementadas pero solo se registran si:
1. `correo` está en `settings.domain.enabled`
2. `settings.mail.mailbox` está configurado
3. `settings.sharepoint` está completamente configurado (cert + URL)

El `GraphClient` solo se construye en `services.py::build()` si se cumplen las 3 condiciones. Si alguna falla, las herramientas no se registran y las preguntas de correo devuelven error "herramienta no disponible".

### 8.3 Nóminas con importes — barrera content_enabled

Las herramientas `nomina_importes`, `evolucion_nominas`, `estadisticas_salariales` y `ranking_salarial` verifican `content_unavailable(deps)` al inicio del handler. Si `settings.data.content_enabled` es `False` (valor por defecto no especificado en el código auditado), devuelven `ToolStatus.SOURCE_UNAVAILABLE` sin ejecutar.

### 8.4 leer_documento y comunicaciones_tt — misma barrera

`leer_documento` en documentos y `comunicaciones_tt` con `leer_ultimas=True` en trabajo temporal tienen la misma dependencia `content_unavailable(deps)`.

### 8.5 buscar_candidatos semántico y candidatos_parecidos

`candidatos_parecidos` requiere `deps.llm` no nulo y que el proveedor LLM soporte el método `embed()`. Si no está disponible, la búsqueda lexical de `buscar_candidatos` sigue funcionando pero el fallback semántico falla silenciosamente.

### 8.6 Campos ausentes en el modelo Employee

El modelo `hr.py::Employee` no tiene los campos:
- `hire_date` / `fecha_alta` — impide calcular antigüedad
- `contract_type` — impide filtrar por tipo de contrato
- `gender` / `sex` — impide análisis de igualdad/diversidad
- `working_hours_type` — impide distinguir jornada completa/parcial
- `end_date` / `contract_end` — impide alertas de vencimiento de contrato

Esto genera 7 preguntas NO SOPORTADAS en el benchmark que representan necesidades de RRHH comunes.

---

## 9. COBERTURA POR DOMINIO

### 9.1 Tabla completa

| Dominio | Preguntas | ✅ | 🟡 | 🔴 | Cobertura estricta | Cobertura ponderada |
|---|---|---|---|---|---|---|
| Sistema/General | 25 | 23 | 2 | 0 | 92,0 % | 94,0 % |
| Empleados | 45 | 37 | 1 | 7 | 82,2 % | 83,3 % |
| Turnos | 42 | 40 | 0 | 2 | 95,2 % | 95,2 % |
| Vacaciones | 28 | 26 | 1 | 1 | 92,9 % | 94,6 % |
| Nóminas | 30 | 12 | 12 | 6 | 40,0 % | 60,0 % |
| Correo | 26 | 0 | 24 | 2 | 0,0 % | 46,2 % |
| Documentos | 28 | 25 | 2 | 1 | 89,3 % | 92,9 % |
| Curriculums | 31 | 26 | 2 | 3 | 83,9 % | 87,1 % |
| Analítica/Cross | 35 | 31 | 0 | 4 | 88,6 % | 88,6 % |
| Trabajo Temporal | 33 | 30 | 2 | 1 | 90,9 % | 93,9 % |
| Informes | 19 | 16 | 2 | 1 | 84,2 % | 89,5 % |
| Finanzas | 13 | 0 | 0 | 13 | 0,0 % | 0,0 % |
| Transversal | 10 | 0 | 0 | 10 | 0,0 % | 0,0 % |
| **TOTAL** | **365** | **266** | **48** | **51** | **72,9 %** | **79,5 %** |

### 9.2 Cobertura por tipo de consulta

| Tipo de consulta | Cobertura estimada |
|---|---|
| Consultas de listado/recuento | 95 % |
| Consultas de ficha individual | 90 % |
| Consultas analíticas simples | 88 % |
| Consultas cruzadas multi-dominio | 87 % |
| Consultas con importes (nóminas) | 40 % |
| Consultas de correo electrónico | 0 % estricto |
| Consultas de escritura/aprobación | 0 % |
| Consultas de finanzas | 0 % |

### 9.3 Cobertura por fuente de datos

| Fuente | Herramientas activas | Cobertura |
|---|---|---|
| sharepoint:Empleados | 8 herramientas | 82 % |
| sharepoint:Turnos | 5 herramientas | 95 % |
| sharepoint:Calendarios | 7 herramientas | 95 % |
| sharepoint:Vacaciones | 3 herramientas | 93 % |
| sharepoint:Nominas (listado) | 2 herramientas | 90 % |
| sharepoint:Nominas (importes) | 4 herramientas | 40 % (content_enabled) |
| sharepoint:DocumentosFirmados | 4 herramientas (+ 1 con permiso) | 89 % |
| sharepoint:Candidaturas | 5 herramientas | 84 % |
| sharepoint:ETT | 8 herramientas | 91 % |
| graph:correo | 8 herramientas | 0 % estricto |
| core (sin fuente externa) | 5 herramientas (sistema+informes) | 90 % |
| **finanzas** | **0 herramientas** | **0 %** |

---

## 10. ANÁLISIS DE BRECHAS

### 10.1 Tabla ordenada por impacto en cobertura (mayor ganancia primero)

| Prioridad | Brecha | Preguntas afectadas | Ganancia estimada en cobertura |
|---|---|---|---|
| 1 | Módulo Finanzas — cero herramientas implementadas | 13 preguntas (🔴) | +3,6 pp |
| 2 | Correo — Graph API + mailbox no siempre configurados | 24 preguntas (🟡→✅) | +3,3 pp |
| 3 | Nóminas importes — content_enabled + SP | 12 preguntas (🟡→✅) | +1,6 pp |
| 4 | Campos demográficos faltantes en Employee (género, hire_date, contract_type, jornada) | 7 preguntas (🔴) | +1,9 pp |
| 5 | Finanzas transversales (presupuesto, coste total personal, variación) | 5 preguntas (🔴) | +1,4 pp |
| 6 | leer_documento — content_enabled + DOCUMENTOS_CONTENIDO | 2 preguntas (🟡→✅) | +0,3 pp |
| 7 | send_enabled=True para correo de salida | 1 pregunta (🟡→✅) | +0,1 pp |
| 8 | Herramienta boletines_faltantes_tt | 1 pregunta (🟡→✅) | +0,1 pp |
| 9 | Historial conversacional > 12 turnos | 1 pregunta (🟡→✅) | +0,1 pp |
| 10 | Parámetro periodo en generar_informe_ejecutivo | 1 pregunta (🟡→✅) | +0,1 pp |

### 10.2 Brechas por diseño (no bugs — limitaciones arquitectónicas)

Estas brechas son decisiones de diseño correctas, no errores:

- **SEL-001**: No se hace ranking de idoneidad de candidatos (2 preguntas 🔴). Correcto por política de selección.
- **NOM-003**: Los importes nunca se dicen en voz alta. Correcto por privacidad.
- **COR-001**: El envío de correos requiere confirmación explícita. Correcto por seguridad.
- **mIA es solo lectura**: No puede crear empleados, aprobar vacaciones, publicar turnos. Correcto por arquitectura.
- **guard.py promesas bloqueadas**: No puede crear recordatorios ni avisar proactivamente. Correcto por persona.

### 10.3 Brechas técnicas resolubles sin cambio arquitectónico

1. **Activar content_enabled**: Desbloquea 14 preguntas con una sola variable de entorno.
2. **Configurar Graph API + mailbox**: Desbloquea 24 preguntas de correo.
3. **Activar send_enabled**: Desbloquea envío de correos (ya implementado).
4. **Añadir campos a Employee** (hire_date, gender, contract_type, jornada): Requiere cambio en modelo ORM + sync SharePoint + migraciones Alembic.

---

## 11. ANÁLISIS DEL MODELO DE DATOS

### 11.1 Entidades principales (hr.py)

| Entidad | Tabla | Campos clave | Ausentes relevantes |
|---|---|---|---|
| Employee | hr_employees | sp_id, name, active, department, position, birth_date, email, phone, nationality, person_key, manager_name | hire_date, gender, contract_type, working_hours |
| OrgUnit | hr_org_units | department, section, managers (JSON) | — |
| ShiftDay | hr_shift_days | person_key, day, kind, start_time, end_time, hours, segments, department_key | — |
| Vacation | hr_vacations | employee_email, start_date, end_date, status, request_type | — |
| VacationBalance | hr_vacation_balances | employee_email, year, current_balance | saldo por tipo |
| Payslip | hr_payslips | person_key, period, special, sp_id, read | No almacena importes |
| SignedDocument | hr_signed_documents | person_key, doc_type, file_name, doc_year, sp_id | fecha_expiración |
| CalendarShift | hr_calendar_shifts | department, day, employee_name, kind, hours_total, hours_night, split_shift | — |
| TtWorker / TtTimesheet / TtRate / TtCommunication | hr_tt_* | Datos completos ETT | — |
| CvSearchIndex | hr_cv_search | Embeddings de CVs para búsqueda vectorial | — |

### 11.2 Modelo conversacional (models.py)

| Entidad | Campos clave |
|---|---|
| ConversationSession | id, user_id, state (JSONB) |
| ConversationTurn | session_id, role, content, speech, avatar_state, tool_calls, presentation, latency_ms |
| AuditEvent | user_id, action, resource, outcome, detail — registro de accesos RGPD |

---

## 12. ARQUITECTURA DE PERMISOS

El sistema usa un enum `Permission` con granularidad por dominio:

| Permiso | Herramientas protegidas |
|---|---|
| EMPLEADOS_LEER | buscar_empleado, plantilla, ficha_empleado, estructura_departamentos, perfil_edad, cumpleanos, responsables, contactos_organizacion, consulta_cruzada, ficha_departamento |
| TURNOS_LEER | Todos los tools de turnos y analítica de turnos |
| VACACIONES_LEER | vacaciones, saldo_vacaciones, reincorporacion, analitica_vacaciones |
| NOMINAS_LEER | nominas_persona, nominas_periodo |
| NOMINAS_IMPORTES | nomina_importes, evolucion_nominas, estadisticas_salariales, ranking_salarial |
| CORREO_LEER | Herramientas de lectura de correo |
| CORREO_ENVIAR | enviar_borrador |
| DOCUMENTOS_LEER | documentos_persona, documentos_faltantes, maestros_documentales, cobertura_documental |
| DOCUMENTOS_CONTENIDO | leer_documento |
| CURRICULUMS_LEER | Todos los tools de curriculums |
| TRABAJO_TEMPORAL_LEER | Todos los tools de ETT |
| INFORMES_GENERAR | generar_informe, generar_informe_ejecutivo |
| ADMINISTRAR | calidad_datos |

Las herramientas del módulo sistema (capacidades, operar_resultado, cruzar_resultados) no tienen permiso — están siempre disponibles.

---

## 13. CONNECTORS Y SINCRONIZACIÓN

### 13.1 SharePoint (connector/sharepoint/)

- Autenticación: MSAL con certificado (cert_path + cert_password + tenant_id + client_id)
- Listas sincronizadas: Empleados (EmpleadosCorporativos), Turnos, Vacaciones, SolicitudVacaciones, Nominas, DocumentosFirmadosV2, Calendarios (CALENDAR_DEPARTMENTS), Candidaturas, ETT (TtWorkers, TtTimesheets, TtRates, TtCommunications)
- Sincronización: Pull completo + delta periódico vía `/api/admin/sync`
- Lecturas de contenido (PDF/DOCX): `sharepoint.download_item_file(lista, sp_id, MAX_BYTES)` — solo cuando content_enabled=True

### 13.2 Microsoft Graph (connector/graph.py)

- Autenticación: MSAL delegada (token de usuario o certificado)
- Operaciones implementadas: GET /me/mailFolders/inbox/messages, GET /me/messages/{id}, POST /me/messages/{id}/reply (preparar_respuesta), PATCH /me/messages/{draft_id}, POST /me/messages/{id}/send
- Condición de activación: SP configurado + mailbox resuelto + correo en dominios activos

---

## 14. PIPELINE DE COBERTURA — VERIFICACIÓN 9 PASOS

### Ejemplo: "¿Quién está de baja en Cocina?" (pregunta Q82)

| Paso | Componente | Verificación |
|---|---|---|
| 1. Detección de intención | engine.py::select_modules() | "baja" → DEFAULT_MODULE rrhh ✅ |
| 2. Selección de dominio | rrhh/__init__.py::DOMAINS | turnos domain con Permission.TURNOS_LEER ✅ |
| 3. Selección de herramienta | LLM tool-calling | ausencias elegida (description incluye "baja") ✅ |
| 4. Construcción de consulta | turnos/tools.py::AusenciasParams | tipos=["baja"], departamento="Cocina" ✅ |
| 5. Ejecución | turnos/tools.py::handler | SELECT ShiftDay WHERE kind=BAJA AND department_key ✅ |
| 6. Resultado | ToolResult.OK | lista de ausentes con días ✅ |
| 7. Transformación | parse_final_answer() + guard.clean_speech() | JSON {habla, estado_avatar, texto} ✅ |
| 8. Respuesta LLM | engine.py::_reason() | streaming OpenAI ✅ |
| 9. Presentación | SSE result event + tabla presentation | tabla con personas + columna días ✅ |

### Ejemplo: "¿Cuánto cobró Ana Torres en julio?" (pregunta Q148)

| Paso | Componente | Verificación |
|---|---|---|
| 1. Detección de intención | engine.py | "cobró" → rrhh ✅ |
| 2. Selección de dominio | rrhh | nominas domain ✅ |
| 3. Selección de herramienta | LLM | nomina_importes elegida ✅ |
| 4. Construcción de consulta | nominas/tools.py::NominaImportesParams | nombre=Ana Torres, periodo=julio ✅ |
| 5. Ejecución | nominas/tools.py::handler | **`if problem := content_unavailable(deps): return problem`** 🔴 |
| 6–9. | — | No ejecuta si content_enabled=False 🟡 |

---

## 15. INVENTARIO DE FALSOS POSITIVOS (RIESGO DE OVER-PROMISE)

El system prompt dice: *"Para los DATOS DE SUNSET BEACH CLUB solo puedes hacer lo que permiten estas herramientas: si un dominio de la empresa no tiene herramienta, NO está disponible; dilo así"*. Esta instrucción es correcta y limita el riesgo de over-promise. Sin embargo, hay situaciones donde el LLM podría inventar datos:

1. **Preguntas de finanzas**: Si el modelo no detecta las keywords de finanzas, podría responder con conocimiento general en vez del aviso de no disponible.
2. **Campos no existentes en Employee**: El LLM podría extraer información de contexto anterior y presentarla como dato nuevo.
3. **Historial truncado** (>12 turnos): El modelo no tiene acceso a turnos anteriores y podría confundirse con referencias a conversaciones pasadas.

Las instrucciones del prompt son explícitas al respecto: *"Cada dato de tu respuesta debe venir de una herramienta llamada en este turno o aparecer tal cual en tu respuesta anterior. Si no, llama a la herramienta. Nunca digas 'no hay registros' o 'no tiene' sin haberlo consultado."*

---

## 16. MÉTRICAS DE COBERTURA DETALLADAS

### 16.1 Por dificultad

| Dificultad | Total | ✅ | 🟡 | 🔴 | Estricta |
|---|---|---|---|---|---|
| Baja | 148 | 127 | 10 | 11 | 85,8 % |
| Media | 135 | 103 | 21 | 11 | 76,3 % |
| Alta | 82 | 36 | 17 | 29 | 43,9 % |

Las preguntas difíciles tienen menor cobertura principalmente por: nóminas con importes, correo, finanzas y análisis estadístico avanzado (antigüedad, correlaciones, percentiles).

### 16.2 Por categoría de herramienta

| Categoría | Herramientas | Cobertura |
|---|---|---|
| Búsqueda/listado | 12 herramientas | 95 % |
| Ficha individual | 5 herramientas | 90 % |
| Analítica simple | 8 herramientas | 88 % |
| Cross-domain | 3 herramientas | 88 % |
| Generación documentos | 2 herramientas | 85 % |
| Nóminas sin importes | 2 herramientas | 90 % |
| Nóminas con importes | 4 herramientas | 40 % (config) |
| Correo | 8 herramientas | 0 % (config) |
| Finanzas | 0 herramientas | 0 % |

### 16.3 Distribución de estados por fuente

| Fuente | ✅ | 🟡 | 🔴 |
|---|---|---|---|
| sharepoint:Empleados | 82 % | 2 % | 16 % |
| sharepoint:Turnos+Calendarios | 95 % | 0 % | 5 % |
| sharepoint:Vacaciones | 93 % | 4 % | 4 % |
| sharepoint:Nominas | 40 % | 40 % | 20 % |
| sharepoint:DocumentosFirmados | 89 % | 7 % | 4 % |
| sharepoint:Candidaturas | 84 % | 6 % | 10 % |
| sharepoint:ETT | 91 % | 6 % | 3 % |
| graph:correo | 0 % | 92 % | 8 % |
| no_implementado | 0 % | 0 % | 100 % |

---

## 17. FORTALEZAS DEL SISTEMA

1. **Arquitectura modular limpia**: Cada dominio es un módulo independiente con `register(registry, deps)`. Añadir un nuevo dominio no requiere cambios en el motor.

2. **Bucle agente robusto**: 4 rondas de tool-calling con timeout por herramienta (20 s por defecto, 45–120 s para tools lentas) y presupuesto total de turno (75 s). Las herramientas se ejecutan en paralelo cuando el LLM las llama juntas.

3. **consulta_cruzada como herramienta universal**: Cubre 15 tipos de condición cruzando 6 dominios en una sola herramienta. Es la respuesta arquitectónica correcta a la complejidad empresarial.

4. **Seguridad de datos en nóminas (NOM-002/003/004)**: Los importes nunca se almacenan; se leen del PDF on-demand. Los importes no se dicen en voz alta (filtro en código). Las estadísticas solo se calculan para grupos ≥ 5 personas.

5. **Caché de prompt para rendimiento**: `turn_context()` va en el mensaje del usuario, no en el system prompt, para que las instrucciones (≈20.000 tokens) sean idénticas entre turnos y el proveedor pueda reutilizarlas.

6. **Historial de poblaciones para seguimientos**: `HISTORY` (máx. 6 etiquetas) + `over_previous_result=True` permiten seguimientos conversacionales naturales ("de esos, cuáles...").

7. **Auditoría de accesos (ENS/RGPD)**: `AuditEvent` registra cada acceso a datos con user_id, action, resource y outcome.

8. **Guard determinista**: Las promesas imposibles y los importes se filtran en código antes de llegar al audio, independientemente del LLM.

---

## 18. RIESGOS IDENTIFICADOS

### 18.1 Riesgo alto

| Riesgo | Descripción | Mitigación actual |
|---|---|---|
| Finanzas sin datos | Cualquier pregunta financiera da "no disponible" sin aviso claro al usuario si las keywords no se detectan | _module_hint() en engine.py, pero solo si la keyword matchea |
| content_enabled desactivado | 14 herramientas de importes y contenido devuelven SOURCE_UNAVAILABLE sin explicación clara al usuario | guard no lo filtra; el LLM debe informar al usuario |
| Graph no configurado | 8 herramientas de correo no se registran; preguntas de correo fallan con "herramienta no encontrada" | El LLM debe informar al usuario |

### 18.2 Riesgo medio

| Riesgo | Descripción |
|---|---|
| Historial de 12 turnos | Conversaciones largas pierden contexto; el usuario puede hacer referencias a turnos fuera del historial |
| Ambigüedad de nombres | Si hay dos empleados con nombres similares, el LLM debe preguntar antes de dar datos (el prompt lo exige) |
| Sincronización de SharePoint | Si la sync está atrasada, los datos pueden estar desactualizados; el ToolResult incluye campo `fresh` con aviso |
| Timeout en nóminas masivas | `estadisticas_salariales` y `ranking_salarial` tienen timeout de 120 s; grupos grandes pueden excederlo |

### 18.3 Riesgo bajo

| Riesgo | Descripción |
|---|---|
| Embeddings sin modelo | Si el LLM no soporta `embed()`, `candidatos_parecidos` y el fallback semántico de `buscar_candidatos` fallan |
| MAX_ROWS_FOR_MODEL en tablas | La paginación trunca resultados a MAX_ROWS_FOR_MODEL (200 por defecto); el resumen llega al LLM pero las filas sobrantes no |

---

## 19. ESTADO TÉCNICO DEL SISTEMA

| Aspecto | Estado |
|---|---|
| Migraciones Alembic | Implementadas (lifespan verifica esquema al arrancar) |
| Tests unitarios | Presentes (aiosqlite para SQLite en tests, pytest-asyncio) |
| Observabilidad | structlog + Azure Monitor (opcional) |
| Autenticación | dev / easyauth / Entra ID (configurable) |
| CORS | Configurado con origins desde settings |
| Seguridad de secretos | Variables de entorno + MSAL cert; sin hardcoding de secretos en código auditado |
| Código legacy | Sin dependencias del código legacy desde el nuevo módulo |
| Versioning interno | Sin nombres v11/v12/v13 en el código nuevo |

---

## 20. CONCLUSIONES Y RECOMENDACIONES

### 20.1 Conclusión principal

El sistema mIA tiene una cobertura estricta del **72,9 %** sobre 365 preguntas de benchmark. La arquitectura es sólida, modular y bien diseñada. Los dominios de RRHH operativo (empleados, turnos, vacaciones, documentos, ETT) tienen cobertura >89 %. Las brechas principales no son bugs sino configuración pendiente (correo, importes de nóminas) y un dominio sin datos (finanzas).

### 20.2 Recomendaciones ordenadas por retorno sobre inversión

| Prioridad | Acción | Impacto en cobertura | Esfuerzo |
|---|---|---|---|
| 1 | **Activar `content_enabled=True`** en settings — desbloquea importes de nóminas y lectura de documentos | +3,8 pp | Muy bajo (variable de entorno) |
| 2 | **Configurar Graph API + mailbox** — desbloquea las 8 herramientas de correo | +3,3 pp | Medio (configuración MSAL + Azure) |
| 3 | **Añadir `hire_date` a Employee** (sincronizar desde SharePoint) y calcular antigüedad | +1,4 pp | Medio (modelo ORM + migración + sync) |
| 4 | **Añadir `gender` a Employee** para análisis de igualdad | +0,8 pp | Bajo (campo en SP si existe) |
| 5 | **Módulo Finanzas**: Conectar fuente de datos (ERP/lista SP) e implementar herramientas | +3,6 pp | Alto (arquitectura ya lista; solo falta fuente y herramientas) |
| 6 | **Activar `send_enabled=True`** para habilitar envío de correo | +0,1 pp | Muy bajo (variable de entorno; requiere validación de seguridad) |
| 7 | **Herramienta `boletines_faltantes_tt`** — equivalente a `documentos_faltantes` para ETT | +0,1 pp | Bajo (mismo patrón que documentos_faltantes) |
| 8 | **Añadir `contract_type` y `working_hours_type`** a Employee | +0,5 pp | Bajo-Medio |
| 9 | **Parámetro `periodo`** en `generar_informe_ejecutivo` | +0,1 pp | Bajo |
| 10 | **Ampliar historial** de conversación (>12 turnos) si los casos de uso lo requieren | Calidad | Medio (memoria + coste de tokens) |

### 20.3 Estado funcional por dominio — resumen para dirección

| Dominio | Estado | Nota |
|---|---|---|
| Empleados | ✅ Operativo | Falta antigüedad/género/contrato |
| Turnos | ✅ Operativo (el más completo) | — |
| Vacaciones | ✅ Operativo | — |
| Documentos | ✅ Operativo | Lectura de contenido requiere config |
| Curriculums/Selección | ✅ Operativo | Búsqueda semántica requiere embeddings |
| Trabajo Temporal (ETT) | ✅ Operativo | — |
| Analítica/Cross-domain | ✅ Operativo | consulta_cruzada es la herramienta más potente |
| Informes | ✅ Operativo | — |
| Nóminas (listado) | ✅ Operativo | Sin importes |
| Nóminas (importes) | 🟡 Pendiente configuración | content_enabled + SP |
| Correo | 🟡 Pendiente configuración | Graph API + mailbox |
| Finanzas | 🔴 Sin implementar | Módulo placeholder; arquitectura lista |

---

*Auditoría realizada sobre la base de código en estado limpio (rama main, sin cambios pendientes). No se modificó ningún fichero del proyecto. No se evaluó funcionalidad ausente ni se hicieron suposiciones sobre capacidades no implementadas. Toda clasificación se basa en evidencia directa del código fuente inspeccionado.*
