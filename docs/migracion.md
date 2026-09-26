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
| `POST /api/mia/informes/generar` | ⏳ fase 4 |

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
| `MIA_TENANT_ID`, `MIA_CLIENT_ID`, `MIA_CERT_*`, `MIA_SHAREPOINT_HOST`, `MIA_*_URL` | Fase 2 (`MIA_SHAREPOINT__*`) |
| `MIA_OUTLOOK_*` | Fase 4 (`MIA_MAIL__*`) |
| `MIA_WEB_SEARCH_ENABLED`, `MIA_WEATHER_*`, `MIA_DEFAULT_LOCATION` | Asistente general (fase 4) |
| `MIA_LLM_MODE`, `MIA_LLM_RESPONDER`, `MIA_V12_CHAT_URL`, `MIA_LLM_EXPOSE_DEBUG`, `MIA_LLM_RPM_LIMIT` | Eliminadas: ya no aplican |

## Batería de paridad

`tools/extract_parity_corpus.py` extrae las conversaciones registradas por el
sistema anterior. Sobre la base entregada: **1.859 conversaciones, 3.983
preguntas (688 distintas), 485 conversaciones de varios turnos y 1.345
preguntas que dependen del contexto anterior**. Cada dominio migrado debe
superar sus casos antes de sustituir al sistema anterior.
