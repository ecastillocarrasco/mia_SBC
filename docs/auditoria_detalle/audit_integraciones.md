# Auditoría de integraciones externas — mIA (Sunset Beach Club)

Alcance: TODAS las conexiones salientes/entrantes con sistemas externos al proceso Python de mIA.
Enfoque: protocolo, autenticación, permisos, timeouts/reintentos, manejo de fallos, logging, TLS.
El contenido semántico que viaja (prompts, PII) lo cubre otro auditor en paralelo; aquí solo el
"cómo" de la conexión salvo excepciones puntuales señaladas como contexto.

Repositorio: `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA`. Todas las citas son `fichero:línea` reales,
leídas directamente del código, no inferidas.

---

## 1. SharePoint Online (Microsoft Graph REST, vía Entra ID + certificado) — ✅ Implementado

**Sentido:** saliente. **Protocolo:** HTTPS/REST (puerto 443), `https://<host>.sharepoint.com/_api/web/...`
(SharePoint REST clásico, no Graph `/v1.0/sites`).

**Endpoint genérico:** `src/mia/connectors/sharepoint/client.py:73` — `{site}/_api/web/lists/getbytitle('{title}')`.
Sitio RRHH y sitio "PortalCorporativo" (dos sitios, dos `SharePointClient`, ver
`src/mia/ingestion/sync/runner.py:71,79`: `site_clients: dict[str, SharePointClient]`).

