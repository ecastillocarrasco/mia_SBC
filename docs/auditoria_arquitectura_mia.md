# Auditoría de arquitectura y seguridad — mIA

**Repositorio**: `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA` · **Fecha**: 2026-10-20
**Metodología**: lectura directa del código fuente (sin ejecución de la app, sin acceso a configuración real de Azure/Entra ID). Cada afirmación cita `fichero:línea`. Realizada por 5 auditorías paralelas, una por bloque, cuyos informes completos están en:

- `docs/auditoria_detalle/audit_auth_secretos.md`
- `docs/auditoria_detalle/audit_llm_presidio_voz.md`
- `docs/auditoria_detalle/audit_integraciones.md`
- `docs/auditoria_detalle/audit_despliegue_infra.md`
- `docs/auditoria_detalle/audit_frontend_api_supplychain.md`

Leyenda: ✅ Implementado y verificado en código · 🟡 Parcial/en desarrollo · 🔵 Planificado (decidido, pendiente) · ❌ No existe / brecha.

**Regla seguida**: nada se marca ✅ sin haberlo visto en el código. Lo no verificable desde el repositorio (p. ej. permisos reales concedidos en el tenant de Entra ID) se marca explícitamente como "requiere verificación en el tenant", no se asume.

---

## 0. Resumen ejecutivo

**108 controles/componentes evaluados en total**: ✅ 66 implementados · 🟡 14 parciales · 🔵 6 planificados · ❌ 22 brechas o ausencias.

mIA tiene una base de seguridad notablemente más sólida de lo habitual en un proyecto de este tamaño: validación JWT completa contra Entra ID con 7 casos de test (incluido "key confusion"), un sistema de permisos granular a nivel de dato (no solo de ruta), fail-closed real al arranque en producción (5 comprobaciones distintas bloquean el arranque si falta configuración mínima de seguridad), protección de PII con reconocedores españoles validados por checksum real, y ningún secreto expuesto en el frontend ni en el historial de git. Al mismo tiempo, hay brechas concretas y reales que deben comunicarse con la misma honestidad: un defecto de despliegue que haría fallar el job de sincronización en Azure tal como está today, ausencia total de rate limiting y de escaneo de vulnerabilidades en CI, un permiso de Microsoft Graph potencialmente más amplio de lo pretendido, y — el punto más importante para no sobrevender — de los dominios de negocio anunciados (RRHH, Finanzas, Administración, Legal y Compliance) **solo RRHH está implementado**; el resto es un placeholder vacío o no existe en absoluto.

### Los 10 hallazgos más importantes para IT (todas severidades)

| # | Hallazgo | Severidad | Fuente |
|---|---|---|---|
| 1 | El permiso de aplicación de Graph para correo (`Mail.Read`) da acceso a **todos los buzones del tenant** salvo que exista una Application Access Policy de Exchange Online que lo acote — no hay evidencia en el repo de que exista | 🔴 Crítico | Integraciones |
| 2 | El Container Apps Job de sincronización (`infra/main.bicep:431`) ejecuta `python -m mia.sync`, módulo que **no existe** en el paquete realmente desplegado (`mia.ingestion.sync` es el real) → falla en cada ejecución en Azure | 🔴 Alto | Despliegue |
| 3 | De los dominios anunciados (RRHH, Finanzas, Administración, Legal, Compliance), **solo RRHH existe**; Finanzas es un paquete vacío; Administración/Legal/Compliance no existen ni como esqueleto | 🔴 Alto (sobreventa) | Despliegue |
| 4 | Sin rate limiting en ninguna ruta (`/api/chat/stream`, `/api/voice/stream`) — riesgo de abuso de coste y disponibilidad | 🔴 Alto | Frontend/API |
| 5 | Sin Dependabot ni escaneo de vulnerabilidades (pip-audit/npm audit/trivy) en CI | 🔴 Alto | Frontend/API |
| 6 | El modelo spaCy (`es_core_news_lg`) que exige el Privacy Gateway no se instala en ningún paso automatizado (Dockerfile/CI) — el Privacy Gateway es obligatorio en producción y fallaría cerrado hasta instalarlo a mano | 🟠 Alto (fiabilidad) | Despliegue |
| 7 | Permisos de aplicación de Graph/SharePoint no declarados como código (siempre `.default`) — el mínimo privilegio solo se puede auditar en el tenant de Entra ID, no desde el repositorio | 🟠 Alto | Integraciones |
| 8 | Sin lockfile real en el backend Python (solo rangos en `pyproject.toml`) — build no 100% reproducible | 🟡 Medio-alto | Frontend/API + Despliegue |
| 9 | La capa de voz (ElevenLabs) solo filtra importes de nómina; nombres, DNI, email o datos médicos no se filtran antes de salir a ese proveedor externo | 🟡 Medio | LLM/Presidio/Voz |
| 10 | `MIA_PRIVACY_GATEWAY__ENABLED=false` por defecto fuera de producción — mitigado por un validador que lo obliga `true` cuando `MIA_ENVIRONMENT=production`, pero esa garantía depende de que el entorno real de Azure esté correctamente etiquetado | 🟡 Medio | LLM/Presidio/Voz |

