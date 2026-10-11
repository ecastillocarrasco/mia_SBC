# 10 - Seguridad y Permisos

## Sistema de Permisos

Los permisos son un `StrEnum` en `auth/context.py`. Cada herramienta declara el permiso que exige. El motor filtra las tools antes de ofrecerlas al LLM: si el usuario no tiene el permiso, la tool es invisible para el modelo.

### Permissions disponibles

| Permission | Valor | Descripción |
|---|---|---|
| EMPLEADOS_LEER | `empleados:leer` | Datos de plantilla |
| TURNOS_LEER | `turnos:leer` | Turnos y ausencias |
| VACACIONES_LEER | `vacaciones:leer` | Solicitudes y saldos de vacaciones |
| NOMINAS_LEER | `nominas:leer` | Metadatos de nóminas (existencia, periodo) |
| NOMINAS_IMPORTES | `nominas:importes` | Importes reales de nóminas (PDF) |
| DOCUMENTOS_LEER | `documentos:leer` | Metadatos de documentos firmados |
| DOCUMENTOS_CONTENIDO | `documentos:contenido` | Contenido PDF de documentos |
| CURRICULUMS_LEER | `curriculums:leer` | CVs y candidaturas |
| TRABAJO_TEMPORAL_LEER | `trabajo_temporal:leer` | Datos de ETT |
| CORREO_LEER | `correo:leer` | Lectura del buzón |
| CORREO_ENVIAR | `correo:enviar` | Envío de correos (además de confirmación explícita) |
| INFORMES_GENERAR | `informes:generar` | Generar PDF/Excel/PPTX |
| PREDICCIONES_LEER | `predicciones:leer` | Reservado para módulo predictivo (sin tools activas aún) |
| ADMINISTRAR | `sistema:administrar` | Calidad de datos (admin only) |

---

## Roles y sus Permisos

| Rol (Entra ID App Role) | Permisos |
|---|---|
| `mia.admin` | TODOS los permisos |
| `mia.rrhh` | empleados, turnos, vacaciones, nóminas (leer+importes), documentos (leer+contenido), curriculums, correo (leer+enviar), informes, predicciones |
| `mia.seleccion` | solo curriculums + empleados |
| `mia.responsable` | empleados + turnos + vacaciones |

---

## Modos de Autenticación

| Modo | Descripción | Entorno válido |
|---|---|---|
| `dev` | Identidad fija configurable (dev-user, dev@localhost, rol mia.admin) | LOCAL, TEST, DEV (NUNCA producción) |
| `easyauth` | Identidad inyectada por Azure App Service Easy Auth (header X-MS-CLIENT-PRINCIPAL) | Producción en Azure App Service |
| `entra` | Valida JWT de Entra ID (firma, emisor, audiencia, expiración) usando JWKS públicas | Producción (cualquier hosting) |

La validación de producción en `settings.py` bloquea el arranque si auth.mode=dev en PRODUCTION.

---

## Dónde se Aplican los Permisos

1. **Middleware HTTP**: el `RequestContextMiddleware` resuelve el `UserContext` de cada petición.
2. **ToolRegistry.filtered_for(user)**: filtra el catálogo de tools antes de enviarlo al LLM.
3. **Tool handler**: cada handler puede verificar adicionalmente (p.ej. `NOMINAS_IMPORTES` en cada descarga de PDF).
4. **Correo (envío)**: además del permiso `CORREO_ENVIAR`, el motor exige confirmación explícita del usuario en el mensaje ("confirmo envía", "sí, envíalo") y `send_enabled=True` en settings.

---

## Protecciones de Datos Sensibles

| Dato sensible | Protección |
|---|---|
| DNI/NIE | Seudonimizado con HMAC (pseudonym_key) antes de guardarse en BD |
| Importes de nóminas | NUNCA guardados en BD; leídos del PDF en el momento |
| Estadísticas salariales | Solo para grupos de 5+ personas (NOM-004) |
| Ranking salarial | Solo con permiso NOMINAS_IMPORTES + auditoría; no se dice en voz alta |
| Contenido de documentos | Solo con DOCUMENTOS_CONTENIDO + content_enabled |
| Correo | Solo con CORREO_LEER; no persiste en BD |

---

## Auditoría

- Tabla `AuditEvent` en BD para cada acceso a datos sensibles
- Campos: user_id, action, resource, outcome, detail, created_at
- Resources auditados: `nominas_importes`, `nominas`, `documentos`, `vacaciones`, `correo`, `informes`, etc.
- No hay historial de modificaciones de datos (AuditEvent solo registra accesos, no cambios en SharePoint)

---

## CORS

Configurado en `main.py`:
```python
cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
```
Para producción debe configurarse con el dominio real del frontend.

---

## Riesgos de Seguridad Detectados

| Riesgo | Severidad | Estado |
|---|---|---|
| auth.mode=dev en producción | CRÍTICO | Bloqueado en arranque por validación |
| pseudonym_key por defecto en producción | ALTO | Bloqueado en arranque por validación |
| CORS permisivo (localhost) en producción | MEDIO | Requiere configuración manual |
| mia_local.db en directorio raíz del proyecto | MEDIO | Solo para desarrollo local; en producción usar PostgreSQL configurado |
| LLM fake en producción | CRÍTICO | Bloqueado en arranque |
| Correo: send_enabled=False por defecto | BIEN | El envío está desactivado por defecto |
| Importes en voz alta | BIEN | Guard filtra en código |
| Datos de salud laboral | N/A | No hay datos de salud en el sistema (riesgo futuro si se añaden) |

---

## Lo que NO puede hacer un usuario con permisos limitados

- Un usuario con solo `mia.responsable` NO puede ver nóminas, documentos, curriculums ni correo.
- Un usuario con solo `mia.seleccion` NO puede ver turnos, vacaciones ni nóminas.
- Ningún usuario puede hacer escritura en SharePoint (mIA es solo lectura).
- El envío de correo requiere permiso explícito Y confirmación en el turno.
