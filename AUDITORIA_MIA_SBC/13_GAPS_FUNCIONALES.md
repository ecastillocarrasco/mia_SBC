# 13 - Gaps Funcionales

## EMPLEADOS

| Funcionalidad | Estado |
|---|---|
| Búsqueda y ficha de empleados | YA TENEMOS ✅ |
| Organigrama y estructura | YA TENEMOS ✅ |
| Demografía (edad, franja, cumpleaños) | YA TENEMOS ✅ |
| Directorio de contactos | YA TENEMOS ✅ |
| Responsables por departamento | YA TENEMOS ✅ |
| Altas recientes | YA TENEMOS ✅ |
| Empleados próximos a jubilación | YA TENEMOS ✅ (proximos_jubilacion) |
| Antigüedad / años en empresa | NOS FALTA 🔴 — sin hire_date en Employee |
| Tipo de contrato (indefinido/temporal) | NOS FALTA 🔴 — sin contract_type |
| Jornada (completa/parcial) | NOS FALTA 🔴 — sin campo jornada |
| Género / estadísticas de género | NOS FALTA 🔴 — sin campo género |
| Vencimiento de contratos | NOS FALTA 🔴 — sin fecha_fin_contrato |
| Discapacidad reconocida | NOS FALTA 🔴 — datos sensibles, sin campo |
| Reducción de jornada | NOS FALTA 🔴 — sin tipo_jornada |
| Plan de igualdad | NOS FALTA 🔴 — sin género + sin módulo |
| Historial de cambios del empleado | NOS FALTA 🔴 — AuditEvent solo registra accesos |

---

## TURNOS

| Funcionalidad | Estado |
|---|---|
| Turnos publicados (persona/día/franja/hora) | YA TENEMOS ✅ |
| Ausencias (baja/permiso/vacaciones) | YA TENEMOS ✅ |
| Reincorporaciones | YA TENEMOS ✅ |
| Horas trabajadas calculadas | YA TENEMOS ✅ |
| Compañeros de turno | YA TENEMOS ✅ |
| Histórico de turnos reales (Calendario) | YA TENEMOS ✅ |
| Auditoría planificado vs real | YA TENEMOS ✅ |
| Disponibilidad cruzada día | YA TENEMOS ✅ |
| Absentismo y tendencias | YA TENEMOS ✅ |
| Cobertura semanal | YA TENEMOS ✅ |
| Control de presencia / fichajes | NOS FALTA 🔴 — sin integración |
| Horas extras diferenciadas | NOS FALTA 🔴 — sin campo en modelo |
| Calendario laboral / festivos convenio | NOS FALTA 🔴 — sin módulo |
| Restricciones médicas en turno | NOS FALTA 🔴 — sin datos salud laboral |

---

## VACACIONES

| Funcionalidad | Estado |
|---|---|
| Solicitudes por estado | YA TENEMOS ✅ |
| Saldos de vacaciones | YA TENEMOS ✅ |
| Reincorporación de vacaciones | YA TENEMOS ✅ |
| Analítica de distribución | YA TENEMOS ✅ |
| Conflictos/solapamientos en departamento | YA TENEMOS ✅ (conflictos_vacaciones) |
| Asuntos propios | YA TENEMOS ✅ |
| Permisos especiales (matrimonio, maternidad) | NOS FALTA 🔴 — sin tipos especiales modelados |
| Reglas de plantilla mínima | TENEMOS PARCIALMENTE 🟡 — informa solapamientos pero no aplica reglas de mínimos automáticamente |
| Aprobación/rechazo de solicitudes | NOS FALTA 🔴 — solo lectura |

---

## NÓMINAS

| Funcionalidad | Estado |
|---|---|
| Metadatos (existencia, periodo, lectura) | YA TENEMOS ✅ |
| Detección de anomalías (duplicados, faltantes, huérfanos) | YA TENEMOS ✅ (anomalias_nominas) |
| Importes individuales (líquido, devengado, IRPF) | TENEMOS (requiere permisos + config) 🟡 |
| Conceptos salariales desglosados | TENEMOS (requiere permisos + config) 🟡 (parse_concepts) |
| SS-empresa | TENEMOS (requiere permisos + config) 🟡 (parse_employer_ss) |
| Estadísticas salariales (media, mediana, percentiles) | TENEMOS (requiere permisos + config) 🟡 |
| Ranking salarial | TENEMOS (requiere permisos + config) 🟡 |
| Evolución interanual de un empleado | TENEMOS (requiere permisos + config) 🟡 |
| Suma total de nóminas empresa sin restricción | NOS FALTA 🔴 — NOM-004 prohíbe grupos <5; sin suma global explícita |
| Coste total de personal por empresa | TENEMOS PARCIALMENTE 🟡 — estadisticas_salariales suma coste_total_empresa pero requiere permisos |
| Presupuesto de personal | NOS FALTA 🔴 — sin datos de presupuesto |

---

## DOCUMENTOS

