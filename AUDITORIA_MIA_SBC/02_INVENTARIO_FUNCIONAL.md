# 02 - Inventario Funcional

**Total de tools registradas:** ~82 (conteo exacto por dominio abajo)

---

## SISTEMA (3 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `capacidades` | Qué puede hacer mIA ahora mismo | ninguno | BD local |
| `operar_resultado` | Filtrar/ordenar/agrupar/columnas/primeros sobre último resultado | ninguno | sesión |
| `cruzar_resultados` | Unión, intersección, diferencia entre dos resultados | ninguno | sesión |

---

## EMPLEADOS (8 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `buscar_empleado` | Búsqueda por nombre/apellido/código | EMPLEADOS_LEER | SharePoint:Empleados |
| `ficha_empleado` | Ficha completa de un empleado | EMPLEADOS_LEER | SharePoint:Empleados |
| `plantilla` | Listado/recuento con filtros por dept/puesto/estado | EMPLEADOS_LEER | SharePoint:Empleados |
| `estructura_departamentos` | Organigrama y departamentos | EMPLEADOS_LEER | SharePoint:Empleados |
| `perfil_edad` | Distribución de edad de la plantilla | EMPLEADOS_LEER | SharePoint:Empleados |
| `cumpleanos` | Quién cumple años en un periodo | EMPLEADOS_LEER | SharePoint:Empleados |
| `responsables` | Responsables por departamento | EMPLEADOS_LEER | SharePoint:Empleados |
| `contactos_organizacion` | Emails y extensiones por departamento | EMPLEADOS_LEER | SharePoint:Empleados |

---

## TURNOS (13 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `turnos_persona` | Turnos de una persona por semana | TURNOS_LEER | SharePoint:Turnos |
| `turnos_dia` | Quién trabaja un día/hora/franja | TURNOS_LEER | SharePoint:Turnos |
| `ausencias` | Bajas, permisos, vacaciones activas | TURNOS_LEER | SharePoint:Turnos |
| `reincorporaciones` | Próximas reincorporaciones | TURNOS_LEER | SharePoint:Turnos |
| `horas_trabajadas` | Horas de una persona en un periodo | TURNOS_LEER | SharePoint:Turnos |
| `companeros_de_turno` | Compañeros en el turno de una persona | TURNOS_LEER | SharePoint:Turnos |
| `turnos_historico` | Turnos reales pasados del Calendario | TURNOS_LEER | SharePoint:Calendarios |
| `catalogo_tipos_turno` | Tipos de turno definidos | TURNOS_LEER | SharePoint:Calendarios |
| `plantillas_turno` | Plantillas asignadas a personas | TURNOS_LEER | SharePoint:Calendarios |
| `comentarios_semana_turno` | Comentarios de semana del Calendario | TURNOS_LEER | SharePoint:Calendarios |
| `metricas_turnos` | Métricas de horas reales históricas | TURNOS_LEER | SharePoint:Calendarios |
| `auditoria_publicacion_turnos` | Discrepancias planificado vs real | TURNOS_LEER | SharePoint:Calendarios |
| `disponibilidad_dia` | Disponibilidad cruzando calendario, vacaciones y ETT | TURNOS_LEER | SharePoint:Calendarios+Vacaciones+ETT |

---

## VACACIONES (4 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `vacaciones` / `solicitudes` | Solicitudes por estado/tipo/persona/periodo | VACACIONES_LEER | SharePoint:Vacaciones |
| `saldo_vacaciones` / `saldos` | Saldos de vacaciones por persona/departamento | VACACIONES_LEER | SharePoint:Vacaciones |
| `reincorporacion` | Cuándo vuelve una persona de vacaciones/baja | VACACIONES_LEER | SharePoint:Vacaciones+Turnos |
| `conflictos_vacaciones` | Solapamientos en el departamento para un periodo | VACACIONES_LEER | SharePoint:Vacaciones |

---

## NÓMINAS (7 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `nominas_persona` | Documentos de nómina (metadatos) de una persona | NOMINAS_LEER | SharePoint:Nominas |
| `nominas_periodo` | Cobertura de nóminas de un mes (quién no tiene) | NOMINAS_LEER | SharePoint:Nominas |
| `anomalias_nominas` | Duplicados, faltantes y huérfanos en un periodo | NOMINAS_LEER | SharePoint:Nominas |
| `nomina_importes` | Importes del PDF de una nómina (liquido, IRPF, conceptos) | NOMINAS_IMPORTES | SharePoint:Nominas (PDF) |
| `evolucion_nominas` | Evolución mensual de importes de una persona (con comparación interanual) | NOMINAS_IMPORTES | SharePoint:Nominas (PDF) |
| `estadisticas_salariales` | Media, mediana, percentiles por grupo | NOMINAS_IMPORTES | SharePoint:Nominas (PDF) |
| `ranking_salarial` | Quién cobra más/menos en un grupo | NOMINAS_IMPORTES | SharePoint:Nominas (PDF) |

---

## DOCUMENTOS (5 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `documentos_persona` | Documentos firmados de una persona | DOCUMENTOS_LEER | SharePoint:DocumentosFirmados |
| `documentos_faltantes` | Quién no tiene un tipo de documento | DOCUMENTOS_LEER | SharePoint:DocumentosFirmados |
| `maestros_documentales` | Tipos de documentos obligatorios | DOCUMENTOS_LEER | SharePoint:DocumentosFirmados+Portal |
| `cobertura_documental` | Porcentaje de cobertura por tipo/dept | DOCUMENTOS_LEER | SharePoint:DocumentosFirmados |
| `leer_documento` | Contenido del PDF del documento | DOCUMENTOS_CONTENIDO | SharePoint:DocumentosFirmados (PDF) |

