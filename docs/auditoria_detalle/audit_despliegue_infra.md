# Auditoría de seguridad — Despliegue, infraestructura, procesos y observabilidad

Repositorio: `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA`
Alcance: exclusivamente el bloque "despliegue / infraestructura / procesos-servicios en ejecución / observabilidad". Toda afirmación cita fichero:línea exacto verificado en el repositorio en el momento de la auditoría.

Leyenda: ✅ Implementado · 🟡 Parcial · 🔵 Planificado · ❌ No existe / brecha · **HALLAZGO** = riesgo de seguridad u operación a comunicar a IT.

---

## 1. Prerrequisitos

- **Python**: `requires-python = ">=3.12"` — `pyproject.toml:10`. Build con `FROM python:3.12-slim` — `Dockerfile:2` y `Dockerfile:9`. ✅
- **Node** (frontend): CI usa `node-version: "22"` — `.github/workflows/ci.yml:58`, con `cache-dependency-path: frontend/package-lock.json` (`ci.yml:60`), build vía `npm ci` + `npm run build` (`ci.yml:61-62`). El Dockerfile de producción **no construye el frontend** (no hay `COPY frontend` ni `npm` en `Dockerfile`); el frontend no forma parte de la imagen de la API. 🟡
- **Dependencias Python relevantes para seguridad/PII** — `pyproject.toml:11-37`: `pypdfium2>=4` (línea 33), `pillow>=10` (línea 34), `presidio-analyzer>=2.2,<3` / `presidio-anonymizer>=2.2,<3` (líneas 36-37), `spacy>=3.8,<4` (línea 38).
- **Modelo spaCy `es_core_news_lg`**: configurado como valor por defecto en `src/mia/settings.py:212` (`spacy_model: str = "es_core_news_lg"`) y usado en `src/mia/privacy_gateway/presidio_engine.py:48-69` (carga perezosa, solo al primer análisis real, comentario explícito en líneas 1-6: *"el modelo spaCy en español (~500 MB) solo se carga la primera vez... así arrancar la app... no paga ese coste"*).
  **❌ HALLAZGO — el modelo NO se descarga en ningún paso de build/instalación automatizado.** No es una dependencia de `pip` declarada en `pyproject.toml` (los modelos de spaCy se instalan aparte, normalmente con `python -m spacy download es_core_news_lg` o un wheel directo) y **no hay ningún `RUN`/paso en `Dockerfile` que lo instale** (ver bloque 2). La única referencia a que está "instalado" es documental, en `PRIVACY_GATEWAY_PROGRESS.md:40` ("sí, autorizado e instalado... ~568 MB") — un documento de progreso, no un paso reproducible de CI/CD. Si la imagen Docker descrita en el `Dockerfile` se construye tal cual y se despliega, la primera vez que el *Privacy Gateway* intente analizar texto real, `presidio_engine.py:77-80` capturará la excepción de carga del modelo y lanzará `UnsafeContentBlockedError` — es decir, **fallará cerrado** (no hay fuga de datos), pero la funcionalidad de pseudonimización quedará inoperativa en un despliegue "de libro" hasta que alguien instale el modelo manualmente dentro del contenedor. Dado que `settings.py:344-345` **prohíbe explícitamente desactivar el Privacy Gateway en producción** (`MIA_PRIVACY_GATEWAY__ENABLED=false no está permitido en producción`), este hueco de instalación es crítico para la fiabilidad del arranque en producción, aunque no para la seguridad (el fallo es seguro, no silencioso).
- No se detectan otras dependencias de sistema nativas explícitas (ffmpeg, fuentes TTF, etc.) en `Dockerfile` ni `pyproject.toml`; `pypdfium2`, `pillow`, `reportlab`, `python-pptx`, `python-docx`, `openpyxl` se instalan como wheels manylinux estándar vía `pip wheel` (`Dockerfile:7`), sin pasos de compilación adicionales visibles.

---

## 2. Dockerfile (`Dockerfile`, raíz del repo)

Dos etapas (multi-stage build):

