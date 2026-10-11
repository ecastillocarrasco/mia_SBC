# 08 - Fuentes de Datos

## Mapa de Fuentes

```
SharePoint (RRHH site) ──┐
                         ├─→ ingestion/mappers/hr.py → PostgreSQL → Tool → Dominio → Respuesta
SharePoint (Portal) ─────┤
Microsoft Graph ─────────┘ (correo: no sincronizado, acceso directo en tiempo real)
```

---

## SharePoint:Empleados

| Atributo | Valor |
|---|---|
| Lista SP | Empleados |
| Sincronización | Periódica (full sync diaria a las 3AM, incremental cada 30 min) |
| Modelo BD | `Employee` (data/hr.py) |
| Campos disponibles | name, position, department, department_key, email, person_key (DNI seudonimizado), active, birth_date, manager_name, employee_code, nationality |
| Campos NO disponibles | género, hire_date, contract_type, jornada, discapacidad, fecha_fin_contrato |
| Auth | Certificado PFX/PEM de la app en Entra ID |
| Disponibilidad | Requiere configuración completa (tenant_id, client_id, cert, rrhh_site_url) |
| Cuellos de botella | Sincronización puede tardar si la lista es grande (page_size=2000, concurrency=4) |

---

## SharePoint:Turnos

| Atributo | Valor |
|---|---|
| Lista SP | Turnos (turnos publicados por departamento/semana) |
| Sincronización | Periódica |
| Modelo BD | `ShiftDay` |
| Campos disponibles | employee_name, department, day, kind (TRABAJO/DESCANSO/BAJA/VACACIONES/PERMISO...), start_time, end_time, hours |
| Datos NO disponibles | fichajes reales, horas extras, incidencias en tiempo real |
| Auth | Misma app que Empleados |

---

## SharePoint:Vacaciones

| Atributo | Valor |
|---|---|
| Lista SP | Vacaciones (solicitudes) + VacationBalance (saldos) |
| Sincronización | Periódica |
| Modelos BD | `Vacation`, `VacationBalance` |
| Campos disponibles | employee_email, employee_name, department_key, start_date, end_date, status, request_type, total_days |
| Limitación | Solo vacaciones y asuntos propios; permisos especiales (matrimonio, maternidad) no modelados |

---

## SharePoint:Nominas

| Atributo | Valor |
|---|---|
| Lista SP | Nominas (metadatos de documentos PDF) |
| Sincronización | Metadatos periódicamente; PDFs on-demand |
| Modelo BD | `Payslip` |
| Campos disponibles | person_key, employee_email, period, year, month, special, read, file_name, label, sp_id |
| Importes | NUNCA en BD; se leen del PDF en el momento con `content_enabled=True` |
| Parser | `nominas/parser.py` extrae: devengado, deducciones, líquido, IRPF, conceptos salariales, SS-empresa |
| Auth | Misma app + permiso NOMINAS_IMPORTES para descargar PDFs |

---

## SharePoint:DocumentosFirmados

| Atributo | Valor |
|---|---|
| Lista SP | DocumentosFirmados |
| Sincronización | Periódica |
| Modelo BD | `SignedDocument` |
| Campos disponibles | employee_sp_id, employee_name, document_type, date, sp_id |
| Campos NO disponibles | fecha_expiración |
| Contenido PDF | On-demand con content_enabled + DOCUMENTOS_CONTENIDO |

---

## SharePoint:Calendarios

| Atributo | Valor |
|---|---|
| Lista SP | Calendarios (histórico de turnos reales, tipos, plantillas, comentarios) |
| Sincronización | Periódica |
| Modelos BD | `CalendarShift`, `ShiftType`, `ShiftTemplate`, `ShiftComment` |
| Uso | Histórico de horas reales, auditoría publicado vs real, disponibilidad por día |

---

## SharePoint:ETT (Trabajo Temporal)

| Atributo | Valor |
|---|---|
| Listas SP | TtWorker, TtTimesheet, TtCompany, TtRate, TtCommunication |
| Sincronización | Periódica |
| Modelos BD | `TtWorker`, `TtTimesheet`, `TtCompany`, `TtRate`, `TtCommunication` |
| Campos disponibles | worker.name, company, department, visible; timesheet.day, hours_total, amount, worker_id |
| Limitación | Sin módulo de presupuesto ETT |

---

## SharePoint:Candidaturas

| Atributo | Valor |
|---|---|
| Lista SP | Candidaturas (CVs de candidatos) |
| Sincronización | Periódica (index_batch=200) con indexación de embeddings |
| Modelo BD | `Candidate` + índice vectorial |
| Campos disponibles | name, position, cv_text, embeddings |
| Búsqueda | Semántica (vector similarity) + keywords |
| Limitación | disponibilidad_inmediata y fecha_candidatura dependen de metadatos opcionales |

---

## SharePoint:Portal

| Atributo | Valor |
|---|---|
| Uso | Solo para sincronizar maestro de tipos documentales |
| Configuración | `MIA_SHAREPOINT__PORTAL_SITE_URL` (opcional; si vacío no se sincroniza) |

---

## Microsoft Graph (Correo)

| Atributo | Valor |
|---|---|
| Endpoint | Microsoft Graph API /v1.0/users/{mailbox}/messages |
| Auth | Misma app (certificado) con permisos Graph Mail.Read + Mail.Send |
| Sincronización | NO (acceso directo en tiempo real) |
| Modelo BD | NO (nunca se persiste el correo) |
| Configuración | `MIA_MAIL__MAILBOX` o modo `user` (buzón del usuario autenticado) |
| Limitación | Sin configuración, todo el dominio correo devuelve SOURCE_UNAVAILABLE |

---

## Base de Datos Local (PostgreSQL / SQLite tests)

| Tabla | Contenido |
|---|---|
| `conversation_sessions` | Estado conversacional por sesión/usuario |
| `conversation_turns` | Historial de turnos (MAX_HISTORY=12) |
| `audit_events` | Registro de accesos a datos sensibles (RGPD/ENS) |
| `reports` | Metadatos de informes generados (ID, path, TTL) |
| Tablas HR | Todas las entidades sincronizadas desde SharePoint |

---

## Resumen de Disponibilidad

| Fuente | Configurable | Activa en dev (sin config) | Impacto si no disponible |
|---|---|---|---|
| SharePoint:Empleados | Con cert+URL | No (SOURCE_UNAVAILABLE) | 60% de tools caen |
| SharePoint:Turnos | Con cert+URL | No | Turnos, ausencias, horas |
| SharePoint:Vacaciones | Con cert+URL | No | Vacaciones, saldos |
| SharePoint:Nominas | Con cert+URL | No | Nóminas |
| SharePoint:DocumentosFirmados | Con cert+URL | No | Documentos |
| SharePoint:Calendarios | Con cert+URL | No | Histórico turnos |
| SharePoint:ETT | Con cert+URL | No | Trabajo temporal |
| SharePoint:Candidaturas | Con cert+URL | No | Curriculums |
| Microsoft Graph | Con mailbox | No | Todo el dominio correo |
| PostgreSQL | Con DATABASE_URL | SQLite local (tests) | Sin BD, no arranca |
| LLM (OpenAI) | Con API key | Fake (solo tests) | Sin LLM no funciona el chat |
| ElevenLabs (voz) | Con API key | Desactivado (NONE) | Sin voz, solo texto |