---

## CORREO (8 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `correos_sin_leer` / `pendientes` | Correos sin leer del buzón | CORREO_LEER | Graph:correo |
| `buscar_correos` / `buscar` | Búsqueda por asunto/remitente/fecha | CORREO_LEER | Graph:correo |
| `leer_correo` / `leer` | Contenido completo de un correo | CORREO_LEER | Graph:correo |
| `preparar_respuesta` / `borrador` | Crea un borrador de respuesta | CORREO_LEER | Graph:correo |
| `enviar_borrador` / `enviar` | Envía un borrador con confirmación | CORREO_ENVIAR | Graph:correo |
| `modificar_borrador` / `modificar` | Modifica texto de un borrador | CORREO_LEER | Graph:correo |
| `descartar_borrador` / `descartar` | Elimina un borrador | CORREO_LEER | Graph:correo |
| `borradores_guardados` / `guardados` | Lista de borradores guardados | CORREO_LEER | Graph:correo |

---

## CURRICULUMS (5 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `buscar_candidatos` / `buscar` | Búsqueda semántica por puesto/habilidades/idiomas | CURRICULUMS_LEER | SharePoint:Candidaturas |
| `candidatos_parecidos` / `parecidos` | Candidatos similares a un perfil (vector search) | CURRICULUMS_LEER | SharePoint:Candidaturas |
| `candidaturas` | Recuento de candidaturas por puesto/fecha | CURRICULUMS_LEER | SharePoint:Candidaturas |
| `ficha_candidato` | Ficha y CV de un candidato | CURRICULUMS_LEER | SharePoint:Candidaturas |
| `candidatos_y_plantilla` | Candidatos que ya son empleados | CURRICULUMS_LEER | SharePoint:Candidaturas+Empleados |

---

## TRABAJO TEMPORAL (10 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `trabajadores_tt` / `trabajadores` | Listado de trabajadores ETT | TT_LEER | SharePoint:ETT |
| `boletines_tt` / `boletines` | Boletines de horas ETT | TT_LEER | SharePoint:ETT |
| `boletines_faltantes_tt` | ETT sin boletín en el periodo | TT_LEER | SharePoint:ETT |
| `variacion_coste_tt` / `variacion_coste` | Variación de coste ETT entre periodos | TT_LEER | SharePoint:ETT |
| `estimar_coste_tt` / `estimar_coste` | Estimación de coste ETT | TT_LEER | SharePoint:ETT |
| `anomalias_tt` / `anomalias` | Anomalías en hojas horarias ETT | TT_LEER | SharePoint:ETT |
| `comunicaciones_tt` / `comunicaciones` | Comunicaciones con ETT | TT_LEER | SharePoint:ETT |
| `tarifas_tt` | Tarifas de ETT por puesto | TT_LEER | SharePoint:ETT |
| `contactos_ett` | Contactos de empresas ETT | TT_LEER | SharePoint:ETT |
| `ett_hoy` | ETT trabajando hoy | TT_LEER | SharePoint:ETT |

---

## ANALITICA (12 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `panel_rrhh` / `panel` | Panel ejecutivo multi-dominio | TURNOS_LEER | múltiple |
| `comparar_departamentos` / `comparar` | Comparación de KPIs entre departamentos | TURNOS_LEER | múltiple |
| `cobertura_semanal` / `cobertura` | Cobertura de turnos por semana | TURNOS_LEER | SharePoint:Turnos |
| `analitica_vacaciones` | Distribución y picos de vacaciones | VACACIONES_LEER | SharePoint:Vacaciones |
| `tendencia_ausencias` | Tendencia histórica de ausencias | TURNOS_LEER | SharePoint:Turnos |
| `ranking_absentismo` | Ranking de absentismo por dept | TURNOS_LEER | SharePoint:Turnos |
| `altas_empleados` / `altas` | Altas recientes de empleados | EMPLEADOS_LEER | SharePoint:Empleados |
| `calidad_datos` / `calidad` | Calidad de datos en el sistema | ADMINISTRAR | BD local |
| `proximos_jubilacion` | Empleados próximos a la edad de jubilación | EMPLEADOS_LEER | SharePoint:Empleados |
| `datos_de_personas` | Cruce de datos de cualquier origen para una lista | EMPLEADOS_LEER | múltiple |
| `consulta_cruzada` | Consulta multi-criterio y multi-dominio | EMPLEADOS_LEER | múltiple |
| `ficha_departamento` | Ficha 360 de un departamento | EMPLEADOS_LEER | múltiple |

---

## INFORMES (2 tools)

| Tool | Descripción | Permiso | Fuente |
|---|---|---|---|
| `generar_informe` | PDF/Excel/PPTX del último resultado en tabla | INFORMES_GENERAR | sesión |
| `generar_informe_ejecutivo` | Informe ejecutivo autónomo de RRHH | INFORMES_GENERAR | múltiple |

---

## FINANZAS (0 tools)

El módulo está registrado como placeholder con vocabulario de enrutado pero sin ninguna herramienta activa. `register()` es un no-op.

---

## Resumen de conteo

| Dominio | Tools |
|---|---|
| Sistema | 3 |
| Empleados | 8 |
| Turnos | 13 |
| Vacaciones | 4 |
| Nóminas | 7 |
| Documentos | 5 |
| Correo | 8 |
| Curriculums | 5 |
| Trabajo Temporal | 10 |
| Analítica | 12 |
| Informes | 2 |
| Finanzas | 0 |
| **TOTAL** | **77** |