- **Etapa `build`** (`Dockerfile:2-7`): `FROM python:3.12-slim AS build`. Copia `pyproject.toml`, `README.md` y `src` (`Dockerfile:5-6`) y ejecuta `pip wheel --wheel-dir /wheels ".[azure]"` (`Dockerfile:7`) — construye un wheel del propio paquete `mia` con el extra `azure` (OpenTelemetry/Application Insights, `pyproject.toml:44-45`).
- **Etapa `runtime`** (`Dockerfile:9-22`): `FROM python:3.12-slim AS runtime` (línea 9). Crea un usuario no-root: `RUN useradd --create-home --uid 10001 mia` (línea 12) e **invoca `USER mia` antes del arranque** (línea 18). ✅ **El contenedor NO corre como root en ejecución** (solo la instalación de paquetes con `pip install` en la línea 15 corre como root, antes del `USER mia`, lo cual es el patrón correcto).
- Copia solo los wheels generados (línea 14), instala con `pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels` (línea 15), y copia `alembic.ini` y `migrations` (líneas 16-17) — **no copia el código fuente `src/` a la imagen final**, solo el paquete ya empaquetado. Correcto desde el punto de vista de minimizar superficie.
- **Puerto expuesto**: `EXPOSE 8000` (línea 19), coherente con `MIA_PORT=8000` (línea 11) y con el *targetPort* de Container Apps (`infra/main.bicep:381`). Un único puerto expuesto — ✅ sin exposición innecesaria.
- **Healthcheck**: definido en `Dockerfile:20-21`, `HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "...urlopen('http://127.0.0.1:8000/health/live'...)"`. ✅ Existe y usa el endpoint real `/health/live` (`src/mia/api/routes/health.py:13-16`, liveness simple sin dependencias) y hay un segundo endpoint `/health/ready` (`health.py:19-27`) que sí comprueba la base de datos (`services.db.ping()`, línea 22) y detecta migraciones pendientes (`schema_problem`, línea 23) — este segundo endpoint se usa como *readiness probe* en Container Apps (`infra/main.bicep:397`), no en el `HEALTHCHECK` de Docker.
- **Comando de arranque**: `Dockerfile:22` → `CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory mia.main:create_app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]`.
  - 🟡 **Nota de seguridad menor**: `--forwarded-allow-ips='*'` confía en las cabeceras `X-Forwarded-*` de **cualquier** origen que llegue al proceso. En Azure Container Apps el tráfico externo pasa siempre por el *ingress* gestionado (no es accesible saltarse ese proxy desde fuera), por lo que el riesgo práctico es bajo en ese entorno, pero es una configuración permisiva que vale la pena señalar si el contenedor se expusiera alguna vez detrás de otro proxy no controlado o directamente a Internet.
  - Las migraciones (`alembic upgrade head`) se ejecutan **en cada arranque del contenedor**, antes de levantar uvicorn — no hay un paso de migración separado del arranque de la aplicación.
- **Versionado de dependencias Python**: `pip wheel --wheel-dir /wheels ".[azure]"` (línea 7) resuelve las dependencias **en el momento del build** contra los rangos declarados en `pyproject.toml:11-37` (p. ej. `"fastapi>=0.115,<1"`, `"httpx>=0.27,<1"`, `"spacy>=3.8,<4"`). 🟡 **HALLAZGO — las versiones NO están fijadas (pinned) a una resolución exacta**: no hay `requirements.txt`/`uv.lock`/`poetry.lock` ni `pip freeze` congelado que se use en el build; cada build de imagen puede resolver una versión de parche/minor distinta dentro de esos rangos, lo que puede introducir builds no reproducibles bit a bit (aunque los rangos con `<` acotan el riesgo de saltos mayores). No se encontró ningún lockfile en la raíz del repo ni en `infra/`.

---

## 3. docker-compose.yml (raíz del repo)

Dos servicios, pensado explícitamente para desarrollo local (comentario `docker-compose.yml:1-3`: *"Entorno local: PostgreSQL + mIA"*):

- **`db`** (`docker-compose.yml:5-18`): `image: postgres:18-alpine` (línea 6). **❌ HALLAZGO — credenciales hardcodeadas en texto plano**: `POSTGRES_USER: mia` / `POSTGRES_PASSWORD: mia` / `POSTGRES_DB: mia` (líneas 8-10). Es explícitamente el par **`mia:mia`**, de ejemplo para desarrollo local — no corresponde a ningún entorno de producción (en Azure, la contraseña de PostgreSQL es un parámetro `@secure()` (`infra/main.bicep:27-29`) inyectado en el despliegue y almacenado en Key Vault, ver bloque 4). Aun así, es una mala práctica dejar cualquier contraseña en texto plano en un fichero versionado en git, incluso de "solo desarrollo", porque (a) se replica sin pensar a otros entornos por copiar/pegar, y (b) si alguna vez ese puerto 5432 quedara expuesto accidentalmente fuera de `localhost` (p. ej. en una VM de pruebas con el compose desplegado tal cual), la credencial ya es pública en el repositorio.
  - Puerto publicado `5432:5432` (línea 12) — accesible desde el host.
  - Tiene *healthcheck* propio: `pg_isready -U mia` (línea 16).
- **`api`** (`docker-compose.yml:20-29`): se construye desde el `Dockerfile` local (`build: .`, línea 21), carga variables desde `.env` (`env_file: .env`, línea 22 — fichero no versionado, fuera del repo) y además fija explícitamente `MIA_DATABASE_URL: postgresql+asyncpg://mia:mia@db:5432/mia` en texto plano (línea 24) — **mismo hallazgo de credencial de desarrollo repetida**. Publica el puerto `5001:8000` (línea 26) y depende de que `db` esté *healthy* (líneas 27-29).
- No se usan secrets de Docker Compose (`secrets:`) ni variables indirectas para la contraseña de base de datos en este fichero; en cambio, el `.env` (no versionado) es el mecanismo previsto para el resto de secretos (LLM, voz, etc.), lo cual es razonable para un entorno estrictamente local.