### Puntos fuertes verificados a destacar (no solo brechas)

- Autenticación Entra ID: validación de firma RS256/JWKS, audiencia, emisor, expiración, con 7 escenarios de test incluyendo rechazo de tokens firmados con clave ajena.
- 5 comprobaciones de arranque ("fail-closed") impiden que producción arranque con configuración insegura: modo dev, Privacy Gateway desactivado o en fail-open, proveedor LLM "fake", clave de seudonimización de desarrollo.
- Autorización a nivel de dato (no solo de ruta): permiso específico para importes de nómina y para contenido médico de documentos, ambos con puerta de código verificada, no solo instrucción al LLM.
- Confirmación humana robusta para envío de correo (bloqueo en el mismo turno, confirmación léxica explícita, verificación de buzón de origen).
- Ningún secreto real encontrado en el historial de git ni en el frontend; todas las claves viven en Key Vault vía Managed Identity.
- Ningún `verify=False` en ningún cliente HTTP del repositorio (TLS siempre validado).
- Seudonimización de DNI/NIE antes de persistir, con reconocedores españoles (DNI/NIE, IBAN, Seguridad Social) validados por dígito de control real, no solo forma.
- Conectia/A3 está correctamente marcado como no implementado en el propio código (sin falsos positivos de integración que no existe).

---

## 1. Inventario de capas y seguridad

### 1.1 Autenticación — ✅ Implementado (backend) / 🔵 Planificado (despliegue del modo `entra`)

Tres modos por `MIA_AUTH__MODE` (`src/mia/settings.py:27-35`): `dev`, `easyauth`, `entra`.

- **`dev`** — identidad fija (`src/mia/auth/providers.py:36-47`), rol `mia.admin` = acceso total. Bloqueado en producción por validador de arranque (`settings.py:331-334`) con test dedicado (`tests/test_auth.py:208-210`).
- **`easyauth`** — lee cabecera `x-ms-client-principal` inyectada por Azure tras el login gestionado por la plataforma (`src/mia/auth/providers.py:50-81`). Es la vía de producción configurada hoy en `infra/main.bicep:441-458`.
- **`entra`** — validación JWT propia completa: firma RS256 contra JWKS del tenant, audiencia, issuer, expiración, claims obligatorios (`src/mia/auth/providers.py:84-167`). Cobertura de test exhaustiva, incluido rechazo por "key confusion" (`tests/test_auth.py:148-205`). Frontend con MSAL.js real, no un stub (`frontend/src/core/auth-gate.js`), incluido manejo de token y pantalla de "acceso restringido" si el usuario no tiene rol.
  **Brecha de despliegue**: `infra/main.bicep` solo contempla `dev`/`easyauth` (línea 333) — el modo `entra`, aunque implementado y probado, no está conectado a la infraestructura Azure actual.

### 1.2 Autorización — ✅ Implementado (ruta + dato)

19 permisos granulares (`src/mia/auth/context.py:17-49`), mapa rol→permiso con dos familias (roles de desarrollo vs. 5 App Roles reales de Entra ID: `Global`, `RRHH`, `RRHH.NoNominas`, `Administracion`, `Legal`). Decisión de seguridad relevante: mIA **nunca** lee el claim `groups` de Entra ID, solo `roles` asignados explícitamente.

