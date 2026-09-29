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

## Segunda auditoría (intenciones reales y listas usadas)

Contrastando las 157 intenciones que el sistema anterior resolvió de verdad y todas las
listas de SharePoint que leía, se añadieron:

| Sistema anterior | mIA | Estado |
|---|---|---|
| Álgebra de resultados (`v12_reference_*`: contar, filtrar, proyectar, ordenar, agrupar, intersecar) | `operar_resultado`, `cruzar_resultados` | ✅ |
| Descarga de CV, nómina y documento firmado (`…/documento`) | `GET /api/documents/{cv\|nomina\|documento}/{id}` con permiso y auditoría | ✅ |
| Correo: revisar, descartar y listar borradores; bloqueo no-reply; triaje a fondo | `modificar_borrador`, `descartar_borrador`, `borradores_guardados`, `incluir_texto` | ✅ |
| «Si el DNI del campo y el de la carpeta de Turnos no coinciden, se excluye» | Exclusión en la sincronización (queda como incidencia) | ✅ |
| Saldo consumido; saldo oficial sin recalcular | `consumido` en saldos, regla VAC-003 | ✅ |
| Comparar bajas por departamento; quién entra a una hora; publicación por departamento | `personas_por_departamento`, `empieza_a`, `personas_activas_sin_turnos_publicados` | ✅ |
| Comparar maestros de tipos documentales | `maestros_documentales` | ✅ |
| **Planificación de turnos v12**: calendarios `Calendario<Departamento>_AAAA` (histórico real desde 2023, descubiertos automáticamente), `TipoTurnos`, `TurnosPlantillas`, `ComentariosTurnosSemanas`, auditoría de publicación Turnos↔Calendario, métricas de horas y nocturnidad | `turnos_historico`, `catalogo_tipos_turno`, `plantillas_turno`, `comentarios_semana_turno`, `metricas_turnos`, `auditoria_publicacion_turnos` | ✅ (fase 4c) |

## Reglas de negocio del sistema anterior

Las 40 reglas de su base de conocimiento están en el catálogo (`rules/catalog.py`),
en el código de cada dominio o en la política de datos. Destacan: DNI nunca visible
(seudonimización), activos por defecto, reincorporación = primer turno de trabajo,
saldo oficial sin recalcular, «tener turno no implica trabajar», la carpeta manda en
nóminas, una fila de CV es una candidatura, la falta de evidencia no es falta de
competencia, importes históricos de ETT frente a estimaciones con tarifas actuales,
turnos partidos y cohortes privadas para cruces posteriores.


## Fase 4c: planificación de turnos v12 (calendarios)

Los calendarios de departamento no son una lista fija: `python -m mia.sync` (y `--check`)
**descubren automáticamente** qué `Calendario<Departamento>_AAAA` existen de verdad (9
departamentos × los años desde 2023), sin inventar ni asumir ninguno. `--no-calendars`
salta ese descubrimiento para una sincronización más rápida cuando no hace falta.

- **`turnos_historico`**: el histórico real de un departamento, con horas y turnos
  partidos, distinto de la proyección semanal publicada (`turnos_persona`/`turnos_dia`).
- **`catalogo_tipos_turno`**: el maestro `TipoTurnos` (horarios canónicos por departamento).
- **`plantillas_turno`**: `TurnosPlantillas` — reglas de generación, nunca histórico real.
- **`comentarios_semana_turno`**: `ComentariosTurnosSemanas`, contexto de
  departamento/semana, nunca atribuido a una persona.
- **`metricas_turnos`**: jornadas, horas y horas nocturnas reales por persona, excluyendo
  OFF/sin asignación (mismo criterio que el sistema anterior).
- **`auditoria_publicacion_turnos`**: compara un día entre Turnos (publicado) y Calendario
  (real) y señala a quién le falta uno de los dos.

Como estas listas identifican a la persona por nombre (no por DNI), las herramientas
piden que se concrete si hay varias coincidencias, igual que en una búsqueda de
empleados. Reglas nuevas: PLA-001 (Calendario es la fuente histórica autoritativa),
PLA-002 (plantillas y comentarios de semana no son histórico) y PLA-003 (personas por
nombre).

## Tercera revisión y cómo demostrar la paridad

Añadido tras revisar los módulos v12 y los frontends anteriores:

| Sistema anterior | mIA | Estado |
|---|---|---|
| Disponibilidad cruzada (`turnos_availability_v12`: plantilla + Calendario + vacaciones + ETT, con alertas) | `disponibilidad_dia` | ✅ |
| Micrófono (dictado por voz) en los frontends | Botón 🎤 en 2D, 3D y holograma | ✅ |
| Voz del navegador si ElevenLabs no responde | Respaldo automático en el cliente | ✅ |
| Rutas que llaman los frontends anteriores (`/api/mia/chat`, `/chat/stream`, `/v4/chat`, `/v4/health`, `/voice`, `/informes/generar`, `/api/version`) | Alias de compatibilidad | ✅ |

**Esta matriz es una auditoría, no una prueba.** El sistema anterior no guardó el texto de
sus respuestas, así que la paridad solo se demuestra preguntando a los dos a la vez:
`tools/shadow_compare.py` reproduce conversaciones reales en ambos y clasifica cada
respuesta (coinciden, difieren, solo responde el antiguo, solo responde el nuevo). Cada
«solo_antiguo» es un posible hueco; cada «difieren», una cifra que hay que contrastar.