---

## 4. Infraestructura Azure (`infra/main.bicep`, `infra/main.dev.bicepparam`, `infra/main.prod.bicepparam`)

Recursos creados por `infra/main.bicep` (`targetScope = 'resourceGroup'`, línea 4):

| Recurso | Línea | Rol / seguridad |
|---|---|---|
| Log Analytics Workspace | `main.bicep:103-111` | Retención 30 días (línea 109); destino de logs de Container Apps (línea 304-311). |
| Application Insights | `main.bicep:113-122` | Vinculado al workspace anterior (línea 120); su *connection string* se guarda en Key Vault (línea 231-235), nunca en claro en el bicep. |
| User-Assigned Managed Identity | `main.bicep:125-129` | Identidad única (`id-${name}`) compartida por la Container App y el Job de sincronización. |
| Key Vault | `main.bicep:132-144` | `enableRbacAuthorization: true` (línea 139, acceso vía RBAC, no *access policies* clásicas), *soft delete* 30 días (línea 141), *purge protection* forzada solo en prod (línea 142: `isProd ? true : null`). |
| Role assignment Key Vault | `main.bicep:146-159` | Rol **Key Vault Secrets User** (GUID `4633458b-17de-408a-b874-0445c86b69e6`, línea 148) asignado a la Managed Identity (líneas 151-159) — permiso mínimo (solo lectura de secretos, no gestión del vault). |
| PostgreSQL Flexible Server | `main.bicep:162-179` | SKU parametrizable (`postgresSku`, por defecto `Standard_B1ms`, línea 22/166-169), TLS forzado vía `?ssl=require` en la cadena de conexión (línea 193), *backup* 14 días en prod / 7 en dev (línea 175), **sin alta disponibilidad** (`highAvailability: { mode: 'Disabled' }`, línea 176). |
| Regla de firewall PostgreSQL | `main.bicep:187-191` | `AllowAzureServices` con rango `0.0.0.0–0.0.0.0` (líneas 189-190) — es el *toggle* estándar de Azure "permitir servicios de Azure", **no** apertura a Internet; el propio comentario del código (línea 186) ya advierte: *"Acceso solo desde servicios de Azure. Siguiente paso: red privada (VNet) en producción."* — es decir, el propio equipo reconoce que la red privada (VNet/private endpoint) para PostgreSQL **todavía no está implementada**, aunque el acceso público a nivel de red del propio PostgreSQL Flexible Server sigue `publicNetworkAccess: 'Enabled'` (línea 177). 🟡 — correcto para el estado actual, pero es un punto a mejorar antes de producción con datos reales de RRHH. |
| Secretos en Key Vault | `main.bicep:195-235` | `database-url` (con la contraseña embebida, línea 193-199), `llm-api-key` (201-205), `voice-api-key` si aplica (207-211), `pseudonym-key` (213-217, clave HMAC de pseudonimización de DNI/NIE), `sharepoint-pfx` y `sharepoint-pfx-password` si SharePoint está habilitado (219-229), `appinsights-connection-string` (231-235). Todos los parámetros de entrada que alimentan estos secretos están marcados `@secure()` en la cabecera del fichero (líneas 27-29, 31-33, 44-46, 69-71, 73-75, 77-79). |
| Container Registry | `main.bicep:238-256` | SKU `Basic` (línea 242), **`adminUserEnabled: false`** (línea 243 — el login de administrador clásico está desactivado; el acceso es solo vía identidad). Rol **AcrPull** (GUID `7f951dda-4ed3-4680-a7ca-43fe172d538d`, línea 246) asignado a la Managed Identity (líneas 248-256) — permiso mínimo (solo extraer imágenes, no publicar/gestionar). |
| Storage Account (informes) | `main.bicep:259-271` | `allowBlobPublicAccess: false` (línea 267), `allowSharedKeyAccess: false` (línea 268 — fuerza autenticación vía Azure AD/identidad, no claves de cuenta compartidas), `supportsHttpsTrafficOnly: true` (línea 269), `minimumTlsVersion: 'TLS1_2'` (línea 266). Contenedor `informes` (líneas 278-281). Rol **Storage Blob Data Contributor** (GUID `ba92f5b4-2d11-453d-a403-e96b0029c9fe`, línea 283-286) asignado a la Managed Identity (288-296). |
| Container Apps Environment | `main.bicep:299-312` | Logs dirigidos a Log Analytics (línea 304-311), usando `listKeys()` del workspace (línea 308) — esta es la única clave compartida usada en todo el bicep, y es interna entre el *environment* y el workspace de logs, no expuesta a la aplicación. |
| Container App (`ca-${name}`) | `main.bicep:366-404` | Identidad `UserAssigned` (líneas 370-373) con la Managed Identity común. *Ingress* externo, puerto `8000`, **`allowInsecure: false`** (líneas 379-383 — fuerza HTTPS). Los secretos de la app (líneas 386, construidos en `allSecrets`, línea 363) se referencian **todos vía Key Vault reference** (`keyVaultUrl` + `identity`, ver `baseSecrets`/`dataSecrets`/`sharepointSecrets`/`voiceSecrets`, líneas 314-330) — **ningún secreto en claro en las variables de entorno del bicep**; las variables de entorno no sensibles sí van en claro (`baseEnv`, líneas 332-344, p. ej. proveedor LLM, modo de autenticación). Sondas de *liveness* (`/health/live`) y *readiness* (`/health/ready`) configuradas en líneas 395-398. Escalado: mínimo `minReplicas` (parámetro, por defecto 1, línea 91) y máximo `isProd ? 3 : 1` (línea 401). |
| Container Apps Job de sincronización (`caj-${name}-sync`) | `main.bicep:407-438` | Solo se crea si `sharepointEnabled && !empty(containerImage)` (línea 407). Mismo patrón de identidad y secretos vía Key Vault que la app principal (líneas 411-425). **Disparador tipo `Schedule`** con `cronExpression: syncCron` (línea 419/422), y `syncCron` tiene como valor por defecto `'*/10 * * * *'` — **cada 10 minutos** — declarado en `infra/main.bicep:82` (parámetro `syncCron`). Esto **confirma textualmente** la afirmación del README de que la sincronización incremental corre cada 10 minutos vía Container Apps Job. El comentario de la línea 406 añade: *"Sincronización SharePoint → PostgreSQL: incremental cada 10 minutos, completa una vez al día"* — la sincronización completa diaria está regida por `full_sync_hour` (ver bloque 6). |
| Easy Auth (`authConfigs`) | `main.bicep:441-462` | Solo se crea `if (easyAuthEnabled)` (línea 441), donde `easyAuthEnabled = !empty(easyAuthClientId)` (línea 99). Exige login de Entra ID (`unauthenticatedClientAction: 'RedirectToLoginPage'`, línea 447) delante de **toda** la aplicación, excluyendo explícitamente las rutas de salud (`excludedPaths: ['/health/live', '/health/ready']`, línea 449). |