Control a nivel de dato, no solo de ruta, verificado en 2 de 3 casos con puerta de código real (independiente del LLM): importes de nómina (`Permission.NOMINAS_IMPORTES`) y contenido médico de documentos (`Permission.DOCUMENTOS_CONTENIDO_MEDICO`). El tercer caso, firmas (regla `FIR-001`), depende solo de instrucción de prompt — 🟡 sin puerta de código equivalente verificada.

### 1.3 Gestión de secretos — ✅ Implementado

7 campos `SecretStr` en `settings.py` (LLM, voz, certificado SharePoint x2, clave de seudonimización, Token Vault, Application Insights), todos coincidentes con `.env.example` sin valores reales. En Azure: Key Vault + Managed Identity con rol `Key Vault Secrets User` (solo lectura), secretos inyectados como `secretRef`, nunca en claro en el bicep. `.bicepparam` leen de variables de entorno del proceso de CI/CD, no hardcodean nada. Sin indicios de secretos reales en el historial de git (comprobación acotada; se recomienda gitleaks/trufflehog como verificación adicional).

### 1.4 Aislamiento multiusuario — ✅ Implementado y probado

Sesión por `(session_id, user_id)` con `SessionNotOwnedError` → 403 real si otro usuario reutiliza un `session_id` ajeno (test end-to-end incluido). Token Vault del Privacy Gateway aislado por `(user_id, operation_id, token)`. Cuentas de prueba excluidas de la sincronización de datos reales por patrón de nombre (`^test`, `^tezt`), con test dedicado.

### 1.5 Capa LLM — ✅ Implementado

Una única clase sirve OpenAI y Azure OpenAI (`OpenAIResponsesProvider`); Azure OpenAI es un camino de primera clase, no un añadido. Separación system/instructions vs. datos de herramientas a nivel de transporte (API Responses nativa). Resultados de herramientas (correos, documentos, SharePoint) envueltos como "dato no confiable" con delimitadores explícitos — **solo si el Privacy Gateway está activo** (ver 1.7). Streaming end-to-end, límite de rondas de herramientas (8) y presupuesto de turno (120s). Confirmación humana robusta para envío de correo. ❌ Sin rate limiting ni control de coste por usuario.

### 1.6 Motor conversacional y enrutado — ✅ Implementado (con matiz)

Enrutado determinista por vocabulario (no por LLM, decisión explícita de CLAUDE.md). Cuando ninguna palabra clave coincide, el sistema **no** reduce el catálogo de herramientas a un "modo asistente general" de menor privilegio: devuelve el catálogo completo de RRHH para el que el usuario tenga permiso — 🟡 el control real sigue siendo el permiso, no el enrutado; no existe un "sandbox" de menor privilegio para preguntas ambiguas.

### 1.7 Protección de PII — Presidio / Privacy Gateway — ✅ Implementado (con matiz crítico)

Único punto de salida al LLM, sin bypass arquitectónico posible (`build_llm_provider()` siempre envuelve en `PrivacyGateway`). Reconocedores españoles con checksum real (DNI/NIE, IBAN, Seguridad Social). Reversible dentro de la operación vía Token Vault cifrado (Fernet, TTL 900s); irreversible por diseño en embeddings. `fail_open=False` por defecto y bloqueado en producción (fail-closed real: cualquier excepción de Presidio bloquea la llamada, nunca degrada a "enviar sin proteger").

**Matiz crítico**: `PrivacyGatewaySettings.enabled=False` por defecto. Con `enabled=false` el gateway no tokeniza ni escanea nada — mitigado solo porque un validador de arranque **obliga** `enabled=true` en producción; esa garantía depende de que el entorno Azure real esté etiquetado `MIA_ENVIRONMENT=production`, algo que el código no puede verificar por sí mismo.

❌ Sin soporte de inglés (solo `es_core_news_lg`). ❌ El bloqueo de prompt injection es solo detección/auditoría (regex), nunca bloquea la petición — la mitigación real es arquitectónica (permisos deterministas).

### 1.8 RAG / conocimiento — ✅ Implementado

Indexa CVs y, si se activa `index_sensitive_content` (false por defecto), también nóminas/documentos con minimización específica antes de vectorizar (proyección sin cifras para nóminas). Filtrado de acceso a nivel de query SQL para CVs. 🟡 Modelo de acceso es RBAC por rol, no por propietario del registro — un rol RRHH/Administración puede consultar documentos de cualquier empleado.

