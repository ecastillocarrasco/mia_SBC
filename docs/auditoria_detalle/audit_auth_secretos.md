# Auditoría de seguridad — mIA (Sunset Beach Club)

Bloque auditado: **autenticación, autorización, gestión de secretos/configuración, aislamiento multiusuario**.
Repositorio: `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA`. Despliegue objetivo: Azure Container Apps / Key Vault / Managed Identity (`infra/main.bicep`), NO IIS on-prem.

Leyenda: ✅ Implementado y verificado en código · 🟡 Parcial/en desarrollo · 🔵 Planificado (decidido, pendiente) · ❌ No existe / brecha.

---

## 1. Autenticación

El sistema tiene **tres modos** seleccionados por `MIA_AUTH__MODE` (`src/mia/settings.py:27-35`, enum `AuthMode`). La fábrica que instancia el proveedor según el modo está en `src/mia/auth/providers.py:170-175` (`build_identity_provider`).

### 1.1 Modo `dev` — ✅ Implementado (con protección de arranque)

- `DevIdentityProvider` (`src/mia/auth/providers.py:36-47`): devuelve siempre la misma identidad fija, construida una vez en `__init__` a partir de `AuthSettings`: `dev_user_id`, `dev_display_name`, `dev_email`, `dev_roles` (`src/mia/settings.py:95-98`, por defecto `dev_roles=["mia.admin"]` → rol con **todos** los permisos, `src/mia/auth/context.py:78`).
- **Protección contra activación accidental en producción**: `src/mia/settings.py:331-334` — validador `_fail_closed_in_production` que lanza `ValueError("MIA_AUTH__MODE=dev no está permitido en producción...")` si `environment == PRODUCTION` y `auth.mode == DEV`. Se ejecuta al construir `Settings()` (arranque de la app), no es una comprobación opcional.
- Test que lo demuestra: `tests/test_auth.py:208-210` (`test_dev_auth_is_forbidden_in_production`).
- **Verificación cruzada con el despliegue real**: `infra/main.bicep:333` fija `MIA_AUTH__MODE` a `easyauth` si `easyAuthClientId` no está vacío, o a `dev` si está vacío; `infra/main.bicep:333` + `infra/main.bicep:96/333` (`isProd` → `MIA_ENVIRONMENT=production`) hacen que, en el entorno `prod` (`infra/main.prod.bicepparam:3`), si alguien desplegara sin rellenar `easyAuthClientId` (línea 10, actualmente placeholder `<client-id-de-la-app-de-entra>`), la combinación `environment=production` + `auth.mode=dev` dispararía el `ValueError` anterior y **la aplicación no arrancaría**. Esto confirma la afirmación del README (`README.md:114-115`: "Producción exige Easy Auth; sin él la aplicación se niega a arrancar") como un efecto real del código, no solo documentación.

**HALLAZGO (informativo, no bloqueante)**: el rol de desarrollo por defecto es `mia.admin`, que mapea a `frozenset(Permission)` — es decir, acceso total (`src/mia/auth/context.py:78`). Esto es razonable para local/test pero conviene remarcarlo en la presentación: cualquier entorno que accidentalmente quede en `environment != production` con `MIA_AUTH__MODE=dev` (p. ej. un entorno "staging" mal etiquetado) expondría acceso total sin login.

### 1.2 Modo `easyauth` — ✅ Implementado

- `EasyAuthIdentityProvider` (`src/mia/auth/providers.py:50-81`): lee la cabecera `x-ms-client-principal` (inyectada por Azure Container Apps/App Service Easy Auth tras validar el login), la decodifica (base64 + JSON) y extrae `oid` (user id), `name`, `preferred_username`/UPN y los claims de rol.
- El propio docstring del módulo (`src/mia/auth/providers.py:4-6`) documenta la premisa de seguridad explícita: la plataforma Azure **elimina** esa cabecera si llega directamente del cliente, por lo que **solo es fiable detrás de Easy Auth real**; el código no tiene forma de verificar eso por sí mismo (confía en la plataforma).
- Tests: `tests/test_auth.py:93-110` (identidad correcta y rechazo si falta la cabecera).
- En `infra/main.bicep:441-458` se define el recurso `Microsoft.App/containerApps/authConfigs` (Easy Auth) condicionado a `easyAuthEnabled`, con `clientId` y `allowedAudiences: ['api://<easyAuthClientId>']` — es la vía de despliegue real configurada hoy en el bicep (no `entra`, ver 1.3).