### ❌ HALLAZGO confirmado — Container Apps Job de sincronización ejecuta un comando que no existe en el paquete desplegado

`infra/main.bicep:431` define el contenedor del Job con:
```
command: ['python', '-m', 'mia.sync']
```
Pero el paquete Python realmente empaquetado y publicado es únicamente `src/mia` (`pyproject.toml:57`: `packages = ["src/mia"]`). Dentro de `src/mia` **no existe** ningún subpaquete `sync` — se comprobó directamente el árbol de `src/mia/` (no hay `src/mia/sync/`). El módulo de sincronización real, ejecutable y documentado, es **`mia.ingestion.sync`**, con punto de entrada propio en `src/mia/ingestion/sync/__main__.py:1-8` y referenciado consistentemente en:
- `README.md:77-81` (todos los comandos de ejemplo usan `python -m mia.ingestion.sync`)
- `tests/test_sync.py:15`, `tests/test_phase4_sources.py:19`, `tests/test_phase4c_calendars.py:23`
- `src/mia/api/services.py:13`

Existe además un árbol **`src/sync/`** (y toda una jerarquía paralela `src/api/`, `src/main.py`, `src/settings.py`, etc., hermana de `src/mia/`, tracked en git — ver `git ls-files src/sync src/api src/main.py src/settings.py`) cuyo `src/sync/__main__.py:3` también documenta literalmente `python -m mia.sync` en su docstring, y que internamente importa `from mia.sync.factory import ...` (`src/sync/__main__.py:26`) — pero este árbol **no se instala como paquete** (`pyproject.toml:57` solo empaqueta `src/mia`), por lo que ese `import mia.sync...` tampoco resolvería desde el wheel instalado en el contenedor runtime.

**Consecuencia práctica**: tal y como está escrito hoy el bicep, el Container Apps Job programado cada 10 minutos fallará en cada ejecución con `ModuleNotFoundError: No module named 'mia.sync'` dentro del contenedor runtime (que solo tiene instalado el wheel de `mia`, sin el código fuente completo — `Dockerfile:14-15` solo copia e instala los wheels, no `src/`). Esto es un defecto de despliegue real y verificable, no una suposición: compara `main.bicep:431` contra el contenido real de `src/mia/` y contra `pyproject.toml:57`.

