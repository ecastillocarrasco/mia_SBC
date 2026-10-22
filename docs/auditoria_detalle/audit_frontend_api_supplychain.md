# Auditoría de seguridad — mIA (Sunset Beach Club)
## Bloque: Frontend · API/Backend (seguridad de aplicación) · Cadena de suministro

Repositorio: `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA`
Fecha de auditoría: 2026-10-20
Metodología: inspección estática del código fuente real (sin ejecución), con cita exacta fichero:línea.

Leyenda: ✅ Implementado · 🟡 Parcial · 🔵 Planificado · ❌ No existe / brecha

---

## 1. Rutas API y validación de entrada

### 1.1 Rutas principales confirmadas (montaje real en `src/mia/main.py:101-115`)

| Router | Prefijo / rutas | Fichero |
|---|---|---|
| `health` | `GET /health/live`, `GET /health/ready` | `src/mia/api/routes/health.py:13,19` |
| `auth` | `GET /api/auth/config`, `GET /api/auth/me` | `src/mia/api/routes/auth.py:21,40` |
| `chat` | `POST /api/chat`, `POST /api/chat/stream` (SSE) | `src/mia/api/routes/chat.py:36,43` |
| `voice` | `POST /api/voice/stream` | `src/mia/api/routes/voice.py:35` |
| `reports`, `jobs`, `documents`, `admin`, `diagnostics`, `mail`, `attachments` | varios | `src/mia/api/routes/*.py` |
| `compat` | `POST /api/mia/chat`, `/api/mia/chat/stream`, `/api/mia/voice`, `/api/mia/informes/generar`, `GET /api/version`, `GET /api/mia/v4/health` — alias legacy, `include_in_schema=False` | `src/mia/api/routes/compat.py:12,41` |
| `attachments` | `POST /api/adjuntos/upload`, `GET/DELETE /api/adjuntos/{id}` | `src/mia/api/routes/attachments.py:12,30,60,80` |

### 1.2 Validación con Pydantic — 🟡 Parcial

✅ Las rutas principales orientadas al usuario final usan modelos Pydantic con límites explícitos de longitud:
- `ChatRequest` — `message` (1–4000 car.), `session_id` (≤32), `attachment_ids` (≤10 elementos) — `src/mia/api/schemas.py:6-9`.
- `VoiceRequest` — `text` (1–2000 car.) — `src/mia/api/schemas.py:12-13`.
- `LegacyChatRequest` / `LegacyVoiceRequest` (alias de compatibilidad) también acotan longitud — `src/mia/api/routes/compat.py:44-47,65-67`.

**HALLAZGO (bajo-medio):** dos rutas autenticadas aceptan el body como `dict[str, Any]` sin esquema Pydantic, es decir sin límites de longitud/tipo declarativos:
- `mail_action` — `async def mail_action(action: str, body: dict[str, Any], ...)` — `src/mia/api/routes/mail.py:17`.
- `legacy_report` — `async def legacy_report(body: dict[str, Any], ...)` — `src/mia/api/routes/compat.py:168`.

Ambas exigen autenticación (`UserDep`) y `mail_action` valida el nombre de la acción contra un allowlist (`src/mia/api/mail_actions.py`, `ACTIONS`), por lo que no es una inyección directa, pero rompe la consistencia de validación de entrada del resto de la API y no hay tope de tamaño de payload declarado para estos dos endpoints.

**HALLAZGO (medio):** no existe límite global de tamaño de cuerpo de petición a nivel de aplicación/ASGI (no hay `max_upload_size`, comprobación de `Content-Length`, ni middleware equivalente) — confirmado por ausencia total de estos términos en `src/mia/`. Esto afecta a *todas* las rutas, no solo a adjuntos: un cliente puede enviar un body JSON arbitrariamente grande antes de que Pydantic lo rechace por longitud de campo, consumiendo CPU/memoria en el parseo.

### 1.3 Límites de tamaño de adjuntos — ✅ / 🟡