**Autenticación:** certificado de aplicación vía MSAL, flujo client-credentials (OAuth2 "client
credentials with certificate"), NO API key ni secreto de cliente.
- `src/mia/connectors/sharepoint/auth.py:73-80` — `msal.ConfidentialClientApplication` con
  `client_credential={"thumbprint": ..., "private_key": ...}`.
- Scope: `src/mia/connectors/sharepoint/auth.py:65` — `f"https://{settings.host}/.default"` (permisos de
  aplicación concedidos en Entra ID; el código no limita el scope a algo más estrecho).
- Credencial (certificado PFX/PEM) leída de: variable de entorno / fichero, nunca hardcodeada —
  `src/mia/connectors/sharepoint/auth.py:39-57` (`cert_pem_path`, `cert_pfx_base64`, `cert_pfx_path`,
  contraseña en `SecretStr`). En Azure, el PFX llega vía Key Vault como secreto inyectado en el
  Container App: `infra/main.bicep:219-228` (`Microsoft.KeyVault/vaults/secrets`, `sharepoint-pfx`,
  `sharepoint-pfx-password`) y `infra/main.bicep:322-325` (referencia `keyVaultUrl` + identidad
  administrada para leerlo). Huella/tenant/client ID viajan como variables de entorno normales
  (`infra/main.bicep:354-358`), no como secreto (son públicos, no credenciales).

**Permisos solicitados:** ⚠️ **no están declarados en ningún fichero del repositorio** (ni en
`infra/main.bicep`, ni en `docs/`, ni en comentarios de código). El scope pedido es
`.default` (`auth.py:65`), que simplemente reclama **todos** los permisos de aplicación que el
administrador de Entra ID haya concedido en el registro de la app — el repo no fija ni documenta
cuáles son (`Sites.Selected` vs `Sites.Read.All`/`Sites.ReadWrite.All`). **HALLAZGO:** el principio de
mínimo privilegio no es verificable desde el código; solo se puede auditar mirando el registro de
la aplicación en el tenant de Entra ID, fuera de este repositorio. Recomendación para IT: confirmar
en el Portal de Azure que el permiso de aplicación concedido es `Sites.Selected` (acotado al sitio
RRHH + portal) y no `Sites.Read.All`/`Sites.ReadWrite.All` (todo el tenant).

**Timeouts / reintentos / paginación / throttling:**
- Config en `src/mia/settings.py:126-129` — `timeout_seconds: float = 30.0`, `page_size: int = 2000`,
  `max_retries: int = 5`, `concurrency: int = 4`.
- Uso real: `src/mia/connectors/sharepoint/client.py:67` — `httpx.Timeout(timeout_seconds, connect=10.0)`;
  `:66` — `asyncio.Semaphore(concurrency)` limita peticiones simultáneas (control de concurrencia,
  no exactamente un circuit breaker).
- Reintentos con backoff exponencial + jitter y respeto de `Retry-After` en 429/500/502/503/504:
  `client.py:106-107` y `:149-154` (`_sleep`, `delay = backoff_base * 2**attempt + jitter`, tope 60s).
- Renovación de token ante 401 (una vez, `refreshed` flag): `client.py:103-105,130-132`.
- Paginación completa por `odata.nextLink` sin límite de vista, con detección de bucles de
  paginación repetida: `client.py:168-179`.
- Incremental por `CurrentChangeToken`/`GetChanges` (altas/bajas/cambios sin reindexar todo):
  `client.py:227-269`; expiración del token manejada explícitamente
  (`ChangeTokenExpiredError`, `client.py:34-35`) y recuperada con sync completo automático en
  `src/mia/ingestion/sync/runner.py:126-131`.
- No hay *circuit breaker* real (no se "abre el circuito" tras fallos repetidos); solo reintento
  acotado por petición. Para un trabajo de sincronización en background esto es razonable
  (el motivo: `runner.py:8` "Un error en un elemento no detiene la sincronización").

**Si el servicio cae:** la sincronización de UNA fuente falla de forma aislada, se registra y
continúa con las demás (`runner.py:134-137`, `except Exception: report.status="error"; log.exception(...)`),
sin tirar el proceso. Las herramientas conversacionales que consultan datos ya sincronizados en
PostgreSQL siguen funcionando con los últimos datos conocidos (lectura desacoplada de la
disponibilidad de SharePoint en el momento de la conversación). El descubrimiento de calendarios
dinámicos tolera fallos de red por comprobación individual: `src/mia/ingestion/discovery.py:41-43`.

**Logging:** `structlog`, redacción automática de claves sensibles (`api_key`, `authorization`,
`password`, `secret`, `token`) en `src/mia/observability/logging.py:14,24-28`; el logger de `httpx`
se baja a `WARNING` explícitamente para no volcar URLs completas (que pueden llevar IDs/filtros) en
INFO — `logging.py:33-34`. Eventos de sync (`sync.finished`, `sync.failed`, `sync.item_failed`,
`calendar_discovery.*`) no incluyen el token Bearer ni el PFX. Sí se loguea `source.key`, `item_id`
y mensajes de error truncados a 200-1000 caracteres (`runner.py:136,245`) — aceptable, son
identificadores internos, no PII en claro (los campos sensibles ya se seudonimizan antes de
persistir, ver abajo).

**TLS:** no se encontró `verify=False` ni desactivación de verificación de certificado en ningún
cliente HTTP del repositorio (búsqueda explícita en todo `src/`, sin resultados). `httpx.AsyncClient`
usa la verificación TLS por defecto (certifi).

**Datos reales accedidos — listas SharePoint confirmadas** (`src/mia/ingestion/definitions.py`):
empleados (`EmpleadosCorporativos`, L74-87, incluye `DocIdentidad` seudonimizado), departamentos
(L89-100), turnos (`Turnos`, L102-117, incluye `DNIEmpleado` seudonimizado), vacaciones y saldo
(L119-146), currículums (`CurriculosVitae`/`CVDocs`, L149-168), **nóminas** (`Nominas`, L170-183,
biblioteca con carpetas por identidad), **documentos firmados** (`DocumentosFirmadosV2`, L185-194),
trabajo temporal (empresas/trabajadores/boletines/tarifas/comunicaciones, L196-267), altas de
empleados con DNI (`AltaEmpleados`, L234-243), catálogos de turnos/plantillas/comentarios
(L269-332) y calendarios por departamento/año descubiertos dinámicamente (L334-382). Esto confirma
contra el código (no solo contra el README) que SÍ se leen nóminas, documentos firmados, CVs y
trabajo temporal, tal y como se esperaba investigar.

**Seudonimización antes de persistir:** `runner.py:215-230` (`_sanitize`) aplica
`Pseudonymizer`/`mask_ids`/`pseudonymize_path` a los campos marcados `sensitive_fields` y a las
rutas de bibliotecas con `identity_folders=True` ANTES de insertar en PostgreSQL — es decir, el DNI
no llega a la base en claro. Esto es un control relevante para IT aunque pertenezca más al bloque
de contenido que al de conexión.

---

## 2. Correo (Microsoft Graph, buzón propio) — ✅ Implementado

**Sentido:** saliente (lectura/búsqueda/borradores) y, condicionalmente, saliente real (envío).
**Protocolo:** HTTPS/REST, Microsoft Graph v1.0 — `src/mia/connectors/graph.py:13` (`GRAPH =
"https://graph.microsoft.com/v1.0"`).

**Cliente real:** `src/mia/connectors/graph.py` (`GraphClient`), construido en
`src/mia/api/services.py:22-30` (`build_graph_client`) — **misma aplicación y mismo certificado que
SharePoint** (`CertificateTokenProvider(settings.sharepoint, scope="https://graph.microsoft.com/.default")`,
`services.py:30`). **HALLAZGO (credencial compartida):** un único certificado de aplicación habilita
tanto el acceso al sitio SharePoint de RRHH como, potencialmente, Graph Mail sobre buzones — si ese
certificado se compromete, el radio de impacto cubre ambos sistemas a la vez.

**Permisos solicitados:** `Mail.Read`/`Mail.ReadWrite`/`Mail.Send` se conceden desde Entra y el cliente pide `.default`; el repositorio no declara exactamente qué app roles están consentidos.

**Límite de seguridad pendiente de comprobar en el tenant:** el backend resuelve el buzón de la sesión (`src/mia/modules/correo/mailbox.py`) y las herramientas no reciben otro buzón como argumento. La credencial de aplicación, sin embargo, puede tener alcance tenant-wide si Entra/Exchange no lo limitan. No hay evidencia en el repositorio del ámbito efectivo. IT debe revisar permisos generales en Entra y Exchange RBAC for Applications, y probar el usuario propio y otro usuario. Para aislamiento efectivo por petición, evaluar permisos delegados.

**Resolución de buzón:** `src/mia/modules/correo/mailbox.py:16-19` — nunca viene como parámetro
del modelo/usuario, siempre resuelto server-side (mitiga que el LLM o el usuario apunten a otro
buzón, pero no mitiga el alcance del permiso de aplicación en sí).

**Timeouts/reintentos:** `src/mia/connectors/graph.py:26-34` — `timeout_seconds: float = 30.0` (en
`src/mia/settings.py` no hay un `GraphSettings` propio; reutiliza los valores que le pasan);
reintentos ante 429/5xx con `Retry-After` o backoff `2**attempt` tope 30s (`graph.py:58-61`),
renovación de token ante 401 una vez (`graph.py:55-57`), sin paginación explícita de `$skip`/
`@odata.nextLink` implementada en el cliente genérico (cada herramienta pagina con `$top` fijo, ver
p.ej. `src/mia/modules/correo/tools.py:140-142`).

**Si el servicio cae:** cada herramienta de correo captura `GraphError` y devuelve
`ToolResult(ToolStatus.SOURCE_UNAVAILABLE, "No he podido ...")` al usuario en vez de una excepción
sin control — confirmado en 7 puntos de `src/mia/modules/correo/tools.py:143-144,183-184,255-256,
300-301,378-379,411-412,453-454,482-483`. Nota menor: el mensaje incluye `{exc}` (cuerpo HTTP de Graph
truncado a 300 caracteres, `graph.py:63`) tal cual al usuario final de la conversación — no es un
secreto, pero es detalle interno de la API que no se filtra ni genera.

**Envío real:** controlado por flag explícito `MIA_MAIL__SEND_ENABLED` (por defecto `false`,
`.env.example:59`) + confirmación conversacional adicional (comentario en el mismo fichero); el envío
efectivo es una llamada POST a `.../sendMail` o `.../messages/{id}/send` vía el mismo `GraphClient`
(`src/mia/modules/correo/tools.py:377`).

**TLS / logging:** igual que SharePoint (mismo `httpx.AsyncClient`, sin `verify=False`; mismo
logger con redacción de secretos).

---

## 3. Fichajes / Conectia (A3 Wolters Kluwer) — 🔵 Planificado (NO hay conector en red)

**No existe ninguna conexión de red implementada hacia Conectia/A3.** Confirmado leyendo el código,
no solo la documentación:

- `src/mia/connectors/a3/__init__.py:1-10` — docstring explícito: *"Conectia (A3 de Wolters Kluwer):
  fichajes, **sin implementar todavía**. ... A fecha de esta reestructuración no hay documentación de
  su API disponible, así que este módulo es solo la interfaz de enganche"*. Define únicamente una
  clase abstracta `TimeClockConnector(ABC)` con un método `fichajes()` que `raise NotImplementedError`
  (`a3/__init__.py:30-40`) y advierte: *"No importar este módulo desde `modules/rrhh` todavía"*
  (`a3/__init__.py:9`) — y en efecto no hay ningún `import` de `mia.connectors.a3` fuera del propio
  paquete (verificado por búsqueda en `src/mia`).
- Lo que SÍ existe y funciona hoy es un **importador manual de ficheros Excel** exportados a mano
  desde Conectia (sin ninguna llamada de red): `src/mia/modules/rrhh/fichajes/importer.py:1-9` —
  *"Importación manual del Excel de fichajes de Conectia (A3 Wolters Kluwer) — solo entornos de
  prueba"*. Lee `.xlsx` de un directorio local (`importer.py:168`, `directory.glob("*.xlsx")`) con
  `openpyxl.load_workbook` (`importer.py:139`) y hace *matching* de nombres contra la base de
  empleados ya sincronizada. **Esto no es una integración con un sistema externo**: no abre ningún
  socket, no hay endpoint, no hay autenticación — es procesamiento de un fichero que un humano ha
  descargado y colocado manualmente. Se incluye aquí solo para dejar constancia de que NO sustituye
  al conector real pendiente.

**Clasificación:** 🔵 Planificado (el conector real `TimeClockConnector`) + fuera de alcance de "conexión
con sistema externo" para el importador Excel (es E/S de fichero local). No se detectan credenciales,
URLs ni SDK de Conectia/A3 en `pyproject.toml` ni en el código.

---

## 4. Búsqueda web (vía proveedor LLM) — ✅ Implementado (saliente indirecto)

**Sentido:** saliente, pero **no directo**: mIA no hace peticiones HTTP a dominios web arbitrarios;
delega la búsqueda en la herramienta nativa del proveedor LLM (OpenAI Responses API).

- Config: `src/mia/settings.py:76-78` — `web_search: bool = True` por defecto
  (`MIA_LLM__WEB_SEARCH=true` en `.env.example:73`), con nota *"si el proveedor no la admite, se
  desactiva sola"*.
- Implementación: `src/mia/llm/openai_responses.py:138-141` — se añade `{"type": "web_search"}` (o
  `"web_search_preview"` como *fallback* de compatibilidad) a la lista `tools` del payload enviado a
  `/responses`. Si el proveedor rechaza el nombre de la herramienta con HTTP 400, se degrada
  automáticamente al siguiente nombre y, si ninguno funciona, se desactiva sola en caliente
  (`openai_responses.py:209-216`, evento de log `llm.web_search_changed`).
- Las URLs devueltas se filtran a esquemas `http(s)` y se les quita el parámetro de tracking
  `utm_source=openai` (`openai_responses.py:54-62`), pero **la llamada de red real a los sitios web
  citados la hace la infraestructura del proveedor LLM, no el proceso de mIA**. El egress de red de
  mIA para esta función se limita al endpoint del proveedor LLM (`api.openai.com` o el recurso Azure
  OpenAI configurado), no a los dominios resultado de la búsqueda.

**HALLAZGO (dominio no documentado como tal):** aunque el tráfico real a terceros lo hace OpenAI, el
contenido de esos resultados (títulos/URLs arbitrarias de internet) entra en la conversación del
usuario sin ninguna lista blanca/negra de dominios en el código de mIA — es responsabilidad
delegada íntegramente al proveedor LLM, sin control adicional en mIA. No es necesariamente un fallo,
pero IT debe saber que esta función puede traer contenido de cualquier dominio público de internet.

---

## 5. Azure AI Search / Azure ML — 🔵 Planificado / ❌ No existe código que los invoque

**Azure AI Search:** `src/mia/knowledge/__init__.py:1-37` — docstring *"Conocimiento documental de
la empresa (RAG) — vacío por ahora, preparado para Azure AI Search"*. Solo define un *dataclass*
`KnowledgeDocument` y una clase abstracta `KnowledgeIndex(ABC)` con `search()` que lanza
`NotImplementedError` (`knowledge/__init__.py:33-36`). Ningún cliente HTTP, SDK ni credencial de
Azure AI Search en el repositorio ni en `pyproject.toml`.

**Azure ML:** `src/mia/analytics/__init__.py:48-57` — clase abstracta `PredictiveModel(ABC)` con
`predict()` que lanza `NotImplementedError`; comentario explícito (`analytics/__init__.py:30-34`)
de que no se implementa "hasta completar la evaluación legal" de alto riesgo según el Reglamento
Europeo de IA (2024/1689). Sin SDK de Azure ML en dependencias.

**Ni `infra/main.bicep` ni `pyproject.toml` referencian Azure AI Search o Azure ML** (verificado por
búsqueda textual) — confirmando que es exclusivamente infraestructura/contrato de código, sin
despliegue de recursos asociado. Clasificación estricta: 🔵 Planificado (hay un contrato de
interfaz pensado para ello) pero ❌ No existe ninguna conexión real.

---

## 6. Base de datos — PostgreSQL vía asyncpg/SQLAlchemy (+ pgvector) — ✅ Implementado (interno)

**Sentido:** saliente desde el proceso de mIA hacia PostgreSQL. **Protocolo:** TCP/PostgreSQL wire
protocol (puerto 5432 por defecto, ver `docker-compose.yml:11-12` `"5432:5432"`), vía `asyncpg` +
`SQLAlchemy async`.

- `src/mia/data/db.py:16` — pool `pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800`
  (reconexión ante conexiones muertas, sin *circuit breaker* explícito pero con `pool_pre_ping`
  que evita usar una conexión caída).
- Cadena de conexión `MIA_DATABASE_URL` (`.env.example:8`): `postgresql+asyncpg://...` — no se ve en
  el código ningún parámetro `sslmode`/`ssl=` explícito en `db.py`; la seguridad del canal depende de
  lo que se añada a la cadena de conexión en el entorno real (Azure Database for PostgreSQL exige TLS
  por defecto del lado servidor, pero el cliente no lo fuerza explícitamente en código). **Nota
  menor:** no hay `ssl=True`/`sslmode=require` hardcodeado como salvaguarda si alguien construye una
  URL sin TLS.
- `ping()` (`db.py:30-36`) traga cualquier excepción y devuelve `False` — usado para *health checks*,
  no para la ruta normal de negocio (ahí los errores sí propagan, ver `session()` en `db.py:20-28`
  que hace `rollback()` y re-lanza).
- No se profundiza en el esquema por alcance de esta auditoría (pgvector es uso interno de
  embeddings ya calculados, sin conexión externa adicional).

---

## 7. Otras llamadas salientes detectadas (LLM y Voz — "cómo", no contenido)

Cubiertas en detalle por el otro auditor en su contenido; aquí solo el mecanismo de conexión:

- **LLM (OpenAI / Azure OpenAI):** `src/mia/llm/openai_responses.py` — HTTPS a `base_url` configurable
  (`settings.py:68-69`, por defecto `https://api.openai.com/v1`, o recurso Azure si
  `MIA_LLM__PROVIDER=azure_openai`). Auth: `Authorization: Bearer <api_key>` o cabecera `api-key` en
  modo Azure (`openai_responses.py:142`), clave en `SecretStr` desde `MIA_LLM__API_KEY`
  (`.env.example:12`, vacía por defecto en local). Timeout `45.0`s + `turn_budget_seconds=120.0`
  (`settings.py:70,73`). Reintentos con backoff en 429/5xx y ante timeout, tope 3 intentos
  (`openai_responses.py:124-125,198-227`). Fallos propagan como `LLMError` y el motor conversacional
  responde con una frase de error genérica de la persona en vez de un *stack trace*
  (`src/mia/conversation/engine.py:495-499`). Todas las llamadas pasan obligatoriamente por
  `PrivacyGateway`, el único punto de salida hacia el proveedor (`src/mia/privacy_gateway/gateway.py:1-11`);
  su protección de PII está controlada por `MIA_PRIVACY_GATEWAY__ENABLED` (por defecto `False` en
  `src/mia/settings.py:200`, no presente en `.env.example`) — detalle de contenido que corresponde
  al otro auditor, se cita aquí solo porque forma parte de la arquitectura de la conexión saliente.
- **Voz (ElevenLabs):** `src/mia/voice/elevenlabs.py` — HTTPS a `base_url` (`settings.py:87`, por
  defecto `https://api.elevenlabs.io/v1`), auth por API key en cabecera custom `xi-api-key`
  (`elevenlabs.py:23`), timeout `20.0`s (`settings.py:88`), streaming de audio (sin reintento
  explícito más allá de la excepción `httpx.HTTPError` → `VoiceError`, `elevenlabs.py:43-44`). Si
  cae, la ruta HTTP de voz responde `503 Service Unavailable` al frontend
  (`src/mia/api/routes/voice.py:21-22`), no una excepción sin control.

---

## 8. Autenticación entrante — Microsoft Entra ID (JWT/JWKS) — ✅ Implementado

Único flujo de entrada desde un sistema externo (aparte de las peticiones HTTP normales del
frontend) que vale la pena documentar: validación de tokens de acceso de Entra ID.

- `src/mia/auth/providers.py:84-163` (`EntraIdIdentityProvider`): valida firma RS256 contra JWKS del
  tenant (`providers.py:104`, `GET https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys`),
  comprueba emisor, audiencia y expiración (`providers.py:143-150`). Claves cacheadas 24h
  (`providers.py:96`) y refrescadas si aparece un `kid` no reconocido (rotación) o por TTL
  (`providers.py:110-113`).
- **Timeout:** `httpx.AsyncClient(timeout=10)` (`providers.py:105`). **Sin reintentos** ante fallo de
  red al refrescar JWKS (`providers.py:119-124`, un único intento, `except httpx.HTTPError →
  AuthenticationError`) — si Microsoft tiene un fallo transitorio justo cuando hay que rotar claves,
  el login falla sin reintento automático (mitigado por la caché de 24h: solo afecta en el momento
  exacto de rotación). **Nota menor, no crítica.**
- Nunca se expone el secreto: el endpoint público `/api/auth/config`
  (`src/mia/api/routes/auth.py:21-37`) solo devuelve `tenant_id`/`client_id` (identificadores
  públicos, van dentro del propio token) y el `scope`, explícitamente comentado como "nunca
  devuelve secretos" (`auth.py:7-8`).

---

## 9. Webhooks / SMTP directo / SDKs de terceros no listados arriba

Búsqueda explícita en todo `src/mia` de `smtp`, `webhook`, Azure Search/ML SDKs: **sin resultados**
de código real (solo las menciones de Azure AI Search/Azure ML ya cubiertas en el punto 5, que son
contratos vacíos). No hay servidor de webhooks entrante ni envío SMTP directo (todo el correo sale
vía Microsoft Graph, punto 2) — ❌ No existe.

---

## Resumen de clasificación

| Integración | Sentido | Estado |
|---|---|---|
| SharePoint Online (REST + cert. Entra ID) | Saliente | ✅ Implementado |
| Microsoft Graph — Correo | Saliente | ✅ Implementado |
| Conectia/A3 (fichajes, API real) | Saliente | 🔵 Planificado (solo interfaz abstracta) |
| Importación manual Excel de fichajes | — (fichero local) | ✅ Implementado, pero no es conexión externa |
| Búsqueda web (vía proveedor LLM) | Saliente (indirecto) | ✅ Implementado |
| Azure AI Search | Saliente | 🔵 Planificado / ❌ sin código que lo invoque |
| Azure ML (predictivo) | Saliente | 🔵 Planificado / ❌ sin código que lo invoque |
| PostgreSQL (asyncpg) | Saliente (interno) | ✅ Implementado |
| LLM (OpenAI/Azure OpenAI) | Saliente | ✅ Implementado (detalle de contenido: otro auditor) |
| Voz (ElevenLabs) | Saliente | ✅ Implementado (detalle de contenido: otro auditor) |
| Entra ID JWKS (validación de token entrante) | Entrante (validación) / saliente (JWKS) | ✅ Implementado |
| Webhooks entrantes | Entrante | ❌ No existe |
| SMTP directo | Saliente | ❌ No existe |

## Hallazgos priorizados

1. **CRÍTICO — Graph Mail, alcance efectivo pendiente de revisar.** mIA apunta al buzón autenticado,
   pero los permisos app-only pueden permitir el acceso técnico a otros buzones. Revisar Entra y Exchange;
   el código no demuestra cómo está limitado el principal en el tenant.
2. **ALTO — Permisos de Graph/SharePoint no declarados como código.** El scope usado es siempre
   `.default` (`auth.py:65`, `services.py:30`), que depende enteramente de lo que un administrador
   concedió manualmente en el registro de la aplicación en Entra ID; no hay ninguna lista de
   permisos de aplicación exacta en `infra/main.bicep` ni en `docs/`. Imposible auditar el principio
   de mínimo privilegio solo desde el código — requiere revisión directa en el tenant.
3. **MEDIO — Credencial única compartida entre SharePoint y Correo.** Mismo certificado de
   aplicación para dos superficies de datos distintas (sitio RRHH + buzón de correo); un compromiso
   del certificado afecta a ambas integraciones simultáneamente.

Puntos positivos a destacar: sin `verify=False` en ningún cliente HTTP (TLS siempre validado),
redacción de secretos en logs, seudonimización de DNI/NIE antes de persistir, manejo de errores sin
excepciones sin control hacia el usuario final, reintentos con backoff y respeto de `Retry-After` en
todos los clientes REST, Conectia/A3 correctamente marcado como no implementado en el propio código
(sin falsos positivos de integración).