### 1.3 Modo `entra` — ✅ Implementado en el backend (validación JWT completa) / 🔵 Planificado como vía de despliegue en Azure

- `EntraIdIdentityProvider` (`src/mia/auth/providers.py:84-167`). Verificación concreta de cada elemento exigido por el encargo:
  - **Firma**: `jwt.decode(..., key=key, algorithms=["RS256"], ...)` (`src/mia/auth/providers.py:143-150`), con la clave pública obtenida por `kid` desde el JWKS del tenant (`_signing_key`, `src/mia/auth/providers.py:110-117`, `_refresh_keys`, `src/mia/auth/providers.py:119-130`, usando `jwt.algorithms.RSAAlgorithm.from_jwk`).
  - **Audiencia (`aud`)**: `audience=self._audience` = `settings.entra_client_id` (`src/mia/auth/providers.py:101,147`).
  - **Emisor (`iss`)**: `issuer=self._issuer` = `https://login.microsoftonline.com/<tenant_id>/v2.0` (`src/mia/auth/providers.py:103,148`).
  - **Expiración**: `options={"require": ["exp", "iat", "oid"]}` (`src/mia/auth/providers.py:149`) — `PyJWT` valida `exp`/`iat` automáticamente al decodificar y aquí además se exige que estén presentes.
  - Caché de claves JWKS en memoria con TTL de 24 h y refresco si aparece un `kid` no reconocido (rotación) — `JWKS_TTL_SECONDS = 24*60*60` (`src/mia/auth/providers.py:96,110-113`).
  - Roles: se leen del claim configurable `entra_role_claim` (por defecto `"roles"`, `src/mia/settings.py:103-104`), normalizando el caso de un único rol como string suelto (`src/mia/auth/providers.py:154-156`).
  - Exige en construcción `entra_tenant_id` y `entra_client_id` (`src/mia/auth/providers.py:99-100`), reforzado también en `Settings._fail_closed_in_production` (`src/mia/settings.py:335-336`): si `mode=entra` sin esos dos campos, falla el arranque.
  - **Cobertura de test exhaustiva** (`tests/test_auth.py:148-205`): token válido → permisos correctos; token con App Role real "RRHH" (no el alias de dev); sin cabecera → rechazado; audiencia incorrecta → rechazado; emisor incorrecto → rechazado; token expirado → rechazado; token firmado con clave no presente en el JWKS (key confusion) → rechazado. Es la cobertura más fuerte de los tres modos.
- **Frontend (MSAL)**: `@azure/msal-browser` está en `frontend/package.json:16` (`^3.30.0`). El flujo real está implementado en `frontend/src/core/auth-gate.js`:
  - `ensureAuthenticated()` (líneas 60-103): consulta `GET /api/auth/config` (público) para saber si `requires_login` es verdadero (`mode === entra`); si lo es, inicializa `PublicClientApplication` con `clientId`/`authority` reales devueltos por el backend (líneas 73-82), gestiona `handleRedirectPromise()`, y si no hay cuenta activa lanza `msal.loginRedirect(...)` (línea 101) — **login real**, no un hueco.
  - `getAccessToken()` (líneas 110-124): `acquireTokenSilent` con fallback a `acquireTokenRedirect`, para adjuntar `Authorization: Bearer <token>` en las llamadas a la API (confirmado también por el commit `42c14eb "Adjuntar el token de Entra ID a las llamadas reales del mundo 2D"`).
  - `ensureAuthorized()` (líneas 213-236): tras el login, llama a `GET /api/auth/me` y si `has_access` es `false` sustituye toda la UI por una pantalla de "acceso restringido" (líneas 167-203) — nunca deja montado el chat/avatar sin aviso.
  - El propio fichero documenta (líneas 13-16) que esta puerta es solo UX: el límite de seguridad real es el backend (`mia.api.deps.get_user`/`require()`, 401/403), consistente con lo observado en el punto 2.
  - **Backend `/api/auth/config` y `/api/auth/me`**: `src/mia/api/routes/auth.py:21-52`. `auth/config` es público (sin `UserDep`) y nunca expone secretos (`tenant_id`/`client_id` son públicos, van también dentro del propio token — comentario en líneas 7-8). `auth/me` exige `UserDep` (401 si no autentica) y solo devuelve `has_access: bool(user.permissions)`.
  - Tests del endpoint: `tests/test_auth_config_route.py` (modo dev no exige login; modo entra expone tenant/client id; scope por defecto y explícito; `/api/auth/me` con y sin rol reconocido).
