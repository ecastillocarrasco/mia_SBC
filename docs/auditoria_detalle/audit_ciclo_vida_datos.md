# Auditoría de ciclo de vida y retención de datos personales — mIA

Origen: validación de un informe externo (ChatGPT) que señalaba: *"Presidio protege los datos antes
de enviarlos al LLM, pero no garantiza que no se guarden en otras partes de mIA. Hay que revisar y
documentar todo el ciclo de vida y la retención de datos."*

**Veredicto**: la afirmación es correcta y ya estaba parcialmente reflejada en
[audit_llm_presidio_voz.md](audit_llm_presidio_voz.md) (sección 3: *"Presidio protege el tránsito por
el proveedor externo, no la pantalla del usuario legítimo"*). Este documento completa esa auditoría
mapeando, almacén por almacén, dónde queda PII en claro dentro de mIA, con qué retención y con qué
mecanismo de purga. Identificó un hallazgo no cubierto hasta entonces — el registro de auditoría
(`AuditEvent`) no tenía ninguna política de retención — que ya se ha **implementado y cerrado** (ver
más abajo).

**Objetivo de este documento, ampliado**: no es solo justificar este punto concreto del informe de
ChatGPT, sino dejar constancia, almacén por almacén, de que el ciclo de vida de los datos personales en
mIA está alineado con el principio de limitación del plazo de conservación (RGPD art. 5.1.e) — cada
almacén que contiene PII tiene ya un plazo definido y una base que lo justifica, o está señalado
explícitamente como pendiente de decisión (sección "Otros puntos a documentar"). Este documento no
sustituye al Registro de Actividades de Tratamiento (RAT) ni a una auditoría legal de un DPO — es la
base técnica (de código) sobre la que ese análisis legal debe apoyarse.

Metodología: lectura directa del código fuente en `src/mia/`. Toda afirmación cita fichero:línea.

---

## Por qué "proteger antes del LLM" no es "proteger en todo el sistema"

Presidio en mIA (`src/mia/privacy_gateway/`) actúa en un único punto: la salida hacia el proveedor LLM
externo (OpenAI/Azure OpenAI) y hacia el proveedor de embeddings. Su contrato es explícito en el propio
código:

- Antes de salir al LLM, el texto se tokeniza (`PrivacyGateway._sanitize_request`,
  `src/mia/privacy_gateway/gateway.py:201`).
- Al volver del LLM, **antes de mostrarlo al usuario autorizado, se restaura al valor real**
  (`tokenizer.restore`, `src/mia/privacy_gateway/gateway.py:218`).
- Para embeddings, la sustitución es irreversible y permanente (`_anonymize_for_embedding`,
  `src/mia/privacy_gateway/gateway.py:267-287`), pero solo protege el vector que se envía a vectorizar,
  no el texto fuente.

Es decir: por diseño, **el usuario legítimo tiene que ver sus datos reales**, así que en cuanto la
respuesta sale del gateway hacia el resto de la aplicación (base de datos, auditoría, diagnósticos,
caché de voz), el dato vuelve a ser texto plano. A partir de ahí, lo que proteja al dato ya no es
Presidio: es cada almacén por su cuenta (retención, cifrado en reposo, control de acceso). El informe
de ChatGPT identifica correctamente ese límite; lo que faltaba era verificar, con código, qué hace (o
no hace) cada almacén al respecto.

---

## Mapa de almacenes de datos personales

| Almacén | Contiene PII en claro | Dónde vive | Retención | Purga automática |
|---|---|---|---|---|
| Historial de conversación (`ConversationTurn.content`) | ✅ Sí — mensaje del usuario y respuesta final ya restaurada | PostgreSQL | 30 días (`conversation_retention_days`, `src/mia/settings.py:337`) | ✅ Job cada 6h (`run_retention_cleanup`, `src/mia/conversation/retention.py:14-25`, llamado desde `src/mia/main.py:50`) |
| Registro de auditoría (`AuditEvent.detail.arguments`) | ✅ Sí — argumentos reales de las herramientas ejecutadas (nombres, periodos, IDs de documento) (`src/mia/conversation/engine.py:641`) | PostgreSQL | 1095 días / 3 años (`audit_retention_days`, `src/mia/settings.py:337-345`, justificado por el plazo de prescripción de infracciones muy graves del art. 76 LOPDGDD) | ✅ Job cada 6h (`run_audit_retention_cleanup`, `src/mia/data/retention.py`, llamado desde `src/mia/main.py:50-58`) |
| Trazas de diagnóstico (`TraceRecord`) | 🟡 Depende de `mask_pii` | **Memoria del proceso**, nunca disco/BD (`DiagnosticsStore`, `src/mia/diagnostics/store.py:24`) | 24h (`retention_hours`, `src/mia/diagnostics/config.py:12`) + límite de nº de trazas | ✅ Loop cada 5 min (`_cleanup_loop`, `src/mia/diagnostics/store.py:82-88`); además se pierde entero al reiniciar el proceso |
| RAG — CVs y documentos indexados (`HrDocumentText`, `HrDocumentChunk`, `hr_cv_chunks`) | ✅ Sí — el **texto original** se guarda sin anonimizar para lectura autorizada; solo el **embedding** que se envía a vectorizar va anonimizado (`project_payroll_embedding`/`_anonymize_for_embedding`, `src/mia/privacy_gateway/gateway.py:267-287`) | PostgreSQL + pgvector | ❌ Sin retención temporal propia | 🟡 Solo se elimina si el documento fuente desaparece de SharePoint en la siguiente sincronización (`DocumentIndexer.run`, `src/mia/modules/rrhh/document_indexing.py:311-321`) — no hay un TTL independiente |
| Token Vault (pseudonimización reversible) | ✅ Sí (cifrado) | **Memoria del proceso** (Fernet), nunca disco/BD (comentario explícito, `src/mia/privacy_gateway/token_vault.py:4-6`) | TTL 900s por defecto (`vault_ttl_seconds`, `src/mia/settings.py:230-231`) | ✅ Purga por antigüedad + purga explícita al cerrar la operación (`purge_operation`, `token_vault.py:69-74`) |
| Adjuntos de conversación | ✅ Sí (ficheros subidos por el usuario) | `LocalStorage` o `AzureBlobStorage` (`src/mia/attachments/storage.py:23,57`) | 24h por defecto (`retention_hours`, `src/mia/attachments/service.py:50`) | ✅ Batch de expirados (`attachment.expired_batch`, `src/mia/attachments/service.py:218`) |
| Informes/reportes generados (PDF, Excel) | ✅ Sí (datos de negocio exportados) | `StorageBackend` + tabla `Report` | `expires_at` por informe | ✅ Job cada 6h (`run_report_cleanup`, `src/mia/reporting/retention.py:26-55`) |
| Caché de voz (ElevenLabs) | 🟡 Solo frases cortas y repetidas | Memoria (`CachedVoice`) | N/A — por diseño nunca cachea respuestas largas/variables (`max_chars=160`, `src/mia/voice/cache.py:16,40`) | No aplica (no hay datos de negocio reales en caché) |
| Logs estructurados (stdout → Application Insights en Azure) | ❌ No, por diseño | Azure Log Analytics / consola | Según política de retención de Azure Monitor (fuera del código) | El redactor de logs (`_redact`, `src/mia/observability/logging.py:24-28`) solo tapa claves tipo `password`/`token`/`secret`, **no PII** — la protección real es que ningún `log.info/warning/error` del código pasa contenido libre (`message`, `content`, `query`) como campo; se verificó por inspección de todas las llamadas a `log.*` en `src/mia/` |

---

## Hallazgo cerrado: `AuditEvent` ya tiene política de retención ✅ (implementado 2026-10-24)

El modelo `AuditEvent` se describe en su propio docstring como *"Registro de accesos a datos (evidencia
para ENS/RGPD)"* (`src/mia/data/models.py:69-70`), y cada ejecución de herramienta que toca un recurso
auditado guarda sus argumentos reales — que pueden incluir nombre de empleado, periodo de nómina, ID de
documento, etc. (`detail={"arguments": json.loads(execution.call.arguments or "{}")}`,
`src/mia/conversation/engine.py:641`).