### Diferencias dev vs prod y comprobación del requisito `easyAuthClientId`

- `infra/main.dev.bicepparam:1-21` **no define** `easyAuthClientId` (no aparece en el fichero) → en el bicep, `easyAuthClientId` queda en su valor por defecto `''` (`main.bicep:52`) → `easyAuthEnabled = false` (línea 99) → no se crea el recurso `authConfigs` → la app en dev puede arrancar con `MIA_AUTH__MODE=dev` (`baseEnv`, línea 334: `easyAuthEnabled ? 'easyauth' : 'dev'`).
- `infra/main.prod.bicepparam:9-10` **sí** fija `easyAuthClientId` y lo marca explícitamente como obligatorio en un comentario: *"Obligatorio en producción: sin Easy Auth la aplicación no arranca (MIA_AUTH__MODE=dev está bloqueado)"*.
- La comprobación real que hace que la aplicación **se niegue a arrancar** no está en el bicep (el bicep solo decide si despliega o no el recurso Easy Auth de Container Apps) sino **en el propio código Python**, en `src/mia/settings.py:331-334`:
  ```python
  @model_validator(mode="after")
  def _fail_closed_in_production(self) -> Settings:
      if self.environment is Environment.PRODUCTION and self.auth.mode is AuthMode.DEV:
          raise ValueError("MIA_AUTH__MODE=dev no está permitido en producción: usa 'easyauth' o 'entra'.")
  ```
  Esto se ejecuta al construir `Settings` (Pydantic), es decir, **falla al arrancar el proceso**, no en tiempo de petición. ✅ confirmado con evidencia de código, no solo de documentación.
- Otras comprobaciones de "fail-closed" en el mismo validador, también exclusivas de producción (`src/mia/settings.py:335-353`): modo `entra` exige tenant/client id (línea 335-336); `pseudonym_key` no puede seguir siendo el valor de desarrollo `"solo-para-desarrollo-local"` en producción (líneas 337-341, el valor por defecto está en línea 138); el proveedor LLM `fake` está prohibido en producción (línea 342-343); el Privacy Gateway no puede estar deshabilitado (344-345) ni en modo *fail-open* (346-347) en producción; y su `vault_key` tampoco puede quedarse vacío en producción (348-353). Este patrón de validación "falla al arrancar, no en caliente" es consistente y es una buena práctica de seguridad por defecto. ✅

Otras diferencias dev/prod en los `.bicepparam`: idénticos en SKU de PostgreSQL (`Standard_B1ms` en ambos, lo cual es llamativo para producción — un SKU *Burstable* mínimo, sin alta disponibilidad, bajo cargas reales de RRHH; no es una brecha de seguridad pero sí un punto de capacidad/rendimiento a revisar con IT). La única diferencia explícita entre ambos ficheros de parámetros es la presencia de `easyAuthClientId`.

---

## 5. CI/CD (`.github/workflows/ci.yml`)

Un único workflow, 4 jobs, disparado en `push` a `main` y en `pull_request` (`ci.yml:3-6`):

- **`calidad`** (`ci.yml:9-21`): `ruff check` (línea 18), `ruff format --check` (línea 19), `mypy` (línea 20, con `strict = true` según `pyproject.toml:79`), `pytest --cov=mia` (línea 21).
- **`postgres`** (`ci.yml:23-47`): levanta un contenedor `postgres:18` de servicio (líneas 27-35, con credenciales `mia:mia`, igual patrón que el compose local, línea 30-32 — aceptable en CI efímero), aplica `alembic upgrade head` y `alembic downgrade base` (línea 46) para validar las migraciones en ambos sentidos, y corre `pytest` contra PostgreSQL real (línea 47).
- **`frontend`** (`ci.yml:49-62`): `npm ci` + `npm run build` (líneas 61-62) con Node 22 (línea 58).
- **`imagen`** (`ci.yml:64-69`): depende de los tres anteriores (línea 65) y simplemente ejecuta `docker build -t mia:${{ github.sha }} .` (línea 69) — **construye la imagen pero no la publica** (no hay `docker push`, no hay login a ningún registro, no hay paso de despliegue a Azure en este workflow).

### Comprobación explícita de controles de seguridad en el pipeline