### 1.9 Capa de voz — ✅ Implementado (con hallazgo)

ElevenLabs vía streaming, caché que excluye respuestas largas/variables. `guard.clean_speech()` bloquea compromisos imposibles e **importes monetarios** (regla nacida de un incidente real documentado en el propio código). ❌ No filtra PII general (nombres, DNI, email, datos médicos) antes de enviarla a este proveedor externo — y el endpoint `/api/voice/stream` no revalida el texto recibido del frontend contra este filtro.

### 1.10 Dominios funcionales — ✅ RRHH / 🔵 Finanzas / ❌ Administración, Legal, Compliance

`ALL_DOMAINS` (11 dominios, `settings.py:159-171`) son exclusivamente de RRHH, completamente implementados. `src/mia/modules/finanzas/` es un `__init__.py` de 28 líneas que no registra ninguna herramienta (placeholder explícito). **No existe ningún paquete ni mención de código** para Administración, Legal o Compliance.

### 1.11 Capa predictiva/ML — ❌ No existe

Ningún paquete `predictive`/`ml`/`forecasting` en `src/mia/`. Ningún artefacto de despliegue (bicep, Dockerfile, CI) referencia entrenamiento, registro de modelos o scoring. Es íntegramente aspiracional hoy.

### 1.12 Frontend y API — ✅ Implementado (con hallazgos medios)

Token transportado solo vía `Authorization: Bearer` (nunca cookies). Sin ninguna clave de API expuesta en el cliente — todo pasa por el backend como proxy (confirmado, no se encontró ninguna llamada directa del frontend a OpenAI/ElevenLabs). Validación de adjuntos robusta (allowlist + magic-bytes + denylist + anti path-traversal). Manejo de errores sin fuga de información interna.

Hallazgos: ❌ sin rate limiting (severidad alta); 🟡 faltan `Content-Security-Policy` y `Strict-Transport-Security`; ❌ sin escaneo antivirus de adjuntos; `max_files` configurado pero nunca aplicado; `cors_origins` sin guardarraíl fail-closed en producción (a diferencia de otras variables críticas que sí lo tienen).

### 1.13 Cadena de suministro — 🟡 Parcial

Frontend: lockfile real (`package-lock.json`) usado correctamente en CI vía `npm ci`. ❌ Backend: sin lockfile real, solo rangos en `pyproject.toml`. ❌ Sin Dependabot ni escaneo de vulnerabilidades (pip-audit/npm audit/trivy) en ningún punto del pipeline.

### 1.14 Observabilidad — ✅ Implementado (sin alertas)

`structlog` con redacción automática de claves sensibles en logs, correlación por `request_id`, integración opcional con Application Insights que degrada con seguridad si no está configurada. ❌ Sin ninguna alerta automatizada definida como código (ni `metricAlerts` ni `actionGroups` en el bicep) — hay visibilidad, no hay reacción automática.

---

## 2. Inventario de despliegue y operación

### 2.1 Prerrequisitos

Python `>=3.12` (`pyproject.toml:10`), Node 22 en CI para el frontend (el Dockerfile de producción **no** construye el frontend, no forma parte de la imagen de la API). Dependencias sensibles: `presidio-analyzer`/`presidio-anonymizer`, `spacy`. ❌ El modelo `es_core_news_lg` (~500 MB) que exige el Privacy Gateway no se instala en ningún paso de build automatizado — solo hay constancia documental manual.

### 2.2 Dockerfile — ✅ buenas prácticas, con un hallazgo de versionado

Multi-stage, usuario no-root (`uid 10001`), un único puerto expuesto (8000), healthcheck real contra `/health/live`. 🟡 Las dependencias Python se resuelven en el momento del build dentro de rangos (`pip wheel` sin lockfile) — build no reproducible bit a bit. Arranque con `--forwarded-allow-ips='*'` (riesgo bajo dentro de Azure Container Apps, al estar siempre detrás del ingress gestionado).

### 2.3 docker-compose — 🟡 solo desarrollo local

Credenciales `mia:mia` en texto plano (líneas 8-10 y 24) — explícitamente de ejemplo local, no de producción (en Azure la contraseña es un parámetro `@secure()` vía Key Vault), pero mala práctica de higiene en un fichero versionado.

