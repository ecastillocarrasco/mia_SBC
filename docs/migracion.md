# Migración desde el sistema anterior

## Qué sustituye a qué

| Sistema anterior | mIA |
|---|---|
| `mia_legacy_v10_42.py` (23.000 líneas, 141 rutas) | Dominios en `src/mia/domains/` (fases 2–4) |
| `mia_core/*_v12.py`, `bootstrap*.py` (capas v11/v12) | Eliminado; sin equivalente |
| `semantic_v12.py` (parser de regex) | LLM con herramientas tipadas |
| `mIA_LLM_CHAT_V4.py` + `mia_llm_v4/` (segundo proceso) | `conversation/` en el mismo proceso |
| Dos estados de conversación (cliente + SQLite) | Uno, en el servidor (`conversation_sessions`) |
| ~20 cachés con TTL propio | Capa de datos sincronizada (fase 2) |
| 4 ficheros SQLite | PostgreSQL |
| `hotfix/`, `*.bak*`, `mia_core/backup/` | Historia en git |
| Scripts QA PowerShell contra el servidor | `pytest` + batería de paridad |

## Rutas que usa el frontend actual

Se mantienen como alias en `api/routes/compat.py` hasta rehacer el frontend:

| Ruta | Estado |
|---|---|
| `POST /api/mia/v4/chat` | ✅ alias |
| `POST /api/mia/chat` | ✅ alias |
| `POST /api/mia/chat/stream` (NDJSON) | ✅ alias |
| `POST /api/mia/voice` | ✅ alias (ahora en streaming) |
| `GET /api/version`, `GET /api/mia/v4/health` | ✅ alias |
| `GET /mia`, `/mia-assets/*` | ✅ opcional, desde la carpeta anterior |
| `POST /api/mia/informes/generar` | Sustituida por la herramienta `generar_informe` y `GET /api/reports/{id}` |

Rutas nuevas: `POST /api/chat`, `POST /api/chat/stream` (SSE), `POST /api/voice/stream`,
`GET /health/live`, `GET /health/ready`.

Las rutas de diagnóstico del monolito (`/api/sharepoint/lista/<titulo>/items` y
similares) **no se migran**: exponían cualquier lista sin autenticación.

## Variables de entorno

| Anterior | Nueva |
|---|---|
| `MIA_API_OPENAI_KEY` | `MIA_LLM__API_KEY` |
| `MIA_LLM_MODEL` | `MIA_LLM__MODEL` |
| `MIA_LLM_PROVIDER` | `MIA_LLM__PROVIDER` (`openai`, `azure_openai`, `fake`) |
| `MIA_LLM_TIMEOUT_SECONDS` | `MIA_LLM__TIMEOUT_SECONDS` |
| `MIA_VOICE_ELEVEN_LABS_API_KEY` | `MIA_VOICE__API_KEY` (+ `MIA_VOICE__PROVIDER=elevenlabs`) |
| `MIA_VOICE_ELEVEN_LABS_VOICE_ID` | `MIA_VOICE__VOICE_ID` |
| `MIA_VOICE_ELEVEN_LABS_MODEL_ID` | `MIA_VOICE__MODEL_ID` |
| `MIA_DEFAULT_TIMEZONE` | `MIA_TIMEZONE` |
| `MIA_LLM_PORT` | `MIA_COMPAT_PORT` |
| `MIA_TENANT_ID` | `MIA_SHAREPOINT__TENANT_ID` |
| `MIA_CLIENT_ID` | `MIA_SHAREPOINT__CLIENT_ID` |
| `MIA_CERT_THUMBPRINT` | `MIA_SHAREPOINT__CERT_THUMBPRINT` |
| `MIA_CERT_PFX_PATH`, `MIA_CERT_PFX_PASSWORD` | `MIA_SHAREPOINT__CERT_PFX_PATH`, `MIA_SHAREPOINT__CERT_PFX_PASSWORD` |
| `MIA_SHAREPOINT_HOST` | `MIA_SHAREPOINT__HOST` |
| `MIA_RRHH_URL` | `MIA_SHAREPOINT__RRHH_SITE_URL` |
| `MIA_SITE_URL` (portal) | No se usa: todas las fuentes actuales están en el sitio de RRHH |
| — | `MIA_DATA__PSEUDONYM_KEY` (nueva: seudonimización de DNI/NIE) |
| `MIA_OUTLOOK_MAILBOX` | `MIA_MAIL__MAILBOX` |
| `MIA_OUTLOOK_SEND_ENABLED` | `MIA_MAIL__SEND_ENABLED` (por defecto `false`) |
| `MIA_OUTLOOK_DRAFT_WRITE_ENABLED` | `MIA_MAIL__DRAFTS_ENABLED` |
| `MIA_OUTLOOK_MAX_MESSAGES` | `MIA_MAIL__MAX_MESSAGES` |
| `MIA_OUTLOOK_*_MAILBOX`, `MIA_OUTLOOK_SEND_TEST_RECIPIENT` | Eliminadas: un único buzón |
| `MIA_NOMINAS_PERMITIR_CONTENIDO`, `MIA_DOCUMENTOS_FIRMADOS_PERMITIR_CONTENIDO` | Eliminadas: el contenido no se lee (NOM-002, FIR-001) |
| `MIA_WEB_SEARCH_ENABLED`, `MIA_WEATHER_*`, `MIA_DEFAULT_LOCATION` | Asistente general (fase 4) |
| `MIA_LLM_MODE`, `MIA_LLM_RESPONDER`, `MIA_V12_CHAT_URL`, `MIA_LLM_EXPOSE_DEBUG`, `MIA_LLM_RPM_LIMIT` | Eliminadas: ya no aplican |

## Batería de paridad

`tools/extract_parity_corpus.py` extrae las conversaciones registradas por el
sistema anterior. Sobre la base entregada: **1.859 conversaciones, 3.983
preguntas (688 distintas), 485 conversaciones de varios turnos y 1.345
preguntas que dependen del contexto anterior**. Cada dominio migrado debe
superar sus casos antes de sustituir al sistema anterior.