- **Clasificación**: el **backend** de validación de token Entra ID está completamente implementado y probado (✅). El **flujo de login MSAL en el frontend** también está implementado, no es solo un hueco (✅). Lo que sigue en estado 🔵 **planificado/no desplegado** es la vía de **infraestructura**: `infra/main.bicep` solo contempla `dev`/`easyauth` (línea 333: `easyAuthEnabled ? 'easyauth' : 'dev'`); no hay rama en el bicep que fije `MIA_AUTH__MODE=entra` ni que provisione `MIA_AUTH__ENTRA_TENANT_ID`/`MIA_AUTH__ENTRA_CLIENT_ID` como variables de entorno del Container App. Para usar el modo `entra` en Azure con la infraestructura actual, haría falta added manualmente esas variables o extender el bicep.

**HALLAZGO**: ningún proveedor de identidad rellena `UserContext.language` desde una preferencia real (`src/mia/auth/context.py:111-113`, siempre `"es"`) — irrelevante para seguridad, mencionado solo por completitud.

---

## 2. Autorización

### 2.1 Modelo de permisos — ✅ Implementado

- `Permission` (`StrEnum`, `src/mia/auth/context.py:17-49`): 19 permisos granulares por dominio/acción (`EMPLEADOS_LEER`, `NOMINAS_LEER`, `NOMINAS_IMPORTES`, `DOCUMENTOS_LEER`, `DOCUMENTOS_CONTENIDO`, `DOCUMENTOS_CONTENIDO_MEDICO`, `CORREO_ENVIAR`, `ADMINISTRAR`, etc.).
- `ROLE_PERMISSIONS` (`src/mia/auth/context.py:75-95`): mapa rol → conjunto de permisos. Dos familias de roles coexisten explícitamente:
  - Roles de **desarrollo** (`mia.admin`, `mia.rrhh`, `mia.seleccion`, `mia.responsable`) — usados solo por `DevIdentityProvider`, nunca por Entra ID (comentario `src/mia/auth/context.py:76-77`).
  - **App Roles reales de Entra ID** (`Global`, `RRHH`, `RRHH.NoNominas`, `Administracion`, `Legal`) — el comentario (`src/mia/auth/context.py:82-86`) deja constancia de una decisión de seguridad importante: **mIA nunca lee el claim `groups` de Entra ID directamente**, solo `roles` (App Roles asignados explícitamente en el App Registration → Enterprise Application → "Users and groups"), evitando que una persona herede acceso solo por pertenecer a un grupo de Azure AD no pensado para esto.
  - `UserContext.permissions` (`src/mia/auth/context.py:115-120`) es la unión de los permisos de todos los roles que trae el usuario; `has()`/`require()` (líneas 122-128) son el único punto de comprobación.
- **Cobertura de test** de todo el mapa de roles: `tests/test_auth.py:34-90` — incluye una comprobación explícita de que el rol real "RRHH" y el de desarrollo "mia.rrhh" dan **exactamente** el mismo acceso (línea 47-53), y que "Legal"/"Administracion" tienen alcance acotado, no acceso general (líneas 70-83).

### 2.2 Nivel de aplicación: ruta HTTP y a nivel de dato — ✅ Implementado en ambos niveles