- `AttachmentSettings`: `max_files=10`, `max_file_mb=25`, `retention_hours=24`, `temp_path=data/attachments` — `src/mia/settings.py:218-228`.
- El límite de tamaño por fichero **sí se aplica**: `validate(content, safe_name, declared_mime, self._max_bytes)` en `src/mia/attachments/service.py:85`, comprobado en `src/mia/attachments/validation.py:108-110`.
- **HALLAZGO (medio):** `max_files` (tope de 10 adjuntos) se almacena en el servicio (`self._max_files = max_files`, `src/mia/attachments/service.py:55`) **pero nunca se usa** — no hay ninguna comprobación en `upload()` (`src/mia/attachments/service.py:64-143`) que cuente los adjuntos existentes del usuario antes de aceptar uno nuevo. Es un control configurado pero no aplicado (config "muerta").
- **HALLAZGO (bajo-medio):** la ruta de subida lee todo el fichero en memoria antes de validar el tamaño — `content = await file.read()` en `src/mia/api/routes/attachments.py:44`, y solo después se valida contra `max_file_mb` dentro de `svc.upload(...)`. Al no existir además un límite global de body (ver 1.2), un cliente podría forzar al proceso a leer un payload muy grande antes del rechazo (vector de agotamiento de memoria/IO).

### 1.4 Manejo de errores sin fuga de información interna — ✅

- El handler genérico de excepciones no expone trazas ni rutas de fichero al cliente: solo registra en log (`log.exception(...)`) y devuelve un mensaje genérico + `request_id` — `src/mia/api/errors.py:20-30`.
- El error de propiedad de sesión (`SessionNotOwnedError`) también devuelve un mensaje acotado — `src/mia/api/errors.py:13-18`.
- Los errores de voz devuelven mensajes de negocio, no detalles del proveedor — `src/mia/api/routes/voice.py:19-22`.

---

## 2. CORS — 🟡 Parcial (seguro por defecto, sin guardarraíl explícito para producción)

- Configuración: `cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])` — `src/mia/settings.py:306`. **Por defecto solo localhost**, correcto para desarrollo.
- Aplicación: `app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET","POST","DELETE"], allow_headers=["Content-Type","Authorization","X-Request-ID"])` — `src/mia/main.py:94-99`. No se pasa `allow_credentials=True`, por lo que no hay combinación peligrosa de credenciales + orígenes abiertos.
- **HALLAZGO (medio):** a diferencia de otras variables de entorno, `cors_origins` **no tiene ningún validador "fail-closed" en producción**. El validador `_fail_closed_in_production` (`src/mia/settings.py:331-354`) bloquea `AuthMode.DEV`, la clave de seudonimización por defecto, el proveedor LLM `fake` y el Privacy Gateway desactivado/fail-open — pero no comprueba que `cors_origins` en `Environment.PRODUCTION` excluya `"*"` o dominios no corporativos. Si un desplegador fija `MIA_CORS_ORIGINS=["*"]` (o lo deja vacío/mal interpretado) en producción, nada en el código lo impide: el riesgo es que cualquier origen web pueda invocar la API desde el navegador de un usuario ya autenticado (si en el futuro se añadiera `allow_credentials=True`, el riesgo escalaría a robo de sesión vía CSRF/XHR cross-origin).

---

## 3. Rate limiting — ❌ No existe (HALLAZGO ALTO)

Búsqueda exhaustiva de "rate", "limit", "throttl" y de librerías conocidas (`slowapi`, `fastapi-limiter`) en `src/mia/` y en `pyproject.toml`: la única coincidencia es un comentario sobre evitar *throttling* de Microsoft Graph/SharePoint en el conector saliente (`src/mia/connectors/sharepoint/client.py:4`), que es tráfico saliente, no protección de las rutas entrantes.

