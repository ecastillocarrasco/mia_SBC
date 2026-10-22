# Guía de instalación y operación — mIA

Pensada para que el equipo de IT del cliente pueda instalar, operar y auditar mIA sin depender del desarrollador. Fuente: `docs/auditoria_arquitectura_mia.md`. El despliegue real objetivo de mIA es **Azure** (Container Apps, PostgreSQL Flexible Server, Key Vault) vía Infraestructura como Código (`infra/main.bicep`) — no un despliegue on-prem.

---

## 1. Prerrequisitos

### 1.1 Cuentas y recursos cloud

| Recurso | Propósito | SKU previsto |
|---|---|---|
| Resource Group de Azure | Contenedor de todos los recursos | — |
| Azure Container Apps Environment | Ejecuta la API y el job de sincronización | — |
| Azure Container App | Proceso principal (API) | Escalado mínimo 1 réplica, máximo 3 en producción |
| Azure Container Apps Job | Sincronización con SharePoint, cron cada 10 min | — |
| Azure Container Registry | Almacena la imagen Docker | `Basic`, sin login de administrador (acceso vía identidad) |
| PostgreSQL Flexible Server | Base de datos operativa | `Standard_B1ms` (⚠️ revisar si es suficiente para carga real de producción — es el mismo SKU mínimo tanto en dev como en el `.bicepparam` de producción) |
| Azure Key Vault | Todos los secretos | RBAC habilitado, soft-delete 30 días |
| User-Assigned Managed Identity | Identidad para Container App y Job, sin credenciales embebidas | — |
| Log Analytics Workspace | Logs centralizados | Retención 30 días |
| Application Insights | Telemetría (opcional, degrada con seguridad si no se configura) | — |
| Azure Storage Account | Destino previsto para informes generados (⚠️ ver nota en §6) | TLS 1.2 mínimo, sin acceso público ni claves compartidas |

### 1.2 Entra ID / Microsoft 365 (responsabilidad de IT del cliente)

- Un **App Registration** para mIA, con:
  - Certificado de aplicación para SharePoint/Graph (client-credentials, no secreto de cliente).
  - App Roles definidos y asignados a los usuarios/grupos correctos: `Global`, `RRHH`, `RRHH.NoNominas`, `Administracion`, `Legal` (mIA lee el claim `roles`, **nunca** `groups`).
  - Si se usa el modo de login `entra` (ver §7): `redirect URI` del frontend, scope expuesto para MSAL.
- **Consentimiento de administrador** a los permisos de aplicación de Graph/SharePoint — ver `docs/mIA_catalogo_integraciones.md` §4 para el detalle exacto.
- **Verificar/crear una Application Access Policy en Exchange Online** que acote el permiso de correo al buzón compartido de RRHH (hallazgo crítico, ver catálogo de integraciones §2.2) — sin esto, el permiso de aplicación puede dar acceso a todos los buzones del tenant.

### 1.3 Cuentas de terceros

| Proveedor | Para qué | Credencial |
|---|---|---|
| OpenAI o Azure OpenAI | Motor conversacional | API key (o recurso Azure OpenAI con su propia autenticación) |
| ElevenLabs | Síntesis de voz (opcional — `MIA_VOICE__PROVIDER=none` la desactiva) | API key |

### 1.4 Permisos de instalación vs. de ejecución

- **Instalación/despliegue**: quien ejecute `az deployment group create` necesita permisos de **Contributor** (o equivalente) sobre el Resource Group, y permisos para crear role assignments (`Owner` o `User Access Administrator`) para que el bicep pueda asignar los roles RBAC descritos en §1.1.
- **Ejecución**: el proceso de la aplicación corre bajo la Managed Identity, sin credenciales de usuario — no necesita (ni debe tener) permisos de administrador de la suscripción.

### 1.5 Conectividad

- Saliente (egress) necesario desde el Container App: `login.microsoftonline.com`, `graph.microsoft.com`, `*.sharepoint.com`, `api.openai.com` (o el endpoint de Azure OpenAI configurado), `api.elevenlabs.io` — todos sobre HTTPS/443.
- No se requiere ningún puerto de entrada (ingress) adicional al gestionado por Container Apps (HTTPS 443, `allowInsecure: false`).