A diferencia de `ConversationTurn` (purgado a los 30 días), hasta esta implementación `AuditEvent`
**no se purgaba nunca**: no había ningún `DELETE` sobre `audit_events` en todo el árbol `src/mia/`
fuera de su propia inserción.

Esto no era necesariamente un error de código — un log de auditoría RGPD/ENS legítimamente necesita
sobrevivir más tiempo que el historial conversacional, precisamente para poder demostrar quién accedió
a qué — pero RGPD exige que la conservación tenga un plazo definido y justificado (principio de
limitación del plazo de conservación, art. 5.1.e RGPD), y el plazo era "indefinido" por omisión de
código, no por decisión documentada.

**Solución implementada**:

- `AuditRepository.purge_expired(db, retention_days, now=None) -> int` (`src/mia/data/repositories.py:91-96`),
  análogo a `ConversationRepository.purge_expired` (`src/mia/data/repositories.py:54-62`): elimina los
  `AuditEvent` con `created_at` anterior al plazo de retención.
- `Settings.audit_retention_days: int = 1095` (3 años) (`src/mia/settings.py:337-345`). **Base legal del
  plazo**: RGPD art. 5.1.e exige un plazo *limitado y justificado*, pero no fija un número — el RGPD no
  contiene una tabla de plazos de retención. El plazo elegido (1095 días) se justifica por el art. 76
  LOPDGDD, que fija en 3 años la prescripción de las infracciones **muy graves** de protección de
  datos: ese es el periodo durante el que mIA podría necesitar exhibir el registro de auditoría para
  defenderse ante una reclamación o inspección de la AEPD. Pasado ese plazo, conservar el registro deja
  de tener base legal y debe eliminarse. Es un valor configurable (`MIA_AUDIT_RETENTION_DAYS`), no un
  hardcode — si el DPO de Sunset Beach Club determina otro plazo (p. ej. por un convenio colectivo o una
  obligación sectorial distinta), basta con cambiar la variable de entorno.