**No hay ninguna limitación de tasa por usuario, IP o sesión en ninguna ruta HTTP**, incluidas:
- `POST /api/chat/stream` (`src/mia/api/routes/chat.py:43`) — invoca al LLM, coste directo por llamada.
- `POST /api/voice/stream` (`src/mia/api/routes/voice.py:35`) — invoca a ElevenLabs, coste directo por llamada.
- `POST /api/adjuntos/upload` (`src/mia/api/routes/attachments.py:30`) — coste de CPU/IO/almacenamiento.

**HALLAZGO — severidad ALTA.** Un usuario autenticado (o, si el proveedor de identidad fallara, cualquier cliente) puede generar un volumen ilimitado de peticiones a los endpoints de LLM/voz, con impacto directo en coste (facturación de OpenAI/ElevenLabs) y en disponibilidad (saturación del proceso/DB). No existe mitigación a nivel de aplicación; si existe alguna en la capa de infraestructura (API Management, Front Door, Container Apps), no es visible desde este repositorio y debe confirmarse con el equipo de plataforma.

---

## 4. Cabeceras de seguridad HTTP — 🟡 Parcial (HALLAZGO MEDIO: faltan CSP y HSTS)

`RequestContextMiddleware` añade de forma incondicional tres cabeceras — `src/mia/api/middleware.py:13-17,28-29`:

```python
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "SAMEORIGIN",
}
```//applied via response.headers.setdefault(...)

✅ Presentes: `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`.