### 1.6 Variables de entorno y secretos (nombres, nunca valores)

Ver `.env.example` en el repositorio para la lista completa. Los que son secretos reales (`SecretStr` en el código) y deben vivir en Key Vault:

`MIA_LLM__API_KEY`, `MIA_VOICE__API_KEY`, `MIA_SHAREPOINT__CERT_PFX_BASE64`, `MIA_SHAREPOINT__CERT_PFX_PASSWORD`, `MIA_DATA__PSEUDONYM_KEY`, `MIA_PRIVACY_GATEWAY__VAULT_KEY`, `MIA_OBSERVABILITY__APPLICATIONINSIGHTS_CONNECTION_STRING`.

---

## 2. Instaladores y dependencias

### 2.1 Qué se instala y con qué herramienta

```
┌─────────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│  pyproject.toml      │────▶│  pip wheel (Docker,   │────▶│  Imagen Docker      │
│  (rangos de versión) │     │  etapa "build")       │     │  (usuario no-root)  │
└─────────────────────┘     └──────────────────────┘     └────────────────────┘
                                                                     │
┌─────────────────────┐     ┌──────────────────────┐              ▼
│  frontend/package.json │──▶│  npm ci (lockfile)    │──▶  dist/ (estático,
│  + package-lock.json │     │  CI únicamente         │     no entra en la imagen
└─────────────────────┘     └──────────────────────┘      de la API)

┌─────────────────────┐
│  migrations/         │────▶ alembic upgrade head (al arrancar el contenedor,
│  (Alembic)            │     cada vez — no es un paso separado del arranque)
└─────────────────────┘
```

- **Backend**: `pip wheel --wheel-dir /wheels ".[azure]"` (`Dockerfile:7`) resuelve las dependencias de `pyproject.toml` en el momento del build. ⚠️ **No hay lockfile real** (ni `uv.lock` ni `requirements.txt` generado): dos builds del mismo commit pueden resolver versiones de parche distintas dentro de los rangos declarados.
- **Frontend**: `npm ci` en CI, que instala estrictamente desde `package-lock.json` — reproducible.
- **Modelo de NLP para Presidio** (`es_core_news_lg`, ~500 MB): ⚠️ **no se instala en ningún paso automatizado** (ni en `pyproject.toml`, ni en el Dockerfile, ni en CI). Es una dependencia manual pendiente de automatizar — sin ella, el Privacy Gateway (obligatorio en producción) fallará cerrado la primera vez que intente analizar texto real.
- **Verificación de integridad**: el frontend usa `npm ci` (verifica el lockfile); el backend no tiene un paso equivalente de verificación de hashes. No hay escaneo de vulnerabilidades (SCA) en ningún punto — ver hallazgo en la auditoría.

### 2.2 Orden de instalación

1. Aprovisionar infraestructura: `az deployment group create -g <grupo> -f infra/main.bicep -p infra/main.prod.bicepparam` (con las variables de entorno de secretos del paso de CI/CD ya definidas — ver `infra/main.prod.bicepparam`, que las lee con `readEnvironmentVariable(...)`, nunca hardcodeadas).
2. Construir y publicar la imagen Docker al Container Registry creado en el paso 1.
3. Desplegar/actualizar el Container App y el Container Apps Job para que apunten a esa imagen.
4. Las migraciones (`alembic upgrade head`) se ejecutan automáticamente en cada arranque del contenedor — no es un paso manual separado.
5. ⚠️ **Antes de considerar el job de sincronización operativo**: corregir el comando `python -m mia.sync` → `python -m mia.ingestion.sync` en `infra/main.bicep:431` (hallazgo confirmado — el módulo actual no existe en el paquete desplegado y el job fallará en cada ejecución tal como está).

### 2.3 Diferencias entre entornos

| | Desarrollo local | Dev (Azure) | Producción (Azure) |
|---|---|---|---|
| Auth | `dev` (identidad fija) permitido | `dev`/`easyauth` según config | `dev` **bloqueado por código** — exige `easyauth` o `entra` |
| Privacy Gateway | Puede estar desactivado | Puede estar desactivado | **Obligatorio activo**, bloqueado al arrancar si no |
| LLM | Puede ser `fake` (sin coste) | — | `fake` **prohibido**, bloqueado al arrancar |
| Clave de seudonimización | Valor de desarrollo permitido | — | Valor de desarrollo **bloqueado**, exige clave real de Key Vault |
| Easy Auth | No aplica | Opcional | Exigido — sin `easyAuthClientId`, la app no arranca |