- **Nivel de ruta HTTP**: `src/mia/api/deps.py:31-39`, función `require(permission)` — dependencia FastAPI que devuelve 403 si `not user.has(permission)`. Usada p. ej. en `src/mia/api/routes/admin.py:20` (`AdminDep = Depends(require(Permission.ADMINISTRAR))`) para proteger `/api/admin/sources`.
- **Nivel de dato / contenido**, no solo de ruta — tres ejemplos concretos verificados en código:
  1. **Importes de nómina**: `Permission.NOMINAS_IMPORTES` se exige en el registro de la propia herramienta (no en una ruta genérica) — `src/mia/modules/rrhh/nominas/tools.py:425,528,641` (`permission=Permission.NOMINAS_IMPORTES`), y además de forma condicional dentro de la respuesta para decidir si se incluye o no el documento con importes: `src/mia/modules/rrhh/nominas/tools.py:155` (`if ctx.user.has(Permission.NOMINAS_IMPORTES): view["documents"] = [...]`). Reforzado por la regla de negocio explícita `NOM-002` (`src/mia/rules/catalog.py:124-130`: "los importes se leen del PDF en el momento, solo con el permiso nominas:importes, quedan auditados, no se guardan y nunca se dicen en voz alta") — nota: desde `DataSettings.index_sensitive_content` (ver §3), el contenido de nóminas **sí** puede indexarse persistentemente; el propio `Permission.NOMINAS_IMPORTES` (docstring, `src/mia/auth/context.py:26-30`) deja constancia de que esa invariante ya no es absoluta.
  2. **Contenido médico de documentos**: `Permission.DOCUMENTOS_CONTENIDO_MEDICO`, exigido **además** de `DOCUMENTOS_CONTENIDO`, con filtrado de documentos médicos cuando falta: `src/mia/modules/rrhh/documentos/tools.py:116-117` (lista de documentos visibles) y `src/mia/modules/rrhh/documentos/tools.py:510-512` (bloqueo explícito al leer un documento médico concreto sin el permiso, devolviendo `ToolStatus.PERMISSION_DENIED`). Función de clasificación: `is_medical_document_type` (`src/mia/modules/rrhh/documentos/tools.py:65-67`). Validado por rol: "Legal" tiene `DOCUMENTOS_CONTENIDO` pero no `DOCUMENTOS_CONTENIDO_MEDICO` (`src/mia/auth/context.py:94`; test `tests/test_auth.py:70-78`).
  3. **Firmas (regla `FIR-001`)**: `src/mia/rules/catalog.py:168-173` — "sobre firmas solo se responde si existe o no; nunca se lee, muestra ni analiza su contenido". Esta regla está en `in_prompt=True` por defecto, es decir, se la transmite al LLM como instrucción (`rules_for_prompt()`, `src/mia/rules/catalog.py:183-184`); **no he encontrado** (en el tiempo de esta auditoría) una comprobación de código equivalente a los dos casos anteriores que bloquee mecánicamente el contenido de firmas si el LLM ignorase la instrucción — lo marco como:

  **🟡 Parcial** — `FIR-001` depende de que el modelo respete una instrucción de prompt; a diferencia de `NOMINAS_IMPORTES` y `DOCUMENTOS_CONTENIDO_MEDICO`, que tienen una puerta de código que no depende del LLM, no he verificado una puerta de código equivalente para firmas. Si el equipo de IT pregunta específicamente por firmas, decir explícitamente que la salvaguarda ahí es a nivel de prompt/instrucción de negocio, no (verificado) una denegación de permiso en código.

### 2.3 Dominios (`ALL_DOMAINS`) — ✅ Implementado (interruptor de configuración, no de rol)

- `ALL_DOMAINS` (`src/mia/settings.py:159-171`): 11 dominios (`empleados`, `turnos`, `fichajes`, `vacaciones`, `curriculums`, `correo`, `nominas`, `documentos`, `trabajo_temporal`, `analitica`, `informes`).
- `DomainSettings.enabled` (`src/mia/settings.py:174-176`, variable `MIA_DOMAINS__ENABLED`): lista de dominios activos, por defecto todos. El comentario deja claro el propósito: "si uno falla con datos reales se desactiva sin afectar al resto" — es un **interruptor operativo global de configuración**, no un control de acceso por rol/usuario. La restricción por rol/usuario se hace exclusivamente vía `Permission`/`ROLE_PERMISSIONS` (§2.1), no vía `DomainSettings`.

---

## 3. Secretos y configuración

### 3.1 Campos `SecretStr` declarados en `src/mia/settings.py` (nombre y propósito, nunca valor)

| Campo | Línea | Propósito |
|---|---|---|
| `LLMSettings.api_key` | `settings.py:61` | Clave del proveedor LLM (OpenAI / Azure OpenAI). |
| `VoiceSettings.api_key` | `settings.py:83` | Clave del proveedor de voz (ElevenLabs). |
| `SharePointSettings.cert_pfx_base64` | `settings.py:118` | Certificado cliente (PFX) en base64 para la app de SharePoint/Graph, vía Key Vault en Azure. |
| `SharePointSettings.cert_pfx_password` | `settings.py:120` | Contraseña de ese PFX. |
| `DataSettings.pseudonym_key` | `settings.py:138` | Clave HMAC para seudonimizar DNI/NIE; valor por defecto `"solo-para-desarrollo-local"` **bloqueado explícitamente en producción** (ver 3.3). |
| `PrivacyGatewaySettings.vault_key` | `settings.py:208` | Clave Fernet para cifrar el Token Vault del Privacy Gateway. |
| `ObservabilitySettings.applicationinsights_connection_string` | `settings.py:249` | Cadena de conexión de Application Insights (contiene una clave de instrumentación). |