- **SCA (análisis de dependencias/vulnerabilidades conocidas)**: ❌ **No existe**. No hay `pip-audit`, `safety`, Dependabot (`.github/dependabot.yml` no está presente en el repo), ni `npm audit` en el job `frontend`.
- **SAST (análisis estático de seguridad del código)**: 🟡 **Parcial, no un SAST dedicado**. `ruff` está configurado con la regla `"S"` (`pyproject.toml:71`: `select = ["E", "F", "W", "I", "B", "UP", "ASYNC", "S", "SIM", "RUF", "PL"]`), que corresponde a las reglas `flake8-bandit` integradas en Ruff — esto es una comprobación estática ligera de patrones inseguros conocidos (uso de `eval`, `subprocess` sin sanitizar, contraseñas hardcodeadas obvias, etc.), ejecutada en el job `calidad` (`ci.yml:18`). No es un SAST completo (no hay Semgrep, CodeQL, Bandit standalone con su configuración propia, ni SonarQube) y no cubre el frontend.
- **Escaneo de contenedores (imagen Docker)**: ❌ **No existe**. El job `imagen` (`ci.yml:64-69`) solo construye (`docker build`), no hay Trivy, Grype, Docker Scout, ni `az acr check-health`/escaneo de Defender for Containers invocado desde CI.
- **Firmado de imágenes**: ❌ **No existe**. No hay `cosign`, ni ningún paso de firma/verificación de la imagen construida.
- **Despliegue automatizado**: ❌ **No existe en CI**. No hay ningún job que publique en el Container Registry ni que ejecute `az deployment group create` contra `infra/main.bicep` — el despliegue a Azure es, según la documentación del propio bicep (`infra/main.bicep:2`, comentario `az deployment group create -g <grupo> -f infra/main.bicep -p infra/main.dev.bicepparam`), **manual**.

---

## 6. Procesos y jobs

- **Proceso principal (API)**: arrancado por `Dockerfile:22` (uvicorn + factory `mia.main:create_app`), ejecutándose dentro del Container App `ca-${name}` (`main.bicep:366`). ✅
- **Job de sincronización SharePoint → PostgreSQL**: Container Apps Job `caj-${name}-sync` (`main.bicep:407-438`), cron `*/10 * * * *` = cada 10 minutos (`main.bicep:82`, variable `syncCron`), **confirmado contra el README y el propio comentario del bicep** (línea 406). Ver el ❌ HALLAZGO del bloque 4: el comando configurado (`main.bicep:431`, `python -m mia.sync`) no corresponde al módulo real instalado (`mia.ingestion.sync`).
- **Sincronización completa diaria**: no es un job de Azure independiente; está gobernada en código por `DataSettings.full_sync_hour: int = 3` (`src/mia/settings.py:140`) y consumida por el propio `SyncRunner` dentro de `src/mia/ingestion/sync/runner.py:73,83,162-167` — la lógica (línea 165) decide `SyncMode.FULL` si `now_local.hour >= self._full_sync_hour` y no se ha hecho ya una completa ese día, o si han pasado más de 26 horas desde la última completa (línea 166). Es decir: el **mismo** job programado cada 10 minutos decide internamente, cada vez que corre, si le toca hacer una sincronización incremental o la completa diaria de las 03:00 — no hay un segundo *Container Apps Job* para la sincronización completa. ✅ (lógica), pero depende del mismo defecto de comando del bloque anterior para funcionar en Azure.
- **Generación de informes / TTL de ficheros**: `ReportSettings` en `src/mia/settings.py:231-236`: `directory: Path = Path("informes")` (línea 232), `ttl_hours: int = 24` (línea 235), `max_rows: int = 5000` (línea 236). El TTL se aplica explícitamente al construir cada informe en `src/mia/modules/rrhh/informes/tools.py:97` y `tools.py:587` (`ttl = timedelta(hours=settings.ttl_hours if settings else 24)`). En Azure, el directorio de informes se fija a `/tmp/informes` vía variable de entorno `MIA_REPORTS__DIRECTORY` (`main.bicep:350`) — **dentro del propio contenedor**, no en el Storage Account/Blob (el Storage Account de `main.bicep:259-271` existe y tiene permisos concedidos a la identidad, pero no se ve una variable de entorno que redirija `MIA_REPORTS__DIRECTORY` hacia blob storage; es un punto a confirmar con el equipo de desarrollo, porque escribir informes en `/tmp` de un Container App significa que no sobreviven a un reinicio/réplica nueva, y con `maxReplicas` > 1 en prod (`isProd ? 3 : 1`, línea 401) un informe generado podría no estar disponible si la siguiente petición cae en otra réplica). 🟡
- **Worker de informes masivos**: `JobsSettings` (`src/mia/settings.py:252-255`): `enabled: bool = False` por defecto (línea 253), `poll_interval_seconds: float = 5.0` (línea 255) — es un *flag* que activa un worker en segundo plano **dentro del mismo proceso**, no un job de Azure independiente; no se ve activado (`true`) en ninguno de los `.bicepparam` ni en `main.bicep` (no se referencia `MIA_JOBS__ENABLED` en las variables de entorno de `main.bicep:332-362`), así que en el despliegue Azure descrito, este worker permanece **desactivado por defecto**. 🟡
- **Rotación/retención de logs**: gestionada por Azure, no por la aplicación: `retentionInDays: 30` en el Log Analytics Workspace (`main.bicep:109`). No hay rotación de logs a nivel de fichero local en el contenedor (los logs van a stdout, ver bloque 7), lo cual es el patrón correcto para contenedores — no hay ficheros de log locales que rotar.

