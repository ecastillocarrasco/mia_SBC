# Matriz de cobertura: sistema anterior → mIA

Cada función del sistema anterior (v10.42 + capas v11/v12 + gateway v4) con su
equivalente. Las rutas de diagnóstico interno (`/api/sharepoint/*`, `roadmap/*`,
`qa/*`, `modelo-datos/*`, `cache/*`) no se migran: eran herramientas de
desarrollo y exponían listas sin autenticación.

## Conversación y consultas

| Sistema anterior | mIA | Estado |
|---|---|---|
| `/api/mia/chat`, `/chat/stream`, `/v4/chat`, `/consultar`, `/preguntar`, `/interpretar`, `/resolver` | Motor único con herramientas (`/api/chat`, `/api/chat/stream` + alias) | ✅ |
| Asistente general (búsqueda web, tiempo) | Cualquier consulta fuera de SBC va al LLM; búsqueda web del proveedor | ✅ |
| Contexto y foco (`resultados/contexto`, v12 conversation state) | Estado en servidor: foco de persona/departamento/periodo | ✅ |
| Cruces por cohorte (`cruces/cohorte/*`) | `sobre_resultado_anterior` en plantilla, turnos, ausencias, vacaciones, saldos, nóminas, documentos y reincorporaciones | ✅ |
| Voz (`/api/mia/voice`, `voz/config`) | ElevenLabs en streaming + caché; la voz nunca dice importes | ✅ |
| Capacidades (`capacidades`, `conversacion/capacidades`, `catalogo`) | Herramienta `capacidades`, calculada del registro real | ✅ |

## Empleados y organización

| Sistema anterior | mIA | Estado |
|---|---|---|
| `empleados/360`, `empleados/ficha360` | `ficha_empleado`: hoy, semana, próximos hitos, ficha laboral, organización, vacaciones y saldo, bajas del año, nóminas, documentos, indicadores y acciones | ✅ |
| Plantilla, búsquedas | `plantilla` (activos por defecto, agrupar por departamento/puesto/nacionalidad), `buscar_empleado` | ✅ |
| `departamentos`, `departamentos/360`, `organizacion/mapeo`, `sharepoint/empleados/responsables` | `estructura_departamentos`, `panel_rrhh(departamento)` | ✅ |
| `departamentos/comparar`, `analitica/departamentos/comparar` | `comparar_departamentos` | ✅ |
| `dashboard/rrhh`, `analitica/dashboard-rrhh` | `panel_rrhh` | ✅ |
| `alta-empleados` | `altas_empleados` (AltaEmpleados; la contraseña nunca se lee) | ✅ |
| `empleados/calidad`, `saldovacaciones/calidad`, `seleccion/calidad` | `calidad_datos` (solo administración) | ✅ |
| Nacionalidad | Campo opcional; se sincroniza en cuanto exista la columna | ✅ |

## Turnos, ausencias y vacaciones

| Sistema anterior | mIA | Estado |
|---|---|---|
| `turnos`, `turnos/personas-dia`, `analitica/departamento-dia`, `operacion/departamento` | `turnos_persona`, `turnos_dia` (franjas y presencia) | ✅ |
| `turnos/cobertura`, `operacion/semana` | `cobertura_semanal` | ✅ |
| `turnos/comentarios` | Comentarios incluidos en cada día de turno | ✅ |
| Turnos partidos (varios tramos) | Tramos y horas por día; presencia por tramo | ✅ |
| Bajas, ausencias, reincorporación | `ausencias` (periodo real), `reincorporacion`, `reincorporaciones` | ✅ |
| `vacaciones`, `vacaciones/vigentes`, `vacaciones/pendientes` | `vacaciones` (estado aceptadas/pendientes/rechazadas) | ✅ |
| `vacaciones/analitica` | `analitica_vacaciones` | ✅ |
| `saldovacaciones`, `saldos/personas`, `saldovacaciones/cobertura` | `saldo_vacaciones`, `calidad_datos` | ✅ |

## Documentación, nóminas y selección

| Sistema anterior | mIA | Estado |
|---|---|---|
| `nominas` | `nominas_persona`, `nominas_periodo` | ✅ |
| `nominas/<id>/texto`, `pregunta-economica`, `evolucion`, `comparar` | `nomina_importes`, `evolucion_nominas` (permiso propio, auditado, sin guardar, nunca en voz) | ✅ |
| `documentos-firmados` | `documentos_persona`, `documentos_faltantes` | ✅ |
| `documentos-firmados/<id>/texto` | `leer_documento` (permiso propio, auditado, sin guardar) | ✅ |
| `tipos-documentos-firma`, `tipos-documento`, `documentacion/comparar-maestros-firma` | Maestros sincronizados; documentos obligatorios (FirmarTodas) en `documentos_faltantes` | ✅ |
| `curriculums`, `seleccion/candidaturas`, `curriculums/<id>/perfil` | `candidaturas`, `ficha_candidato` | ✅ |
| `curriculums/buscar-contenido`, `seleccion/evidencias`, `indice-cv` | `buscar_candidatos` (semántica, con evidencia, sin ranking) | ✅ |
| `curriculums/<id>/documento/ocr` | CVs en imagen leídos con el modelo multimodal | ✅ |

## Trabajo temporal

| Sistema anterior | mIA | Estado |
|---|---|---|
| `trabajo-temporal/empresas`, `empleados`, `resumen` | `trabajadores_tt` | ✅ |
| `trabajo-temporal/boletines`, `analitica/trabajo-temporal` | `boletines_tt` | ✅ |
| `trabajo-temporal/estimar-coste`, `settings` | `estimar_coste_tt` (SettingsTT) | ✅ |
| `analitica/trabajo-temporal/anomalias` | `anomalias_tt` | ✅ |
| `trabajo-temporal/comunicaciones` | `comunicaciones_tt` | ✅ |

## Informes

| Sistema anterior | mIA | Estado |
|---|---|---|
| `informes/generar` (14 módulos, PDF/Excel, plantilla corporativa con logo) | `generar_informe` desde cualquier resultado (tabla, panel, ficha 360, nóminas…) + alias `/api/mia/informes/generar` para los botones del frontend | ✅ |
| `exportar/*.xlsx` (turnos, vacaciones, departamento, comparativa) | El mismo generador sobre el resultado correspondiente | ✅ |
| PowerPoint (planificado, nunca implementado) | `pptx` en `generar_informe` | ✅ nuevo |

## Correo

| Sistema anterior | mIA | Estado |
|---|---|---|
| Outlook: pendientes, detalle, adjuntos, borradores, envío | `correos_sin_leer`, `buscar_correos`, `leer_correo`, `preparar_respuesta`, `enviar_borrador` (confirmación obligatoria) | ✅ |

## Reglas de negocio del sistema anterior

Las 40 reglas de su base de conocimiento están en el catálogo (`rules/catalog.py`),
en el código de cada dominio o en la política de datos. Destacan: DNI nunca visible
(seudonimización), activos por defecto, reincorporación = primer turno de trabajo,
saldo oficial sin recalcular, «tener turno no implica trabajar», la carpeta manda en
nóminas, una fila de CV es una candidatura, la falta de evidencia no es falta de
competencia, importes históricos de ETT frente a estimaciones con tarifas actuales,
turnos partidos y cohortes privadas para cruces posteriores.