---

## 3. Guía de instalación paso a paso (comandos reales del repo)

```powershell
# 1. Aprovisionar infraestructura (una vez, o para actualizarla)
az group create -n <nombre-grupo> -l spaincentral
$env:MIA_PG_ADMIN_PASSWORD = "..."      # desde un gestor de secretos del pipeline, nunca en texto plano
$env:MIA_LLM_API_KEY = "..."
az deployment group create -g <nombre-grupo> -f infra/main.bicep -p infra/main.prod.bicepparam

# 2. Build y push de la imagen (en el pipeline de CI/CD)
docker build -t <registro>.azurecr.io/mia:<tag> .
docker push <registro>.azurecr.io/mia:<tag>

# 3. Verificación tras el despliegue
curl https://<container-app-url>/health/live     # 200 esperado, sin dependencias externas
curl https://<container-app-url>/health/ready     # 200 esperado, confirma conexión real a PostgreSQL

# 4. Verificar el job de sincronización (tras corregir el comando, ver §2.2 punto 5)
az containerapp job start -g <nombre-grupo> -n caj-mia-sync
az containerapp job logs show -g <nombre-grupo> -n caj-mia-sync
```

Verificación tras cada fase:
- Tras el paso 1: confirmar en el Portal de Azure que Key Vault tiene los 7 secretos esperados y que la Managed Identity tiene los roles RBAC (`Key Vault Secrets User`, `AcrPull`, `Storage Blob Data Contributor`).
- Tras el paso 3: `/health/ready` debe devolver 200 — si falla, revisar que las migraciones se aplicaron (`alembic upgrade head` corre en el arranque del contenedor, visible en los logs del Container App).
- Tras el paso 4: revisar que el log no contenga `ModuleNotFoundError` (sería el hallazgo del §2.2 sin corregir).

---

## 4. Procesos y servicios en ejecución

| Proceso | Comando / definición | Puerto | Identidad | Healthcheck | Reinicio |
|---|---|---|---|---|---|
| API (Container App) | `uvicorn --factory mia.main:create_app --host 0.0.0.0 --port 8000` (tras `alembic upgrade head`), `Dockerfile:22` | 8000 (interno; HTTPS 443 expuesto por Container Apps) | Managed Identity, usuario de sistema no-root (`uid 10001`) | `/health/live` (Docker), `/health/ready` (Container Apps readiness) | Automático (gestionado por Container Apps) |
| Job de sincronización | `python -m mia.ingestion.sync` (⚠️ corregir en bicep, ver §2.2) | — | Misma Managed Identity | — (job programado, no servicio de larga duración) | Cron `*/10 * * * *`; sincronización completa diaria a las 03:00 decidida internamente |
| Limpieza de adjuntos | Bucle interno en el mismo proceso de la API (`start_cleanup`), cada hora si `MIA_ATTACHMENTS__ENABLED=true` | — | Mismo proceso | — | Vive con el proceso de la API |
| Worker de informes masivos | Desactivado por defecto (`MIA_JOBS__ENABLED=false`), no activado en ningún `.bicepparam` actual | — | — | — | — |

### Mapa de red (resumen)

- **Entrada**: solo HTTPS 443 al Container App, gestionado por el ingress de Container Apps (`allowInsecure: false`).
- **Salida**: HTTPS 443 a los 5 dominios externos listados en `docs/mIA_catalogo_integraciones.md` §1, más PostgreSQL (interno, TLS forzado por cadena de conexión `?ssl=require`).
- **PostgreSQL**: regla de firewall `AllowAzureServices` (acceso desde servicios de Azure, no desde Internet abierto); **sin red privada (VNet/private endpoint) todavía** — reconocido como pendiente en el propio código de infraestructura.

---

## 5. Arranque, parada y operación