No hay otros campos `SecretStr` en el fichero (grep exhaustivo sobre `src/mia/settings.py`, 7 resultados, todos listados arriba).

### 3.2 Correspondencia con `.env.example` — ✅ Coincide

`.env.example` (raíz del repo) refleja los mismos grupos y deja todos los secretos vacíos: `MIA_LLM__API_KEY=` (línea 12), `MIA_VOICE__API_KEY=` (línea 20), `MIA_SHAREPOINT__CERT_PFX_PASSWORD=` (línea 43), `MIA_DATA__PSEUDONYM_KEY=` (línea 48, con instrucción de generarla con `secrets.token_urlsafe(32)` y advertencia de no cambiarla después). No hay en `.env.example` ningún valor real, solo placeholders vacíos o nombres de variable — correcto.

### 3.3 Camino de los secretos en Azure (`infra/main.bicep`) — ✅ Implementado (Key Vault + Managed Identity)

- Key Vault se crea en `infra/main.bicep:132-145`; la identidad administrada del Container App recibe el rol `Key Vault Secrets User` vía `roleAssignment` (`infra/main.bicep:146-156`) — acceso de solo lectura de secretos, por identidad administrada, sin credenciales embebidas.
- Secretos concretos creados en Key Vault: `secretDatabase` (195), `secretLlm` (201), `secretVoice` (207, condicional a `voiceEnabled`), `secretPseudonym` (213), `secretPfx`/`secretPfxPassword` (219/225, condicionales a `sharepointEnabled`), `secretInsights` (231).
- Esos secretos se exponen al Container App como variables de entorno con `secretRef` apuntando al Key Vault (no como valor plano): `MIA_DATABASE_URL` (335), `MIA_LLM__API_KEY` (339), `MIA_OBSERVABILITY__APPLICATIONINSIGHTS_CONNECTION_STRING` (340), `MIA_VOICE__API_KEY` (345, si `voiceEnabled`), `MIA_DATA__PSEUDONYM_KEY` (347), `MIA_SHAREPOINT__CERT_PFX_BASE64`/`CERT_PFX_PASSWORD` (359-360, si `sharepointEnabled`). El bloque `secrets: allSecrets` (386, 424) asocia cada `secretRef` a su `keyVaultUrl` + la identidad administrada que puede leerlo (`infra/main.bicep:314-363`).
- `infra/main.prod.bicepparam:11-21` y `infra/main.dev.bicepparam:10-20` pasan los valores reales (contraseña de PostgreSQL, API keys de LLM/voz, clave de seudonimización, PFX de SharePoint) mediante `readEnvironmentVariable('MIA_PG_ADMIN_PASSWORD', '')` etc. — es decir, **se leen de variables de entorno del proceso de despliegue (CI/CD), nunca están escritas en el `.bicepparam` committeado**. Confirmado por lectura directa de ambos ficheros: ningún valor de secreto está hardcodeado, solo nombres de variables de entorno del entorno de CI/CD.
- **Arranque forzado ("fail-closed") en producción** — `src/mia/settings.py:331-354` (`_fail_closed_in_production`), además del caso `dev` ya descrito en §1.1:
  - `environment=production` + `pseudonym_key == "solo-para-desarrollo-local"` → `ValueError` (exige que venga de Key Vault) — línea 337-341.
  - `environment=production` + `llm.provider == FAKE` → `ValueError` — línea 342-343.
  - `environment=production` + `privacy_gateway.enabled == False` → `ValueError` (Privacy Gateway obligatorio en producción) — línea 344-345.
  - `environment=production` + `privacy_gateway.fail_open == True` → `ValueError` — línea 346-347.
  - `environment=production` + `privacy_gateway.enabled` + `vault_key` vacío → `ValueError` — línea 348-353.
  - Estas cinco comprobaciones, junto con la de `auth.mode==dev` (§1.1), son el mecanismo real por el que "producción se niega a arrancar" sin la configuración mínima de seguridad — verificado en código, no solo en README.