- `run_audit_retention_cleanup()` (`src/mia/data/retention.py`), tarea de fondo que purga cada 6 horas,
  arrancada en `create_app()` junto a la de conversaciones (`src/mia/main.py:50-58,79,115-118`) y
  cancelada limpiamente al apagar la app.
- Tests: `tests/test_retention.py` — cubre tanto `AuditRepository.purge_expired` (nuevo) como
  `ConversationRepository.purge_expired` (existente, sin test previo).

---

## Otros puntos a documentar (no bloqueantes, pero parte del ciclo de vida)

1. **RAG sin TTL propio**: el contenido de CVs/nóminas/documentos indexado para búsqueda semántica
   vive mientras el documento exista en SharePoint — no hay una política de "máximo N días/años en el
   índice" independiente de la fuente. Si un documento se archiva pero no se borra de SharePoint,
   su texto (incluyendo nóminas si `index_sensitive_content=true`) permanece indexado indefinidamente.
2. **Backups de la base de datos**: fuera del alcance del código — los backups de PostgreSQL en Azure
   conservan una copia de `conversation_turns`, `audit_events` y las tablas RAG con la misma PII, con
   su propia política de retención de backups (normalmente más larga que la purga aplicativa). Esto
   debe verificarse y documentarse a nivel de infraestructura Azure, no de código.
3. **Diagnósticos en memoria**: al no persistirse a disco/BD, se pierden en cada despliegue/reinicio —
   bueno para minimización de datos, pero significa que no hay evidencia histórica de diagnóstico más
   allá de 24h ni de la vida del proceso.
4. **Verificación de entorno real en Azure**: igual que el hallazgo ya registrado en
   `audit_llm_presidio_voz.md` sección 3, todas las garantías de retención/purga dependen de que el
   proceso tenga `MIA_ENVIRONMENT=production` correctamente configurado — el código por sí solo no
   puede confirmarlo contra la configuración real desplegada.

---

## Resumen para IT / DPO

| Pregunta | Respuesta |
|---|---|
| ¿Presidio evita que el LLM externo vea PII? | ✅ Sí, en el punto de salida, si `PRIVACY_GATEWAY__ENABLED=true` |
| ¿Presidio evita que mIA guarde PII internamente? | ❌ No, y no es su objetivo — el usuario autorizado necesita ver sus propios datos reales |
| ¿Qué guarda PII en claro dentro de mIA? | Historial de conversación (30 días), auditoría (3 años, justificado por LOPDGDD art. 76), texto indexado de CVs/nóminas/documentos (sin TTL propio), adjuntos (24h), informes (por expiración) |
| ¿Hay algún almacén sin ningún control de retención? | Sí, uno pendiente: el texto RAG indexado (ligado solo al ciclo de vida del documento en SharePoint, no a un plazo propio). El de auditoría ya quedó cerrado. |
| ¿Se loguea PII en los logs de aplicación/Azure Monitor? | No, por diseño del código (no se pasa contenido libre a los logs); no verificado a nivel de configuración real de Azure Monitor |