### 2.4 Infraestructura Azure (`infra/main.bicep`) — ✅ Implementado, con un defecto crítico

Recursos: Log Analytics, Application Insights, Managed Identity, Key Vault (RBAC, acceso mínimo), PostgreSQL Flexible Server (TLS forzado, sin alta disponibilidad, SKU `Standard_B1ms` tanto en dev como en prod), Container Registry (sin login admin, solo AcrPull vía identidad), Storage Account (sin acceso público, sin claves compartidas, TLS 1.2 mínimo), Container App (HTTPS forzado, secretos solo vía Key Vault reference), Container Apps Job de sincronización (cron cada 10 min), Easy Auth condicional.

**❌ Defecto confirmado**: el Job de sincronización ejecuta `python -m mia.sync` (`main.bicep:431`), módulo que no existe en el paquete desplegado (el real es `mia.ingestion.sync`) — fallará con `ModuleNotFoundError` en cada ejecución tal como está hoy.

🔵 Red privada (VNet/private endpoint) para PostgreSQL reconocida como pendiente en el propio comentario del código (`main.bicep:186`).

✅ Confirmado en código (no solo en README): producción se niega a arrancar sin `easyAuthClientId`, vía el validador `_fail_closed_in_production` (`settings.py:331-354`), que también exige: clave de seudonimización real, proveedor LLM distinto de `fake`, Privacy Gateway activo y no en fail-open con `vault_key` presente.

### 2.5 CI/CD (`.github/workflows/ci.yml`) — 🟡 calidad sí, seguridad de cadena no

4 jobs: calidad (ruff + mypy estricto + pytest), postgres (migraciones en ambos sentidos contra BD real), frontend (`npm ci` + build), imagen (`docker build`, sin publicar). ❌ Sin SCA, sin SAST dedicado (solo reglas bandit integradas en ruff), sin escaneo de contenedores, sin firmado de imágenes, sin despliegue automatizado (el despliegue a Azure es manual, por diseño documentado).

### 2.6 Procesos y jobs

Proceso principal (API, uvicorn). Job de sincronización SharePoint→PostgreSQL cada 10 minutos (ver defecto 2.4); la sincronización completa diaria (03:00) la decide el mismo job internamente, no es un job aparte. Generación de informes con TTL de 24h; 🟡 se escriben en `/tmp` del contenedor — con `maxReplicas>1` en producción, un informe podría no estar disponible si la siguiente petición cae en otra réplica. Worker de informes masivos (`JobsSettings`) desactivado por defecto y no activado en ningún `.bicepparam`.

---

## 3. Inventario de conexiones e integraciones

Ver detalle completo y matriz de datos en `docs/mIA_catalogo_integraciones.md`. Resumen de estado:

| Integración | Estado |
|---|---|
| SharePoint Online (REST + certificado Entra ID) | ✅ Implementado |
| Microsoft Graph — Correo | ✅ Implementado (⚠️ ver hallazgo crítico de alcance de permiso) |
| Conectia/A3 (fichajes, conector real) | 🔵 Planificado — solo interfaz abstracta, sin código de red |
| Importación manual de Excel de fichajes | ✅ Implementado — no es conexión externa (fichero local) |
| Búsqueda web (vía proveedor LLM) | ✅ Implementado (indirecto; mIA no llama directamente a sitios externos) |
| Azure AI Search | 🔵 Planificado / ❌ sin código que lo invoque |
| Azure ML (predictivo) | 🔵 Planificado / ❌ sin código que lo invoque |
| PostgreSQL (asyncpg) | ✅ Implementado (interno) |
| LLM (OpenAI / Azure OpenAI) | ✅ Implementado |
| Voz (ElevenLabs) | ✅ Implementado |
| Entra ID (validación JWT/JWKS) | ✅ Implementado |
| Webhooks entrantes | ❌ No existe |
| SMTP directo | ❌ No existe |

Dominios externos confirmados en código: `login.microsoftonline.com`, `graph.microsoft.com`, `*.sharepoint.com`, `api.openai.com` / `<recurso>.openai.azure.com`, `api.elevenlabs.io`. Ningún dominio adicional ni webhook. Sin ningún `verify=False` en ningún cliente HTTP del repositorio.

---

## 4. Matriz de controles (capa × estado)