---

## 7. Observabilidad (`src/mia/observability/`)

- **Logging estructurado**: `src/mia/observability/logging.py`. Usa `structlog` (`logging.py:10`), con salida JSON en Azure o consola legible en local (`json_output` parámetro, línea 31, `JSONRenderer` vs `ConsoleRenderer`, líneas 35-37). ✅
- **Redacción automática de secretos en logs**: `_SENSITIVE_KEYS = frozenset({"api_key", "authorization", "password", "secret", "token"})` (`logging.py:14`) y el procesador `_redact` (líneas 24-28) sustituye esos campos por `"***"` en cada evento de log antes de renderizarlo — control de buena práctica explícito contra fuga de secretos en logs. ✅
- **Correlación de peticiones**: `src/mia/observability/context.py`. `new_request_id()` (líneas 11-17) genera o reutiliza un id de petición validado (máx. 64 caracteres, alfanumérico, línea 14) en un `ContextVar` (línea 8), y el procesador `_add_request_id` de `logging.py:17-21` lo añade automáticamente a cada línea de log. ✅ — correlación real de logs por petición HTTP.
- **Integración con Application Insights**: `src/mia/observability/telemetry.py`. `configure_telemetry()` (líneas 11-22) solo actúa si `settings.observability.applicationinsights_connection_string` tiene valor (línea 12-14); importa `azure.monitor.opentelemetry` de forma perezosa (línea 16, parte del extra `azure` de `pyproject.toml:44-45`) y si no está instalado registra un *warning* y se desactiva sin romper el arranque (líneas 17-19) — **degradación segura, no un fallo duro**. La *connection string* llega siempre desde Key Vault en Azure (`main.bicep:231-235` + `secretRef: 'appinsights'` en `main.bicep:340`), nunca en claro. ✅
- **`ObservabilitySettings`** (`src/mia/settings.py:246-249`): `log_level: str = "INFO"` (línea 247), `log_json: bool = True` (línea 248), `applicationinsights_connection_string: SecretStr | None = None` (línea 249) — tipado como `SecretStr`, por lo que Pydantic tampoco lo expondría accidentalmente en una representación/`repr()` de los *settings*. ✅
- **Alertas**: ❌ **No existe ninguna configuración de alertas** en `infra/main.bicep` — no hay `Microsoft.Insights/metricAlerts`, ni `actionGroups`, ni *smart detection rules* de Application Insights declaradas como código. Hoy la observabilidad es: generar logs/telemetría y enviarlos a Log Analytics/App Insights, y queda en manos del equipo de IT configurar manualmente las alertas sobre esos datos (o no hacerlo). Esto es un punto a destacar: hay **visibilidad** pero no hay **reacción automática** (alertas/runbooks) definida como código.

---

## 8. Dominios funcionales existentes — RRHH sí, el resto NO (hallazgo importante para no sobrevender)

`ALL_DOMAINS` tal cual aparece en el código, `src/mia/settings.py:159-171`:
```python
ALL_DOMAINS = (
    "empleados",
    "turnos",
    "fichajes",
    "vacaciones",
    "curriculums",
    "correo",
    "nominas",
    "documentos",
    "trabajo_temporal",
    "analitica",
    "informes",
)
```
**Los 11 dominios activos por defecto (`DomainSettings.enabled`, línea 175) son exclusivamente de RRHH.** No hay ningún dominio llamado "finanzas", "administración", "legal" ni "compliance" en esta lista.

En `src/mia/modules/` existen físicamente **solo dos paquetes**:
- `src/mia/modules/rrhh/` — **completamente desarrollado**: subpaquetes reales con código para cada uno de los 11 dominios anteriores (`analitica`, `correo`, `curriculums`, `documentos`, `empleados`, `fichajes`, `informes`, `nominas`, `sistema`, `trabajo_temporal`, `turnos`, confirmado por listado directo del directorio) más utilidades (`charts.py`, `common.py`, `content.py`, `document_indexing.py`, `document_search.py`, `payroll_embedding_privacy.py`). ✅ **RRHH es real y está implementado.**
- `src/mia/modules/finanzas/` — **esqueleto vacío, sin fuente de datos**: un único fichero `__init__.py` (28 líneas). Su propio docstring lo dice explícitamente (`src/mia/modules/finanzas/__init__.py:1-9`): *"Módulo Finanzas — sin fuente de datos real todavía"*, y la función `register()` (líneas 52-54) "no registra ninguna herramienta" — el comentario interno aclara que existe únicamente para que el futuro orquestador multi-módulo se diseñe contra un segundo módulo real en su forma (nombre, convenciones), no para ofrecer ninguna funcionalidad de Finanzas hoy. 🔵 **Planificado/placeholder, no funcional.**