- **Arranque**: gestionado por Azure Container Apps (no hay un paso manual de "arrancar el servidor"); al iniciar cada réplica, se ejecutan las migraciones y luego uvicorn.
- **Parada**: escalado a 0 réplicas (si se permite) o eliminación del Container App — no hay un procedimiento de apagado ordenado específico más allá del que gestiona la plataforma.
- **Actualizaciones**: nueva imagen Docker → nueva revisión del Container App. Las migraciones se aplican automáticamente en el arranque de cada revisión.
- **Rollback**: Container Apps mantiene revisiones anteriores; rollback = volver a la revisión previa. ⚠️ Esto no revierte migraciones de base de datos — si una actualización incluyó una migración incompatible, el rollback de código por sí solo no es suficiente.
- **Tareas programadas**: únicamente el job de sincronización (cron cada 10 min). No hay otras tareas cron activas en la configuración actual.

---

## 6. Hardening de la instalación — qué ya está y qué falta

| Práctica | Estado |
|---|---|
| Mínimo privilegio en roles RBAC de Azure (Key Vault Secrets User, AcrPull, Storage Blob Data Contributor) | ✅ Implementado |
| Contenedor sin root | ✅ Implementado |
| Puertos mínimos expuestos (solo 8000/443) | ✅ Implementado |
| Secretos fuera de la línea de comandos y del bicep (Key Vault + Managed Identity) | ✅ Implementado |
| Versiones de dependencias fijadas (lockfile) | 🟡 Frontend sí (`package-lock.json` + `npm ci`) · ❌ Backend no |
| Escaneo de vulnerabilidades (SCA) en CI | ❌ No existe — pendiente añadir (pip-audit, npm audit, Dependabot) |
| Escaneo de imagen de contenedor | ❌ No existe |
| Firmado de imágenes | ❌ No existe |
| Red privada para PostgreSQL | 🔵 Planificado, no implementado |
| Alertas automatizadas sobre logs/telemetría | ❌ No existe — hay visibilidad (Log Analytics/App Insights), no reacción automática |
| Destino de informes generados en almacenamiento persistente compartido | 🟡 Hoy en `/tmp` del contenedor — revisar con múltiples réplicas en producción (el Storage Account ya existe y tiene permisos concedidos, pero no está conectado) |

---

## 7. Checklist previo al paso a producción

Producción es el último paso y todavía no hay nada contratado — esta checklist es la condición para llegar a ese punto, no una lista ya completada:

- [ ] Confirmar en Exchange Online la Application Access Policy que acota el permiso de correo al buzón de RRHH (crítico).
- [ ] Confirmar en Entra ID el alcance exacto de los permisos de aplicación de SharePoint (`Sites.Selected` recomendado).
- [ ] Corregir el comando del Container Apps Job de sincronización (`mia.sync` → `mia.ingestion.sync`).
- [ ] Decidir y desplegar la vía de login real: Easy Auth (ya soportado en el bicep) o extender la infraestructura para el modo `entra` (ya implementado en código, no conectado).
- [ ] Automatizar la instalación del modelo spaCy en el pipeline de build.
- [ ] Añadir rate limiting a `/api/chat/stream` y `/api/voice/stream`.
- [ ] Activar Dependabot y un paso de escaneo de vulnerabilidades en CI.
- [ ] Decidir el SKU real de PostgreSQL para la carga esperada (hoy `Standard_B1ms` en ambos `.bicepparam`, sin alta disponibilidad).
- [ ] Confirmar contractualmente (DPA) con OpenAI/Azure OpenAI y ElevenLabs: región de procesamiento, retención, uso para entrenamiento.
- [ ] Decidir la política de retención de logs y si se integra con el SIEM del cliente, si existe.
- [ ] Revisar el alcance real de dominios: comunicar con claridad que solo RRHH está implementado hoy (Finanzas/Administración/Legal/Compliance no existen todavía).

---

## 8. RACI por capa y control