| Capa | ✅ | 🟡 | 🔵 | ❌ |
|---|---|---|---|---|
| Autenticación, autorización, secretos, aislamiento | 14 | 1 | 1 | 0 |
| LLM, Presidio, motor conversacional, voz | 19 | 3 | 0 | 6 |
| Integraciones externas | 8 | 0 | 3 | 2 |
| Despliegue, infraestructura, procesos | 16 | 6 | 2 | 10 |
| Frontend, API, cadena de suministro | 9 | 4 | 0 | 4 |
| **Total** | **66** | **14** | **6** | **22** |

---

## 5. Hallazgos y hoja de ruta priorizada

### Prioridad alta (resolver antes de producción)

1. **Verificar en Exchange Online/Entra ID el alcance real del permiso de Graph Mail** — el código usa el buzón propio de la sesión, pero comprobar si los permisos app-only permiten técnicamente acceder a otros buzones; evaluar RBAC y permisos delegados. *(IT + desarrollador; no se puede verificar desde el repositorio)*.
2. **Corregir el comando del Container Apps Job de sincronización** en `infra/main.bicep:431` (`mia.sync` → `mia.ingestion.sync`). *(Desarrollador, esfuerzo: muy bajo)*.
3. **Añadir rate limiting** a `/api/chat/stream` y `/api/voice/stream`, al menos por usuario autenticado. *(Desarrollador, esfuerzo: medio)*.
4. **Activar Dependabot y un paso de escaneo de vulnerabilidades (pip-audit + npm audit) en CI.** *(Desarrollador, esfuerzo: bajo)*.
5. **Automatizar la instalación del modelo spaCy** en el Dockerfile/CI en vez de depender de un paso manual. *(Desarrollador, esfuerzo: bajo)*.
6. **Comunicar con claridad a las partes interesadas el alcance real de dominios**: RRHH implementado; Finanzas, Administración, Legal y Compliance no existen todavía. *(Gestión de expectativas, esfuerzo: ninguno — es una conversación, no código)*.

### Prioridad media

7. Declarar explícitamente en `infra/` o `docs/` los permisos de aplicación mínimos exactos requeridos en Graph/SharePoint (no depender solo de `.default`).
8. Añadir lockfile real para el backend Python (`uv.lock` o equivalente) y usarlo en CI.
9. Añadir cabeceras `Content-Security-Policy` y `Strict-Transport-Security`.
10. Añadir guardarraíl fail-closed en producción para `cors_origins` (igual que ya existe para auth/LLM/privacy gateway).
11. Aplicar el límite `max_files` de adjuntos (ya configurado, no usado).
12. Decidir si la voz debe filtrar PII general además de importes (extender `guard.clean_speech()` o aplicar `scan_text_for_pii()` al campo `habla`).
13. Decidir la vía de despliegue real para el modo `entra` (extender el bicep) o confirmar que Easy Auth es la vía definitiva de producción.
14. Evaluar separar el certificado de aplicación de SharePoint y Correo (hoy comparten uno).
15. Mover la generación de informes a Blob Storage en vez de `/tmp` del contenedor, dado `maxReplicas>1` en producción.

### Prioridad baja / a vigilar

16. Soporte de inglés en Presidio si se prevé contenido en ese idioma.
17. Puerta de código (no solo prompt) para la regla FIR-001 (firmas), igual que ya existe para nóminas/documentos médicos.
18. Escaneo antivirus/malware de adjuntos subidos.
19. Validar límite global de tamaño de body a nivel de aplicación.
20. Red privada (VNet/private endpoint) para PostgreSQL antes de producción con datos reales.
21. Escaneo dedicado de secretos en el historial completo de git (gitleaks/trufflehog) como verificación adicional.

---

## 6. Limitaciones de esta auditoría

- Es una auditoría **de código**, no una auditoría de la configuración real desplegada en Azure/Entra ID. Varios puntos (permisos de Graph realmente concedidos, etiquetado real de `MIA_ENVIRONMENT`, si Azure Front Door añade HSTS por delante) requieren verificación directa en el tenant/suscripción del cliente, fuera del alcance de este repositorio.
- No se ha ejecutado la aplicación ni se han lanzado pruebas de penetración; es un análisis estático.
- La comprobación de secretos en el historial de git fue acotada (grep sobre patrones conocidos), no un escaneo dedicado tipo gitleaks/trufflehog.