---

## Para estar en orden con RGPD y la ley: qué cubre este documento y qué queda fuera del código

El objetivo final no es solo este hallazgo puntual, sino que mIA esté en orden con RGPD/LOPDGDD de
forma sostenida. Lo que este documento (y el código) puede garantizar es el **ciclo de vida técnico**
de los datos: dónde se guardan, cuánto tiempo y con qué purga — ya cubierto arriba. Hay un segundo
bloque de obligaciones RGPD que **no se resuelven escribiendo código**, porque son decisiones
organizativas/legales o contratos con terceros; se listan aquí para que quede documentado que existen
y quién debe cerrarlas, no para que mIA las resuelva por sí sola:

1. **Derechos del interesado** (acceso, rectificación, supresión, portabilidad, oposición — arts.
   15-22 RGPD). Hoy no existe en el código ningún endpoint ni procedimiento para que un empleado
   ejerza, por ejemplo, el derecho de supresión sobre su propio historial de conversación o sobre los
   `AuditEvent` que lo mencionan antes de que expire la retención automática. **A decidir**: si se
   atiende manualmente (vía RRHH/IT con acceso a BD) o se construye un procedimiento/endpoint. No es
   un cambio de código urgente si el volumen de solicitudes es bajo, pero debe estar documentado como
   procedimiento aunque sea manual.
2. **Transferencias internacionales de datos**. mIA envía texto (ya protegido por Presidio si el
   gateway está activo) a OpenAI/Azure OpenAI (`src/mia/llm/openai_responses.py`) y texto sin filtrar
   de PII general a ElevenLabs (`src/mia/voice/elevenlabs.py:29`, ver hallazgo 2 de
   [audit_llm_presidio_voz.md](audit_llm_presidio_voz.md)). RGPD exige una base para transferencias
   fuera del EEE (SCCs, adequacy decision, o que el servicio se contrate en región UE). **A verificar
   fuera del código**: en qué región está desplegado Azure OpenAI en la configuración real, y qué
   cláusulas contractuales tiene el acuerdo con ElevenLabs y con OpenAI (si se usa el proveedor directo
   en vez de Azure).
3. **Encargados de tratamiento (art. 28 RGPD)**: cada proveedor que procesa datos personales en nombre
   de Sunset Beach Club (OpenAI/Azure OpenAI, ElevenLabs, Microsoft/SharePoint) necesita un contrato de
   encargado de tratamiento (DPA) vigente. Esto es un documento legal/comercial, no una propiedad del
   código.
4. **Base legal del tratamiento de datos de empleados** (art. 6 RGPD, y categorías especiales —datos de
   salud en reconocimientos médicos, art. 9— con base reforzada). El código ya segmenta el acceso a
   contenido médico con un permiso aparte (`Permission.DOCUMENTOS_CONTENIDO_MEDICO`,
   `src/mia/auth/context.py:37-42`), lo que facilita aplicar esa base legal reforzada, pero la base
   legal en sí (relación laboral, interés legítimo, consentimiento, etc.) es una decisión del DPO/RRHH,
   no del código.
5. **Registro de Actividades de Tratamiento (RAT, art. 30 RGPD)**: este documento y
   `audit_llm_presidio_voz.md` dan la base técnica para rellenarlo (qué se trata, con qué finalidad,
   dónde se guarda, cuánto tiempo, a quién se cede), pero el RAT formal es un documento de cumplimiento
   que debe mantener el DPO, no un artefacto de código.
6. **Evaluación de Impacto (DPIA, art. 35 RGPD)**: recomendable dado que mIA trata datos de categoría
   especial (salud, en los reconocimientos médicos) de forma sistemática para una parte del personal.
   No se ha hecho en este trabajo — es un análisis de riesgo, no una tarea de ingeniería.
7. **RAG sin TTL propio** (ya señalado arriba): a diferencia del resto, este es un punto que sí se
   resuelve con código cuando el DPO decida un plazo — queda pendiente de ese mismo tipo de decisión
   que ya se tomó para `AuditEvent`.

En resumen: el ciclo de vida *dentro* de mIA (almacenes, plazos, purgas) ya está, con este cambio,
completo y documentado. Lo que queda para "estar en orden" con la ley en sentido amplio son decisiones
y contratos que corresponden al DPO/dirección de Sunset Beach Club, no a un cambio adicional de código.