| Funcionalidad | Estado |
|---|---|
| Inventario de documentos firmados | YA TENEMOS ✅ |
| Documentos faltantes | YA TENEMOS ✅ |
| Cobertura documental | YA TENEMOS ✅ |
| Maestros documentales | YA TENEMOS ✅ |
| Lectura de contenido PDF | TENEMOS (requiere permisos + config) 🟡 |
| Fecha de expiración de documentos | NOS FALTA 🔴 — sin campo en modelo |
| Notificaciones de documentos próximos a vencer | NOS FALTA 🔴 — sin fecha expiración + sin módulo notificaciones |

---

## CORREO

| Funcionalidad | Estado |
|---|---|
| Lectura de buzón (sin leer, búsqueda, contenido) | TENEMOS (requiere Graph) 🟡 |
| Borradores (crear, modificar, descartar) | TENEMOS (requiere Graph) 🟡 |
| Envío (con confirmación) | TENEMOS (requiere Graph + send_enabled) 🟡 |
| Marcar como leído | NOS FALTA 🔴 |
| Recordatorios programados | NOS FALTA 🔴 — guard prohíbe promesas |
| Gestión de carpetas | NOS FALTA 🔴 |
| Reglas de correo | NOS FALTA 🔴 |

---

## CURRICULUMS

| Funcionalidad | Estado |
|---|---|
| Búsqueda semántica de candidatos | YA TENEMOS ✅ |
| Candidatos similares (vector) | YA TENEMOS ✅ |
| Candidaturas por puesto/recuento | YA TENEMOS ✅ |
| Ficha de candidato | YA TENEMOS ✅ |
| Cruce candidatos-plantilla | YA TENEMOS ✅ |
| Ranking por idoneidad | NOS FALTA 🔴 (SEL-001 — por diseño) |
| Candidatos con discapacidad | NOS FALTA 🔴 — sin campo |
| Pipeline de selección (fases) | NOS FALTA 🔴 — sin módulo |
| Programación de entrevistas | NOS FALTA 🔴 — sin integración calendario |

---

## TRABAJO TEMPORAL

| Funcionalidad | Estado |
|---|---|
| Trabajadores ETT y empresas | YA TENEMOS ✅ |
| Boletines de horas | YA TENEMOS ✅ |
| Boletines faltantes | YA TENEMOS ✅ (boletines_faltantes_tt) |
| Anomalías (duplicados, 0 horas, >12h) | YA TENEMOS ✅ |
| Estimación de coste | YA TENEMOS ✅ |
| Variación de coste entre periodos | YA TENEMOS ✅ (variacion_coste_tt) |
| Comunicaciones y tarifas | YA TENEMOS ✅ |
| Presupuesto ETT / control desviación | NOS FALTA 🔴 — sin datos de presupuesto |

---

## ANALÍTICA

| Funcionalidad | Estado |
|---|---|
| Panel ejecutivo multi-dominio | YA TENEMOS ✅ |
| Ficha 360 departamento | YA TENEMOS ✅ |
| Comparación de departamentos | YA TENEMOS ✅ |
| Consulta cruzada multi-criterio | YA TENEMOS ✅ |
| Tendencias de absentismo | YA TENEMOS ✅ |
| Ranking de absentismo | YA TENEMOS ✅ |
| Próximos a jubilación | YA TENEMOS ✅ |
| Estadísticas salariales | TENEMOS PERO NO APROVECHAMOS sin configuración 🟡 |
| Análisis de género/igualdad | NOS FALTA 🔴 — sin campo género |
| Correlaciones estadísticas | NOS FALTA 🔴 — sin módulo predictivo conectado |
| Forecasting de plantilla | NOS FALTA 🔴 — módulo analytics/ no conectado |
| KPIs de productividad | NOS FALTA 🔴 — sin datos operativos |

---

## FINANZAS

| Funcionalidad | Estado |
|---|---|
| Facturación / ingresos | NOS FALTA 🔴 — sin fuente de datos |
| Contabilidad / resultado | NOS FALTA 🔴 — sin fuente de datos |
| Tesorería | NOS FALTA 🔴 — sin fuente de datos |
| Presupuestos | NOS FALTA 🔴 — sin fuente de datos |
| Proveedores | NOS FALTA 🔴 — sin fuente de datos |
| Ratio coste personal/ingresos | NOS FALTA 🔴 — sin ingresos |

---

## Funcionalidades "tenemos pero no aprovechamos"

Estas funcionalidades están implementadas pero requieren configuración que puede no estar activa:

1. **Estadísticas salariales y ranking** — Implementadas con percentiles, suma, media, mediana, SS-empresa. Solo disponibles con `content_enabled=True` y permiso `NOMINAS_IMPORTES`. En demo sin SharePoint no se puede ver.

2. **Lectura de contenido de documentos** — `leer_documento` implementado. Solo con `content_enabled=True` y permiso `DOCUMENTOS_CONTENIDO`.

3. **Correo completo** — 8 tools implementadas. Solo con Graph API configurada.

4. **Módulo predictivo** — Infraestructura en `analytics/` creada. Sin conectar al conversacional.

5. **ElevenLabs voice** — Implementado. Sin configurar en dev (provider=none).

6. **Búsqueda semántica de candidatos** — Implementada con embeddings. Si el índice no está precargado, la primera búsqueda puede ser lenta o fallar.