❌ **Ausentes (confirmado — ninguna coincidencia en todo `src/mia/` para estos términos):**
- `Content-Security-Policy` — sin ella, un XSS en el frontend (p. ej. en los scripts clásicos del mundo 2D, ver sección 6) tiene vía libre para exfiltrar el token de MSAL guardado en `sessionStorage`.
- `Strict-Transport-Security` (HSTS) — sin ella, un navegador que acceda alguna vez por HTTP no queda protegido frente a *downgrade*/*stripping* SSL. (Mitigable en el reverse proxy/App Service de Azure si allí se añade — debe confirmarse, no está en este repositorio.)
- `Permissions-Policy` / `Cross-Origin-Opener-Policy` — tampoco presentes.

**Severidad: media.** El riesgo real depende de si Azure Front Door / App Service añade HSTS por delante (habitual en despliegues Azure estándar) — debe verificarse en la configuración de infraestructura, no visible en este repo.

---

## 5. Adjuntos — validación de tipo, antivirus y retención

### 5.1 Validación de tipo de fichero — ✅ Implementado (robusto)

`src/mia/attachments/validation.py`:
- Allowlist de extensiones (`ALLOWED_EXTENSIONS`, líneas 30-34) y de MIME (`ALLOWED_MIME`, líneas 11-28).
- Denylist explícita de extensiones peligrosas (`.exe .bat .cmd .sh .ps1 .vbs .js .jar .com .scr .msi .dll .py .rb .php`) — líneas 46-49.
- Detección de tipo real por *magic bytes* (no se fía del `Content-Type` declarado por el cliente) — `_detect_mime`, líneas 62-73, usada en `validate()` línea 123.
- Sanitización de nombre de fichero contra *path traversal* (`PurePosixPath(...).name`, filtro de caracteres, límite de 200 car.) — `sanitize_filename`, líneas 86-95.
- Protección de *path traversal* también en el backend de almacenamiento: `LocalStorage._resolve` comprueba que la ruta resuelta siga dentro de `self._base` — `src/mia/attachments/storage.py:29-34`.

### 5.2 Escaneo antivirus / malware — ❌ No existe (confirmado)

Sin coincidencias de "antivirus", "malware", "clamav" ni "virus" como control real en `src/mia/attachments/` (las únicas coincidencias eran de otro dominio, PDF). **No hay ningún escaneo de contenido malicioso** sobre los ficheros subidos — la única defensa es la validación de tipo por extensión/MIME/magic-bytes de la sección 5.1, que no detecta payloads maliciosos embebidos en un PDF/DOCX/XLSX válidos (p. ej. macros, exploits de parser). **Severidad: media** — mitigado parcialmente por el hecho de que los ficheros no se re-exponen públicamente ni se ejecutan, solo se parsean para extraer texto/imágenes para el LLM.

### 5.3 Almacenamiento temporal y retención — ✅ Implementado

- Almacenamiento local en `data/attachments` (`AttachmentSettings.temp_path`, `src/mia/settings.py:224`), aislado por `user_id/attachment_id/raw` (`attachment_path`, `src/mia/attachments/storage.py:55-58`).
- Retención configurable (`retention_hours=24` por defecto, `src/mia/settings.py:223`) con expiración activa: `expire_old()` borra ficheros vencidos (`src/mia/attachments/service.py:192-209`) y se ejecuta en bucle cada hora si `attachments.enabled` (`start_cleanup`, `src/mia/main.py:61-63`).
- Control de propiedad: `get_for_user` rechaza el acceso si `r.user_id != user_id` (con log de intento no autorizado) — `src/mia/attachments/service.py:153-161`.
- **Nota:** el almacenamiento es local al proceso (`LocalStorage`, comentario explícito "para dev/test") — en un despliegue con varias réplicas sin disco compartido, esto podría producir inconsistencias de acceso a adjuntos entre instancias; no es un hallazgo de seguridad pero sí operativo a validar con IT.

---

## 6. Frontend — contrato con la API y manejo de sesión

### 6.1 Transporte del token — ✅ Correcto (Bearer header, no cookies)

- `frontend/src/core/client.js:62-67`: `_authHeaders()` obtiene el token vía `getAccessToken()` y lo añade como `Authorization: Bearer <token>` en `send()` (línea 76) y `speak()` (línea 120). Nunca se usan cookies para el token — evita exposición a CSRF clásico.
- `frontend/src/core/auth-gate.js:110-124`: `getAccessToken()` usa `msal.acquireTokenSilent(...)`; si falla, reintenta con `acquireTokenRedirect` (no expone el token en la URL).
- Caché de MSAL: `cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false }` — `frontend/src/core/auth-gate.js:80`. `sessionStorage` evita persistencia entre sesiones de navegador/pestañas distintas, pero sigue siendo legible por cualquier script en caso de XSS (de ahí la relevancia de la falta de CSP, sección 4).
- Backend valida el JWT de Entra ID de forma completa: firma RS256 contra JWKS del tenant, `audience`, `issuer`, expiración y claims obligatorios (`exp`, `iat`, `oid`) — `src/mia/auth/providers.py:142-152`.

### 6.2 Config pública de autenticación — ✅ Sin secretos expuestos

`GET /api/auth/config` (`src/mia/api/routes/auth.py:21-37`) solo devuelve `tenant_id`, `client_id` y `scope` — identificadores públicos de Entra ID, no credenciales (así lo documenta el propio docstring, líneas 6-8 del fichero). Confirmado: no hay client secret ni API key en la respuesta.

### 6.3 Nada expuesto indebidamente en el cliente — ✅ Confirmado por búsqueda

Búsqueda de patrones de credenciales (`api.openai.com`, `elevenlabs.io`, `sk-...`, `apikey`, `api_key`, `xi-api-key`) en todo `frontend/src/*.js` — **sin coincidencias**. No existe `.env`/`.env.local` en `frontend/` (solo `.env.example` está versionado). `frontend/src/core/identity-v45.js:53` lee `import.meta.env.VITE_MIA_DEV_FIRST_NAME` — es un nombre de usuario de desarrollo, no un secreto.

### 6.4 Confirmación de carpetas "2D"/"2d"

Ambas carpetas existen simultáneamente: `frontend/src/worlds/2D/` y `frontend/src/worlds/2d/` (confirmado por listado de directorio). La **vigente en producción** es `2D` (mayúsculas): `frontend/vite.config.js:11-16` referencia explícitamente `src/worlds/2D/mia-2d.js`, `mia-enhance.js` y sus `.css` como "scripts clásicos" que el plugin de build copia a `dist/` porque Vite no puede empaquetar scripts no-módulo. El comentario del propio `vite.config.js` (líneas 6-11) indica que son scripts legacy sin `type="module"`, cargados mediante globales (`window.ask`, `window.MIA_UI_BUILD`) — superficie más difícil de auditar por XSS que el resto del frontend (módulos ES6 modernos), y motivo adicional por el que la ausencia de CSP (sección 4) importa más en este mundo que en 3D/holograma.

---

## 7. Seguridad de la cadena de suministro / dependencias

### 7.1 Backend Python — 🟡 Parcial / ❌ sin lockfile real (HALLAZGO MEDIO-ALTO)

- `pyproject.toml` fija **rangos de versión**, no versiones exactas, p. ej. `"fastapi>=0.115,<1"`, `"pydantic>=2.8,<3"`, `"httpx>=0.27,<1"` (todo el bloque `dependencies`, líneas 9-32 de `pyproject.toml`).
- **No existe lockfile real**: no hay `uv.lock`, `poetry.lock` ni `requirements.txt` generado en el repositorio (confirmado: `ls uv.lock requirements*.txt` no devuelve nada en la raíz). El pipeline de CI instala con `pip install -e ".[dev]"` (`.github/workflows/ci.yml` — jobs `calidad` y `postgres`), lo que **resuelve las versiones en el momento de cada ejecución** dentro de los rangos declarados, sin garantía de reproducibilidad entre builds ni protección frente a que una dependencia transitiva publique una versión comprometida dentro del rango permitido.
- **Severidad: media-alta** para un entorno corporativo: sin lockfile, dos despliegues del mismo commit pueden traer árboles de dependencias distintos, y un ataque de tipo *dependency confusion* o una versión maliciosa publicada dentro del rango `>=X,<Y` se instalaría automáticamente sin revisión.

### 7.2 Frontend npm — ✅ Lockfile presente, correctamente usado en CI

- `frontend/package.json` usa rangos con caret (`"@azure/msal-browser": "^3.30.0"`, `"three": "^0.185.1"`, `"vite": "^8.2.2"`).
- `frontend/package-lock.json` **sí existe** y fija versiones resueltas exactas.
- El workflow de CI usa `npm ci` (`.github/workflows/ci.yml`, job `frontend`), que **instala estrictamente desde el lockfile** y falla si `package.json`/`package-lock.json` están desincronizados — esto es correcto y reproducible. ✅

### 7.3 Escaneo de vulnerabilidades / Dependabot — ❌ No existe (HALLAZGO ALTO)

- No existe `.github/dependabot.yml` ni ningún fichero equivalente (búsqueda `find . -iname "dependabot*"` sin resultados).
- `.github/workflows/ci.yml` (contenido íntegro revisado) tiene 4 jobs — `calidad` (ruff, mypy, pytest), `postgres` (migraciones Alembic), `frontend` (`npm ci && npm run build`), `imagen` (`docker build`) — **ninguno ejecuta** `pip-audit`, `npm audit`, `safety`, `trivy` ni ningún escáner de vulnerabilidades de dependencias.
- **Severidad: alta.** No hay ningún mecanismo automatizado — ni humano programado — que alerte de CVEs conocidas en las decenas de dependencias Python (incluidas librerías con superficie de ataque relevante: `cryptography`, `pyjwt`, `httpx`, `pillow`, `presidio-analyzer`) ni en las dependencias npm/transitivas del frontend.

### 7.4 Resumen de hallazgos de cadena de suministro

| Control | Estado |
|---|---|
| Versionado backend (rangos vs exacto) | 🟡 Rangos, sin pin exacto |
| Lockfile backend | ❌ No existe |
| Versionado frontend | 🟡 Rangos (caret) |
| Lockfile frontend | ✅ Existe y se usa en CI (`npm ci`) |
| Dependabot / bot de actualización | ❌ No existe |
| Escaneo de vulnerabilidades (pip-audit/npm audit/trivy) en CI | ❌ No existe |

---

## 8. OWASP Top 10 LLM — superficie expuesta por el frontend

**✅ Correcto — todo el tráfico hacia proveedores de IA pasa por el backend (patrón proxy), confirmado:**

- El frontend solo llama a `${apiBase}/api/chat/stream` y `${apiBase}/api/voice/stream`, ambos endpoints propios del backend — `frontend/src/core/client.js:74,118`.
- No hay ninguna llamada `fetch`/`XMLHttpRequest` desde `frontend/src/` hacia `api.openai.com` ni `elevenlabs.io` (búsqueda exhaustiva sin coincidencias, sección 6.3).
- Las claves reales (`LLMSettings.api_key`, `VoiceSettings.api_key`) están tipadas como `SecretStr` y solo existen en `src/mia/settings.py:61,83`, leídas del lado servidor (variables de entorno / Key Vault en Azure según el docstring del módulo, `src/mia/settings.py:1-7`) — nunca se transmiten al cliente.
- Esto **no sería un hallazgo CRÍTICO** porque no se encontró evidencia de clave expuesta; se confirma como diseño correcto (mitiga OWASP LLM `Insecure Plugin/Model Access` por exposición de credenciales en cliente).

---

## Resumen de clasificación

| Punto | Estado |
|---|---|
| 1. Rutas + validación Pydantic | 🟡 Parcial (2 rutas sin esquema; sin límite global de body) |
| 1. Límites de adjuntos | 🟡 Parcial (`max_file_mb` aplicado; `max_files` no aplicado) |
| 1. Manejo de errores sin fuga interna | ✅ Implementado |
| 2. CORS | 🟡 Parcial (seguro por defecto; sin guardarraíl de producción) |
| 3. Rate limiting | ❌ No existe — **ALTO** |
| 4. Cabeceras de seguridad HTTP | 🟡 Parcial — falta CSP y HSTS — **MEDIO** |
| 5. Validación de tipo de adjuntos | ✅ Implementado (robusto) |
| 5. Antivirus/malware en adjuntos | ❌ No existe — **MEDIO** |
| 5. Retención y aislamiento de adjuntos | ✅ Implementado |
| 6. Token vía Authorization Bearer, no cookies | ✅ Correcto |
| 6. Sin secretos expuestos en frontend | ✅ Correcto |
| 7. Lockfile Python | ❌ No existe — **MEDIO-ALTO** |
| 7. Lockfile npm | ✅ Existe y se usa (`npm ci`) |
| 7. Dependabot / escaneo de vulnerabilidades | ❌ No existe — **ALTO** |
| 8. Frontend sin llamadas directas a LLM/voz con clave expuesta | ✅ Correcto |

**Conteo global: ✅ 9 · 🟡 4 · 🔵 0 · ❌ 4**

---

## Hallazgos por severidad

**ALTA**
1. Sin rate limiting en ningún endpoint (§3) — riesgo de abuso de coste (LLM/voz) y denegación de servicio.
2. Sin Dependabot ni escaneo automatizado de vulnerabilidades (pip-audit/npm audit) en CI (§7.3) — CVEs en dependencias (incluidas `cryptography`, `pyjwt`, `pillow`) no se detectan automáticamente.

**MEDIA**
3. Sin lockfile real para Python — build no reproducible, riesgo de dependencia comprometida dentro de rango (§7.1).
4. Faltan `Content-Security-Policy` y `Strict-Transport-Security` (§4) — relevante sobre todo para el mundo 2D legacy (scripts clásicos, §6.4).
5. Sin escaneo antivirus/malware de adjuntos subidos (§5.2).
6. `cors_origins` sin guardarraíl "fail-closed" en producción, a diferencia de otras variables críticas (§2).
7. `max_files` de adjuntos configurado pero no aplicado en el código (§1.3).
8. Lectura completa en memoria del adjunto antes de validar tamaño; sin límite global de tamaño de body (§1.2, §1.3).

**BAJA**
9. Dos rutas (`mail_action`, `legacy_report`) sin esquema Pydantic, body como `dict[str, Any]` (§1.2).