| Control / capa | IT del cliente | Desarrollador | Compartido |
|---|---|---|---|
| Tenant Microsoft 365 / Entra ID (App Registration, consentimiento de administrador) | **R/A** | Consultor técnico | — |
| Application Access Policy de Exchange Online | **R/A** | — | — |
| Grupos y asignación de App Roles a usuarios | **R/A** | — | — |
| Suscripción de Azure, cuotas, costes | **R/A** | — | — |
| Red / firewall / DNS | **R/A** | Especifica requisitos | — |
| Key Vault — creación y rotación de secretos | — | Diseña el mecanismo | **R/A compartido** (IT rota, desarrollador define qué rotar) |
| Código de la aplicación, correcciones, nuevas funcionalidades | — | **R/A** | — |
| Infraestructura como código (`infra/main.bicep`) | Aprueba cambios | **R/A** (autor) | — |
| Parcheo de dependencias / CVEs | — | **R/A** | Notifica a IT si requiere ventana de mantenimiento |
| Copias de seguridad de PostgreSQL | Azure las gestiona (retención configurada en bicep) | Define la retención necesaria | **Compartido** |
| Monitorización y alertas | **R/A** (debe configurarlas; hoy no existen) | Provee los datos (logs/telemetría) | — |
| Respuesta a incidentes | **R/A** (proceso del cliente) | Soporte técnico bajo demanda | **Compartido** |
| Aprobación de proveedores externos (OpenAI, ElevenLabs) | **R/A** (legal/compras) | Proporciona información técnica | — |
| Acceso a Conectia/A3 (cuando se implemente) | **R/A** | Implementa el conector | — |

*(R = Responsable de ejecutar, A = Aprueba/rinde cuentas)*

---

## 9. Qué necesito de IT — lista priorizada

1. **Consentimiento de administrador** a los permisos de aplicación de Graph/SharePoint del App Registration de mIA — sin esto, la sincronización y el correo no funcionan.
2. **Confirmación o creación de la Application Access Policy de Exchange Online** que acota el permiso de correo al buzón de RRHH — crítico de seguridad, ver catálogo de integraciones.
3. **Grupos de usuarios y App Roles**: decidir qué personas/grupos reciben cada rol (`RRHH`, `RRHH.NoNominas`, `Administracion`, `Legal`) en el App Registration.
4. **Suscripción de Azure y cuotas**: resource group, presupuesto aprobado, SKU de PostgreSQL para la carga real esperada.
5. **Reglas de red/firewall**: confirmar que el egress HTTPS a los 5 dominios externos (§1.5) está permitido desde el entorno Azure del cliente si hay restricciones de red corporativas adicionales (p. ej. Azure Firewall con allow-list de FQDN).
6. **Aprobación de proveedores externos** (OpenAI/Azure OpenAI, ElevenLabs): revisión legal/DPA antes de procesar datos reales de empleados.
7. **Acceso a Conectia/A3**: credenciales y documentación de API, cuando el cliente decida priorizar esa integración (hoy no implementada).
8. **Decisión sobre el SIEM**: si existe uno corporativo, decidir si Application Insights/Log Analytics se integra con él.

---

## 10. Propiedad y traspaso

- **Código**: repositorio Git (ubicación según acuerdo con el cliente — hoy en el entorno de desarrollo del proveedor).
- **Secretos**: viven en Azure Key Vault, dentro de la suscripción del cliente — el cliente es propietario y puede rotarlos/revocarlos sin depender del desarrollador.
- **Documentación**: esta guía, el catálogo de integraciones y la auditoría de arquitectura (`docs/`) están pensados para que IT pueda operar sin el desarrollador.
- **Si el desarrollador deja de dar soporte**: IT necesita (a) acceso administrativo a la suscripción de Azure (ya debería ser del cliente, no del desarrollador), (b) acceso al repositorio de código, (c) esta documentación actualizada, (d) ningún secreto ni cuenta de servicio debe depender de una cuenta personal del desarrollador — confirmar explícitamente que esto es así antes del traspaso.

---

## 11. Soporte y cambios

- **Incidentes**: canal a definir con el cliente (no existe hoy un proceso formal documentado en el repositorio).
- **Actualizaciones de código**: vía el pipeline de CI/CD existente (`.github/workflows/ci.yml`) — el despliegue a Azure es manual hoy, no automatizado desde CI.
- **Cambios de permisos/alcance**: cualquier cambio en los permisos de aplicación de Graph/SharePoint requiere nuevo consentimiento de administrador de IT.
- **Ventanas de mantenimiento**: a definir — no hay ventana establecida en la configuración actual (las migraciones se aplican en cada arranque, sin downtime explícito gestionado, aunque Container Apps hace rolling updates).