### 3.4 Histórico de git — ✅ Sin indicios de secretos reales commiteados

- `git log --all --oneline` (50 commits más recientes) inspeccionado: sin mensajes que sugieran filtración de secretos.
- `git log --all -p -- '*.env' '*.env.*'` filtrado por patrones `api[_-]?key|password|secret|token`: los únicos resultados son (a) el propio `.env.example` evolucionando con nombres de variable vacíos (`MIA_LLM__API_KEY=`, `MIA_VOICE__API_KEY=`, `MIA_SHAREPOINT__CERT_PFX_PASSWORD=`, todos sin valor), y (b) un mensaje de commit describiendo que se añadieron tests de `EntraIdIdentityProvider`. Ningún valor real.
- `git log --all --diff-filter=A --name-only` filtrado por `\.env$|\.pfx$|\.pem$|secret`: **sin resultados** — nunca se ha añadido al historial ningún fichero `.env`, `.pfx`, `.pem` ni fichero con "secret" en el nombre.
- **Conclusión**: no encontré hallazgo crítico de secretos reales commiteados en el histórico accesible. (Limitación: esta comprobación cubre lo que `git log --all` expone localmente; no sustituye un escaneo dedicado tipo `gitleaks`/`trufflehog` sobre todo el historial con todas las variantes de patrón, que recomendaría como paso adicional antes de producción.)

---

## 4. Aislamiento multiusuario

### 4.1 Sesión de conversación por usuario — ✅ Implementado y probado

- `ConversationRepository.get_or_create(session_id, user_id)` (`src/mia/data/repositories.py:21-33`): si la sesión ya existe y pertenece a **otro** `user_id`, lanza `SessionNotOwnedError` (línea 25-26) en vez de devolver los datos de otro usuario. Si no existe, crea una sesión nueva asociada a `user_id` (línea 28).
- Ese error se traduce en un **403 HTTP real** en el flujo de chat — confirmado por el test end-to-end `tests/test_auth.py:213-218` (`test_session_belongs_to_its_owner`): crea una sesión con un usuario, cambia la identidad activa a `"otra-persona"` y reutiliza el mismo `session_id` → la API responde `403`.
- El contexto de conversación por turno (`session.state`) se copia a partir de la fila de sesión en BD, ya filtrada por `user_id` — `src/mia/conversation/engine.py:354-357` (`session = await repo.get_or_create(session_id, user.user_id)` seguido de `dict(session.state or {})`) y se persiste de vuelta a esa misma sesión (`src/mia/conversation/engine.py:605`). No hay una caché global en memoria compartida entre usuarios para el estado conversacional: el estado vive en la fila `ConversationSession` de PostgreSQL, indexada por `session_id`, y el acceso a esa fila está controlado por `user_id` como se describe arriba.
- Las herramientas de dominio reciben el `UserContext` autenticado de la petición (`ctx.user`, visto repetidamente en `nominas/tools.py`, `documentos/tools.py`, etc.) y filtran permisos/contenido por ese usuario en cada llamada — no hay un `UserContext` global ni cacheado entre peticiones de distintos usuarios (cada petición HTTP resuelve su propio `UserContext` vía `Depends(get_user)`, `src/mia/api/deps.py:21-26`).

### 4.2 Exclusión de cuentas de prueba de los datos reales — ✅ Implementado y probado

- `DataSettings.exclude_name_patterns` (`src/mia/settings.py:142-144`, por defecto `["^test", "^tezt"]`): expresiones regulares sobre el nombre (normalizado, sin tildes/mayúsculas) de cuentas que no son personas reales.
- Aplicado en la sincronización de datos: `src/mia/ingestion/sync/factory.py:50` pasa `exclude_name_patterns=settings.data.exclude_name_patterns` a `SyncRunner` (`src/mia/ingestion/sync/runner.py:74-76`, que compila los patrones con `re.compile`).
- Test que lo demuestra con datos simulados: `tests/test_sync.py:224-228` — crea empleados de prueba con nombres que matchean `^test`/`^tezt` junto a empleados reales, ejecuta `SyncRunner.run(...)` con esos patrones de exclusión, y comenta explícitamente "carga completa: las cuentas de prueba no entran" (línea 227).