**❌ No existe ningún paquete, módulo ni mención de código para "Administración", "Legal" o "Compliance"** en `src/mia/modules/` ni en `ALL_DOMAINS`. Si el guion de la presentación habla de "RRHH, Finanzas, Administración, Legal y Compliance" como dominios de mIA, la realidad verificada en código es: **RRHH = ✅ implementado y en producción; Finanzas = 🔵 placeholder vacío sin datos ni herramientas; Administración, Legal y Compliance = ❌ no existen en absoluto, ni como esqueleto.** Esto debe comunicarse sin ambigüedad a IT para no sobrevender el alcance actual del sistema.

---

## 9. Capa predictiva/ML — no existe código todavía, es aspiracional

Se buscó explícitamente cualquier paquete `predictive`, `ml`, `forecasting`, `model`, etc. dentro de `src/mia/`. El listado completo de subcarpetas de primer nivel de `src/mia/` es:
```
analytics, api, assets, attachments, auth, connectors, conversation, core, data,
diagnostics, ingestion, knowledge, learning, llm, modules, observability,
presentation, privacy_gateway, query, reporting, rules, voice
```
**❌ No existe ningún paquete `predictive`, `ml`, `forecasting`, `models` ni equivalente.** El requisito de CLAUDE.md de un "subsistema predictivo estructuralmente separado de la capa LLM y de los dominios transaccionales" (con *feature definitions*, *datasets*, *snapshots*, *training*, *scoring*, *forecasting*, *explainability*, *model registry*, *evaluation*, *monitoring*) **no tiene ningún equivalente en el código actual**, ni siquiera como infraestructura/contratos vacíos. El paquete más próximo en nombre es `src/mia/analytics/` y `src/mia/learning/`, pero ninguno de los dos fue investigado como sustituto exacto en esta auditoría del bloque de despliegue/infraestructura (están fuera de alcance de este informe, que es de despliegue/infra/procesos/observabilidad, no de arquitectura funcional); lo que sí se puede afirmar con la evidencia reunida es que **no hay ningún artefacto de despliegue** (bicep, Dockerfile, CI) que haga referencia a entrenamiento de modelos, registro de modelos, *scoring* batch ni pipelines de ML — ni en `infra/main.bicep`, ni en `.github/workflows/ci.yml`, ni en `Dockerfile`. Conclusión para la presentación: la capa predictiva es **íntegramente aspiracional** a día de hoy; no hay nada que auditar en producción porque no se despliega nada de eso.

---

## Resumen de clasificación

| Punto | Estado |
|---|---|
| 1. Prerrequisitos (Python/Node) | ✅ |
| 1. Descarga del modelo spaCy `es_core_news_lg` | ❌ HALLAZGO (no automatizada) |
| 2. Dockerfile — usuario no-root | ✅ |
| 2. Dockerfile — healthcheck | ✅ |
| 2. Dockerfile — versiones Python fijadas | 🟡 HALLAZGO (rangos, no lockfile) |
| 3. docker-compose — credenciales en texto plano (`mia:mia`, desarrollo local) | 🟡 HALLAZGO (ámbito dev, no prod) |
| 4. Recursos Azure, identidad, RBAC, Key Vault | ✅ |
| 4. Requisito `easyAuthClientId` en prod, fail-closed en código | ✅ (confirmado en `settings.py:333-334`) |
| 4. Comando del Container Apps Job de sync (`main.bicep:431`) | ❌ HALLAZGO (módulo inexistente en el paquete desplegado) |
| 4. Red privada (VNet) para PostgreSQL | 🔵 Planificado (admitido en el propio código) |
| 5. CI — lint/tests/build | ✅ |
| 5. CI — SCA | ❌ |
| 5. CI — SAST dedicado (más allá de reglas bandit en ruff) | 🟡 / ❌ |
| 5. CI — escaneo de contenedores | ❌ |
| 5. CI — firmado de imágenes | ❌ |
| 5. CI — despliegue automatizado a Azure | ❌ (manual, por diseño actual) |
| 6. Job de sync cada 10 min (cron) | ✅ (confirmado en bicep), pero ver hallazgo del comando |
| 6. TTL de informes | ✅ (lógica), 🟡 (persistencia en `/tmp` con múltiples réplicas) |
| 7. Logging estructurado + redacción de secretos + correlación por request_id | ✅ |
| 7. Application Insights | ✅ (opcional, degrada con seguridad) |
| 7. Alertas automatizadas | ❌ |
| 8. Dominio RRHH | ✅ Implementado |
| 8. Dominio Finanzas | 🔵 Placeholder vacío |
| 8. Dominios Administración / Legal / Compliance | ❌ No existen |
| 9. Capa predictiva/ML | ❌ No existe (aspiracional) |

**Recuento global: ✅ 16 · 🟡 6 · 🔵 2 · ❌ 10**