Quedan fuera a propósito: las rutas de diagnóstico interno (`/api/sharepoint/*`, `qa/*`,
`roadmap/*`, `cache/*`, `modelo-datos/*`), que exponían listas sin autenticación.

## Resultados del modo sombra (60 conversaciones reales)

Correcciones tras comparar respuesta a respuesta con el sistema anterior:

| Diferencia detectada | Causa | Corrección |
|---|---|---|
| Turnos de mañana/tarde/noche: 101/36/1 frente a 91/42/5 | Se portó la franja del v10; los usuarios usaban la del v12 | Franjas v12: 06–14, 14–22, 22–06 (TUR-001) |
| «¿Quién trabaja mañana?» respondido como turno de mañana de hoy | Ambigüedad resuelta solo en el prompt | Resuelto en código: día siguiente |
| Reincorporaciones 55 frente a 49 | Ventana de 14 días | 35 días, como el antiguo |
| Saldo negativo: 5 personas frente a 4 | Se incluían inactivos | Solo activos por defecto (POB-001); orden por «más días» con empates |
| Vacaciones en agosto: «152 personas» | Se contaban solicitudes como personas | Personas distintas, solicitudes y solapes por separado |
| Edad media de la plantilla y por departamento | No existía | En `plantilla` |
| «Empleados de Pisos»: 112 frente a 136 | Filtrado por puesto en vez de departamento | Corrección automática |
| CVs: sin recuentos de candidaturas/personas | Solo búsqueda semántica top-10 | `filtrar_candidatos` (todos/alguno/excluir), sin duplicar personas |
| Nóminas: 10 frente a 103 documentos | Solo el año en curso | Histórico completo con recuento por tipo y año |
| Comunicaciones ETT sin contenido | Solo listado | Filtro por empresa y lectura de las más recientes |
| Duración media de bajas | Calculada por el modelo | Misma fórmula que el antiguo (días acumulados / periodos) |
| Dos consultas agotaban el tiempo | Cálculo de periodos cargando filas completas | Solo columnas y tipos de día necesarios |

Pendiente de verificar tras sincronizar los calendarios: bajas de Pisos en agosto (41
personas según el antiguo, 18 según mIA), probablemente calculadas por el antiguo desde el
Calendario y por mIA desde Turnos.


## Selección: búsqueda por requisitos (metadatos primero, después el CV)

`buscar_candidatos` recibe todos los requisitos pedidos, cada uno con sus equivalentes (traducciones,
sinónimos, especialidades, niveles), y los comprueba por separado en este orden:

1. **Metadatos de la candidatura**: todas las columnas de CurriculosVitae, incluidas las que no se
   conocían de antemano (la sincronización descubre y guarda cualquier columna propia de la lista).
2. **Documento CV**: el término o un equivalente en el texto extraído del CV.
3. **Por significado**, solo para completar a quien ya cumple el resto: un fragmento del CV que trata
   del requisito sin decirlo literalmente, marcado como «posible» (indicio, no confirmación).

Devuelve cuántas candidaturas y personas únicas cumplen todo, dónde se cumple cada requisito y el
fragmento que lo demuestra. La búsqueda libre por perfil queda como `candidatos_parecidos`.


## Cruce entre dominios

- **Automático**: vacaciones, saldos, ausencias, reincorporaciones y turnos del día se cruzan con
  EmpleadosCorporativos (por email o por el seudónimo del DNI) y muestran el puesto de cada persona;
  vacaciones indica además cuántas solicitudes no tienen ficha en la plantilla.
- **A demanda**: `datos_de_personas` añade a cualquier grupo (el resultado anterior, uno anterior con
  «resultado», o una lista de personas) puesto, departamento, responsable, edad, contacto, turno de hoy,
  saldo y próximas vacaciones, última nómina, nóminas sin leer y documentos firmados.


## Población: plantilla activa por defecto (POB-001)

Toda consulta de grupo es sobre empleados **activos** salvo que se pida expresamente lo contrario
(«incluyendo inactivos», «antiguos empleados», «todos»). Aplicado en: plantilla, saldos, nóminas por
periodo, documentos faltantes, panel y analítica y, desde esta versión, **vacaciones, turnos del día,
ausencias y reincorporaciones** (parámetro `incluir_inactivos`). Cada resumen indica su población
(«plantilla activa (POB-001)» o «activos e inactivos»). Una persona concreta por nombre se busca aunque
esté inactiva, y la ficha lo indica. El histórico de calendarios y métricas de horas reales es histórico:
incluye a quien trabajó en su día.


## Cierre de la fase 4: alcance y cruces

Ver [consultas.md](consultas.md) para el catálogo completo. Novedades de esta entrega:

- `consulta_cruzada`: criterios de varios dominios sobre las mismas personas (vacaciones, bajas, permisos,
  turnos por franja, saldo, nóminas sin leer o ausentes, documentos, edad, cumpleaños) con listar, contar o
  agrupar; admite «que no…» y seguir sobre el resultado anterior.
- `estadisticas_salariales` (NOM-004): salario medio, mediana, mínimo y máximo por puesto o departamento,
  solo agregados y con un mínimo de 5 personas por grupo.
- `ficha_departamento`, `candidatos_y_plantilla`, `companeros_de_turno`, y horas de una persona en
  `metricas_turnos`.