**Nota de alcance**: esto excluye cuentas de prueba de la sincronización de datos de negocio (RRHH) hacia la base de datos operativa de mIA; es distinto del aislamiento de sesión/usuario conversacional (§4.1), que es un mecanismo separado. Ambos están verificados independientemente.

---

## 5. Tests relacionados — ✅ Cobertura real, no solo nominal

Ficheros de test relevantes encontrados y su alcance (ya referenciados en detalle en las secciones anteriores):

- `tests/test_auth.py` — el más completo: mapeo rol→permiso para los 4 roles de desarrollo y los 5 App Roles reales de Entra ID (incluida la paridad exacta "RRHH" == "mia.rrhh" y el alcance acotado de "Legal"/"Administracion"); `EasyAuthIdentityProvider` (identidad correcta / cabecera ausente); `EntraIdIdentityProvider` con 7 escenarios (válido, App Role real, sin cabecera, audiencia incorrecta, emisor incorrecto, expirado, clave no reconocida/key-confusion); bloqueo de `dev` en producción; aislamiento de sesión entre usuarios (403).
- `tests/test_auth_config_route.py` — contrato público de `/api/auth/config` (modo dev no exige login; modo entra expone tenant/client/scope correctos; endpoint público sin token) y de `/api/auth/me` (acceso concedido vs. rol no reconocido → `has_access=false` sin ser un 403).
- `tests/test_sync.py` (línea ~224-228) — exclusión de cuentas de prueba (`exclude_name_patterns`) en la sincronización real de empleados.
- `tests/test_sharepoint_auth.py` — existe (no detallado en profundidad en esta pasada; por su nombre cubre la autenticación de aplicación, certificado, contra SharePoint/Graph — un flujo de *backend-a-backend*, distinto de la autenticación de usuarios finales que es el objeto de este informe).

No he encontrado un test dedicado explícitamente a `FIR-001` (bloqueo de contenido de firmas) a nivel de código — coherente con la clasificación 🟡 de ese punto en §2.2.3.

---

## Resumen de hallazgos (HALLAZGO)

1. **🟡 FIR-001 (firmas) depende de instrucción de prompt, no de una puerta de código verificada** — a diferencia de `NOMINAS_IMPORTES` y `DOCUMENTOS_CONTENIDO_MEDICO`, que sí tienen una comprobación de permiso en código que no depende del LLM.
2. **El modo `entra` (validación JWT propia, con MSAL real en frontend) no está conectado en `infra/main.bicep`** — el bicep actual solo contempla `easyauth`/`dev`. Si el cliente espera "login con Entra ID" vía el flujo MSAL ya implementado, hace falta extender la infraestructura (variables de entorno `MIA_AUTH__MODE=entra`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`) o aclarar que la vía de producción prevista es Easy Auth integrado de Azure, no el validador JWT propio.
3. **No se encontraron secretos reales commiteados** en el histórico de git inspeccionado (acotado); se recomienda un escaneo dedicado (gitleaks/trufflehog) como verificación adicional antes de producción, no solo el `grep` acotado de esta auditoría.
4. **Rol de desarrollo por defecto = acceso total** (`mia.admin`) — sin impacto si `MIA_AUTH__MODE=dev` permanece bloqueado en producción como está verificado, pero a tener en cuenta si se crean entornos intermedios mal etiquetados como no-producción.

## Totales de clasificación

- ✅ Implementado: **14** (dev mode + protección producción; easyauth; entra backend JWT completo; entra frontend MSAL; `/api/auth/config` + `/api/auth/me`; modelo de permisos y roles; autorización a nivel de ruta; autorización a nivel de dato — nóminas; autorización a nivel de dato — documentos médicos; dominios/`ALL_DOMAINS`; secretos `SecretStr` + `.env.example`; secretos en Azure vía Key Vault/Managed Identity; fail-closed en producción; aislamiento de sesión por usuario; exclusión de cuentas de prueba; cobertura de tests de auth/permisos).
- 🟡 Parcial: **1** (FIR-001, salvaguarda de firmas solo a nivel de prompt).
- 🔵 Planificado: **1** (modo `entra` como vía de despliegue en `infra/main.bicep`; el código ya existe y está probado).
- ❌ No existe / brecha: **0** (no se encontró ninguna ausencia total de control en el bloque auditado; el histórico de git tampoco mostró secretos filtrados).
