# 05 - Cobertura de Preguntas

## Resumen del CSV base (365 preguntas auditadas)

| Estado | Cantidad | % |
|---|---|---|
| ✅ SOPORTADA | 226 | 61.9% |
| 🟡 PARCIALMENTE | 46 | 12.6% |
| 🔴 NO SOPORTADA | 93 | 25.5% |

---

## Análisis por Dominio

### SISTEMA (preguntas 1–25)
- ✅ 25/25 — Capacidades, resultados, operaciones, cruces, conocimiento general
- Notable: El historial de 12 turnos limita la memoria conversacional en sesiones largas

### EMPLEADOS (preguntas 26–70)
- ✅ 37 | 🟡 1 | 🔴 7
- Pendientes: género, hire_date/antigüedad, contract_type, jornada, discapacidad, fecha_fin_contrato

### TURNOS (preguntas 71–112)
- ✅ 36 | 🔴 2 (fichajes y horas extras — fuente inexistente)

### VACACIONES (preguntas 113–140)
- ✅ 25 | 🟡 2 | 🔴 1 (permisos especiales: matrimonio, maternidad)

### NÓMINAS (preguntas 141–170)
- ✅ 10 | 🟡 11 (content_enabled + SP) | 🔴 4 (suma global, conceptos CSV pre-implementados — ahora implementados, percentiles — ahora implementados)
- Nota: `parse_concepts()`, `parse_employer_ss()`, percentil_25/75 YA implementados — las preguntas 161–163 están desfasadas en el CSV (deberían ser 🟡 no 🔴)

### CORREO (preguntas 171–196)
- 🟡 24 | 🔴 2 (marcar leído, recordatorios)
- Todo correo depende de Graph API + mailbox configurado

### DOCUMENTOS (preguntas 197–224)
- ✅ 26 | 🟡 2 | 🔴 1 (fecha expiración)

### CURRICULUMS (preguntas 225–255)
- ✅ 27 | 🟡 2 | 🔴 3 (discapacidad, ranking idoneidad SEL-001 — por diseño)

### ANALÍTICA (preguntas 256–290)
- ✅ 32 | 🔴 4 (género, antigüedad/correlación, productividad, jubilación — la última YA implementada)
- Nota: `proximos_jubilacion` YA implementado — pregunta 284 desfasada en CSV

### TRABAJO TEMPORAL (preguntas 291–323)
- ✅ 28 | 🟡 2 | 🔴 1 (presupuesto ETT — sin datos)
- Nota: `boletines_faltantes_tt` y `variacion_coste_tt` YA implementados — preguntas 322-323 desfasadas

### INFORMES (preguntas 324–342)
- ✅ 14 | 🟡 2 | 🔴 1 (personalización diseño)

### FINANZAS (preguntas 343–355)
- 🔴 13/13 — Sin implementar

### TRANSVERSAL (preguntas 356–365)
- 🔴 10/10 — Escritura, plan igualdad, evaluación, formación, historial cambios, jornada reducida, calendario laboral, salud laboral

---

## Batería ampliada de 200 preguntas adicionales por dominio

### Sistema / conversacional (21–40 adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A1 | ¿Puedes ordenar ese resultado por fecha? | 🟢 operar_resultado |
| A2 | Muéstrame solo los 5 primeros | 🟢 operar_resultado |
| A3 | Dame el resultado anterior en PDF | 🟢 generar_informe |
| A4 | ¿Cuántos hay en ese grupo? | 🟢 operar_resultado(contar) |
| A5 | Agrupa ese resultado por puesto | 🟢 operar_resultado(agrupar) |
| A6 | Filtra los anteriores que sean de Mantenimiento | 🟢 operar_resultado(filtrar) |
| A7 | Cruza ese resultado con el de vacaciones | 🟢 cruzar_resultados |
| A8 | ¿Qué idiomas hablas? | 🟢 LLM sin tool |
| A9 | ¿Cuántos días tiene un mes en promedio? | 🟢 LLM sin tool |
| A10 | Explícame qué es un ERE | 🟢 LLM sin tool |

### Empleados (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A11 | ¿Cuántos empleados hay en activo en Animación? | 🟢 plantilla |
| A12 | Dame el listado de todos los puestos que existen en la empresa | 🟢 plantilla/estructura |
| A13 | ¿Hay algún empleado con apellido Ruiz en Cocina? | 🟢 buscar_empleado |
| A14 | ¿Cuántos empleados hay en la sección de Bares? | 🟢 plantilla |
| A15 | Dame la ficha de código E00042 | 🟢 buscar_empleado(employee_code) |
| A16 | ¿Quién es el responsable de Housekeeping? | 🟢 responsables |
| A17 | ¿Cuántos empleados tienen más de 60 años? | 🟢 perfil_edad |
| A18 | ¿Qué empleados cumplen años el mes que viene? | 🟢 cumpleanos |
| A19 | ¿Cuántas personas hay en total por nacionalidad? | 🟢 plantilla(agrupar_por=nacionalidad) |
| A20 | Muéstrame los empleados inactivos de toda la empresa | 🟢 plantilla(estado=inactivos) |
| A21 | ¿Qué edad media tienen los cocineros? | 🟢 perfil_edad/consulta_cruzada |
| A22 | ¿Qué secciones tiene el departamento de Recepción? | 🟢 estructura_departamentos |
| A23 | Dame los teléfonos de extensión de Mantenimiento | 🟢 contactos_organizacion |
| A24 | ¿Cuántos jefes de departamento hay? | 🟢 responsables/plantilla(puesto=jefe) |
| A25 | ¿Qué departamento tiene más empleados? | 🟢 plantilla(agrupar_por=departamento) |
| A26 | ¿Cuántos empleados hay con nombre María? | 🟢 buscar_empleado |
| A27 | ¿Hay alguien de la misma familia (mismo apellido) en Cocina y Recepción? | 🟠 posible con cruces, complejo |
| A28 | ¿Cuántos empleados llevan menos de un año en la empresa? | 🔴 sin hire_date |
| A29 | ¿Cuántos empleados tienen contrato indefinido? | 🔴 sin contract_type |
| A30 | ¿Cuántas mujeres hay en plantilla? | 🔴 sin campo género |

### Turnos (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A31 | ¿Cuántas horas tiene programadas Cocina mañana? | 🟢 turnos_dia |
| A32 | ¿Qué turno tiene Ana Torres el jueves? | 🟢 turnos_persona |
| A33 | ¿Hay algún empleado sin turno publicado hoy en Pisos? | 🟢 consulta_cruzada |
| A34 | ¿Cuántos turnos partidos hay en Recepción esta semana? | 🟢 metricas_turnos |
| A35 | ¿Qué comentarios hay en el calendario de Cocina esta semana? | 🟢 comentarios_semana_turno |
| A36 | ¿Cuántos días de baja lleva María Sánchez? | 🟢 ausencias |
| A37 | Dame las bajas de más de 60 días | 🟢 ausencias(ordenar_por=dias) |
| A38 | ¿Quién empieza a trabajar a las 7:00 mañana en Recepción? | 🟢 turnos_dia |
| A39 | ¿Cuántas personas están disponibles hoy en Pisos cruzando calendario y vacaciones? | 🟢 disponibilidad_dia |
| A40 | ¿Cuál es el índice de bajas de Cocina en los últimos 6 meses? | 🟢 tendencia_ausencias |
| A41 | ¿Qué diferencia hay entre horas planificadas y reales de Mantenimiento en septiembre? | 🟢 auditoria_publicacion_turnos |
| A42 | ¿Quién hizo más horas nocturnas en el tercer trimestre? | 🟢 metricas_turnos |
| A43 | ¿Cuál es el turno más habitual en Cocina? | 🟢 catalogo_tipos_turno |
| A44 | ¿Con quién coincide Pedro García el miércoles en su turno? | 🟢 companeros_de_turno |
| A45 | ¿Hay algún permiso de matrimonio en la empresa esta semana? | 🟢 ausencias(tipos=permiso) |
| A46 | ¿Cuántas personas están de permiso por lactancia? | 🟠 ausencias, si está como tipo |
| A47 | ¿A qué hora fichó Ana Torres esta mañana? | 🔴 sin sistema de fichajes |
| A48 | ¿Cuántas horas extras se han generado este mes? | 🔴 sin campo horas extras |
| A49 | ¿Cuál es el historial de turnos de Juan García en 2025? | 🟢 turnos_historico |
| A50 | ¿Qué plantilla de turno tiene el departamento de Pisos? | 🟢 plantillas_turno |

### Vacaciones (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A51 | ¿Cuántas personas de Recepción están de vacaciones este mes? | 🟢 vacaciones |
| A52 | ¿Hay alguien de Animación sin vacaciones disfrutadas este año? | 🟢 saldo_vacaciones + consulta |
| A53 | ¿Cuántos días de vacaciones hay disfrutados en total en agosto? | 🟢 analitica_vacaciones |
| A54 | ¿Qué porcentaje de solicitudes han sido aprobadas este año? | 🟢 vacaciones (cálculo) |
| A55 | ¿Puede Ana Torres pedir vacaciones la próxima semana sin solapar con nadie? | 🟢 conflictos_vacaciones |
| A56 | ¿Quién vuelve de vacaciones la semana que viene? | 🟢 reincorporacion/reincorporaciones |
| A57 | ¿Hay empleados con más de 25 días de vacaciones sin disfrutar? | 🟢 saldo_vacaciones |
| A58 | ¿Cuántas solicitudes de asuntos propios hay pendientes de aprobación? | 🟢 vacaciones(tipo=asuntos_propios,estado=pendientes) |
| A59 | ¿Cuál es el periodo más demandado para vacaciones? | 🟢 analitica_vacaciones |
| A60 | ¿Cuándo vuelve Pedro García de sus vacaciones? | 🟢 reincorporacion |
| A61 | ¿Tiene Juan García días de permiso por paternidad disponibles? | 🔴 sin tipos especiales |
| A62 | ¿Qué departamento tiene más solicitudes de vacaciones pendientes? | 🟢 vacaciones(estado=pendientes) |
| A63 | ¿Hay conflictos de cobertura si aprueban las vacaciones de Ana Torres? | 🟢 conflictos_vacaciones |
| A64 | ¿Cuántos días totales de asuntos propios quedan disponibles en Pisos? | 🟢 saldo_vacaciones |
| A65 | Dame el Excel de solicitudes de vacaciones de agosto | 🟢 vacaciones + generar_informe |

### Nóminas (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A66 | ¿Cuántas nóminas hay de noviembre de 2025? | 🟢 nominas_periodo |
| A67 | ¿Quién no tiene la nómina de octubre? | 🟢 nominas_periodo |
| A68 | ¿Hay duplicados en las nóminas de septiembre? | 🟢 anomalias_nominas |
| A69 | ¿Cuánto cobra de media un camarero de pisos? | 🟡 estadisticas_salariales (content_enabled+SP) |
| A70 | ¿Cuál es el coste total de empresa de Recepción? | 🟡 estadisticas_salariales (devengado+SS) |
| A71 | ¿Ha subido la nómina de Juan García este año? | 🟡 evolucion_nominas comparar_con_anio_anterior |
| A72 | ¿Cuál es el percentil 75 salarial de los cocineros? | 🟡 estadisticas_salariales (content_enabled) |
| A73 | ¿Hay nóminas huérfanas en el sistema? | 🟢 anomalias_nominas |
| A74 | ¿Cuántas pagas extra hay registradas en diciembre? | 🟢 nominas_periodo / nominas_persona |
| A75 | ¿Cuál es el histórico de nóminas de Ana Torres? | 🟢 nominas_persona |
| A76 | ¿Qué IRPF tiene la nómina de agosto de Pedro García? | 🟡 nomina_importes (content_enabled) |
| A77 | ¿Cuáles son los conceptos salariales de la nómina de Juan García? | 🟡 nomina_importes → parse_concepts() |
| A78 | ¿Cuánto aporta la empresa a la SS de Ana Torres? | 🟡 nomina_importes → parse_employer_ss() |
| A79 | ¿Cuántas nóminas sin leer tiene Cocina? | 🟢 consulta_cruzada / nominas_periodo |
| A80 | ¿Cuál es la suma total de líquido de Pisos en octubre? | 🟡 estadisticas_salariales(suma) |

### Documentos (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A81 | ¿Cuántos tipos de documentos hay en el sistema? | 🟢 maestros_documentales |
| A82 | ¿Qué documentos de Cocina están pendientes? | 🟢 documentos_faltantes(departamento=Cocina) |
| A83 | ¿Tiene Pedro García todos los documentos obligatorios? | 🟢 documentos_persona + documentos_faltantes |
| A84 | ¿Cuántos empleados tienen el reconocimiento médico firmado? | 🟢 cobertura_documental |
| A85 | ¿Qué porcentaje de la plantilla tiene el documento de LOPD? | 🟢 cobertura_documental(tipo=LOPD) |
| A86 | Dame el enlace al contrato de Ana Torres | 🟢 documentos_persona(tipo=contrato) |
| A87 | ¿Qué dice el contrato de Juan García? | 🟡 leer_documento (content_enabled + DOCUMENTOS_CONTENIDO) |
| A88 | ¿Cuándo vence el reconocimiento médico de Pedro García? | 🔴 sin fecha_expiración |
| A89 | ¿Qué cobertura documental tiene Pisos? | 🟢 cobertura_documental(departamento=Pisos) |
| A90 | ¿Cuántos empleados no tienen ningún documento firmado? | 🟢 documentos_faltantes |
| A91 | ¿Qué documentos del año 2024 están firmados? | 🟢 cobertura_documental(anio=2024) |
| A92 | ¿Cuántas prórrogas se han firmado este año? | 🟢 documentos_persona/faltantes(tipo=Prórroga) |
| A93 | ¿Hay empleados de Mantenimiento sin ningún documento? | 🟢 documentos_faltantes(departamento=Mantenimiento) |
| A94 | ¿Qué documento tiene menos cobertura? | 🟢 cobertura_documental |
| A95 | ¿Cuántos documentos de formación hay firmados en total? | 🟢 documentos_persona/cobertura_documental(tipo=formación) |

### Correo (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A96 | ¿Cuántos correos tengo sin leer? | 🟡 correos_sin_leer (Graph) |
| A97 | Muéstrame los últimos 10 correos | 🟡 buscar_correos (Graph) |
| A98 | ¿Hay correos de la ETT Eulen? | 🟡 buscar_correos (Graph) |
| A99 | Resume los correos sin leer de hoy | 🟡 correos_sin_leer + leer_correo (Graph) |
| A100 | ¿Hay algún correo urgente? | 🟡 buscar_correos (sin filtro urgencia real) |
| A101 | Lee el segundo correo sin leer | 🟡 correos_sin_leer + leer (Graph) |
| A102 | Redacta una respuesta al correo de María García | 🟡 preparar_respuesta (Graph) |
| A103 | Envía el borrador | 🟡 enviar_borrador (Graph + send_enabled + confirmación) |
| A104 | ¿Cuántos borradores tengo guardados? | 🟡 borradores_guardados (Graph) |
| A105 | Descarta el borrador número 2 | 🟡 descartar_borrador (Graph) |
| A106 | Marca el correo c1 como leído | 🔴 sin herramienta marcar_leido |
| A107 | Envíame un recordatorio sobre la reunión del viernes | 🔴 guard.py bloquea promesas |
| A108 | ¿Hay correos de la semana pasada sin leer? | 🟡 correos_sin_leer(periodo) (Graph) |
| A109 | Busca correos con adjuntos sobre contratos | 🟡 buscar_correos (Graph, filtro adjuntos básico) |
| A110 | ¿De qué trata el último correo de Pedro Martínez? | 🟡 buscar_correos + leer (Graph) |

### Curriculums (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A111 | ¿Hay candidatos a camarero de pisos con inglés? | 🟢 buscar_candidatos |
| A112 | ¿Cuántos candidatos hay en total para puestos de cocina? | 🟢 candidaturas |
| A113 | Dame los 3 candidatos más similares al perfil de Pedro García | 🟢 candidatos_parecidos |
| A114 | ¿Ya trabaja aquí alguno de los candidatos a recepcionista? | 🟢 candidatos_y_plantilla |
| A115 | Busca candidatos con experiencia en restauración colectiva | 🟢 buscar_candidatos |
| A116 | ¿Cuántos candidatos hay para puestos de limpieza? | 🟢 candidaturas |
| A117 | Dame la ficha completa de Carlos Ruiz candidato | 🟢 ficha_candidato |
| A118 | ¿Hay candidatos con carnet de conducir? | 🟢 buscar_candidatos |
| A119 | ¿Cuántos candidatos han entrado este mes? | 🟡 candidaturas(fecha) si metadato disponible |
| A120 | Ordéname los candidatos de mejor a peor para cocinero | 🔴 SEL-001 — prohibido por diseño |
| A121 | ¿Hay candidatos de Málaga? | 🟢 buscar_candidatos(query=Málaga) |
| A122 | ¿Cuántos candidatos únicos hay en el sistema? | 🟢 candidaturas(personas_unicas) |
| A123 | Dame los candidatos con disponibilidad inmediata | 🟡 buscar_candidatos (si campo disponibilidad) |
| A124 | ¿Hay candidatos con titulación en hostelería? | 🟢 buscar_candidatos |
| A125 | ¿Qué formación tienen los candidatos a jefe de recepción? | 🟢 buscar_candidatos + ficha_candidato |

### Analítica (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A126 | Dame el panel completo de RRHH de hoy | 🟢 panel_rrhh |
| A127 | ¿Cómo está Cocina comparado con Pisos? | 🟢 comparar_departamentos |
| A128 | ¿Qué departamento tiene más vacaciones activas esta semana? | 🟢 analitica_vacaciones / panel |
| A129 | ¿Cuántos empleados se han dado de alta en el último trimestre? | 🟢 altas_empleados |
| A130 | ¿Cuántos empleados de Recepción trabajan de noche y tienen saldo negativo? | 🟢 consulta_cruzada |
| A131 | ¿Cuáles son los empleados de baja de Mantenimiento que también tienen documentos pendientes? | 🟢 consulta_cruzada |
| A132 | ¿Qué ficha 360 tiene Animación? | 🟢 ficha_departamento |
| A133 | ¿Hay algún problema de calidad de datos? | 🟡 calidad_datos (ADMINISTRAR) |
| A134 | ¿Qué empleados están próximos a jubilarse en los próximos 3 años? | 🟢 proximos_jubilacion(horizonte_anios=3) |
| A135 | ¿Cuántos empleados se jubilan antes de 2030? | 🟢 proximos_jubilacion |
| A136 | Dame los datos de vacaciones de todos los que están de baja | 🟢 datos_de_personas |
| A137 | ¿Cuántos empleados de cada puesto están de vacaciones hoy? | 🟢 consulta_cruzada(agrupar_por=puesto) |
| A138 | ¿Cuál es la tendencia de absentismo de los últimos 12 meses? | 🟢 tendencia_ausencias |
| A139 | ¿Qué departamento tiene mejor cobertura semanal? | 🟢 cobertura_semanal |
| A140 | ¿Cuántos empleados de Pisos tienen más de 45 años y turno nocturno? | 🟢 consulta_cruzada |
| A141 | ¿Hay correlación entre antigüedad y absentismo? | 🔴 sin hire_date + sin módulo predictivo |
| A142 | ¿Cuál es el porcentaje de mujeres en la plantilla? | 🔴 sin campo género |

### Trabajo Temporal (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A143 | ¿Cuántos trabajadores de ETT hay asignados esta semana? | 🟢 ett_hoy / boletines_tt |
| A144 | ¿Hay algún trabajador de ETT sin boletín este mes? | 🟢 boletines_faltantes_tt |
| A145 | ¿Cuánto ha variado el coste de ETT respecto al mes pasado? | 🟢 variacion_coste_tt |
| A146 | ¿Cuál es la ETT que más factura? | 🟢 boletines_tt |
| A147 | ¿Hay anomalías en los boletines de ETT de agosto? | 🟢 anomalias_tt |
| A148 | ¿Cuánto se gastó en ETT el primer trimestre? | 🟢 boletines_tt(acumular) |
| A149 | Dame las tarifas de la ETT Adecco por puesto | 🟢 tarifas_tt |
| A150 | ¿Hay trabajadores de ETT trabajando más de 12 horas? | 🟢 anomalias_tt(>12h/day) |
| A151 | ¿Qué comunicaciones recientes hay con la ETT? | 🟢 comunicaciones_tt |
| A152 | Estima el coste de 8 camareros de pisos ETT para julio | 🟢 estimar_coste_tt |
| A153 | ¿Cuántas jornadas ha registrado cada ETT este mes? | 🟢 boletines_tt |
| A154 | ¿Hay duplicados en los boletines de ETT de septiembre? | 🟢 anomalias_tt(duplicates) |
| A155 | ¿Qué presupuesto de ETT tenemos? | 🔴 sin módulo presupuesto |
| A156 | Dame un Excel del coste de ETT del último trimestre | 🟢 boletines_tt + generar_informe |

### Informes (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A157 | Genera un informe ejecutivo de RRHH en PDF | 🟢 generar_informe_ejecutivo |
| A158 | Exporta este resultado a Excel | 🟢 generar_informe(xlsx) |
| A159 | Dame un PowerPoint del análisis de turnos | 🟢 generar_informe(pptx) |
| A160 | ¿Puedo descargar los datos de candidatos? | 🟢 generar_informe(LAST_TABLE) |
| A161 | Genera el informe ejecutivo de los últimos 6 meses | 🟡 generar_informe_ejecutivo (sin param periodo) |
| A162 | ¿Puedo cambiar el logo del informe? | 🟡 settings.reports.logo_path |
| A163 | Cambia el color del informe a azul | 🔴 sin param diseño |

### Finanzas (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A164 | ¿Cuánto factura el hotel al mes? | 🔴 módulo vacío |
| A165 | ¿Cuál es el beneficio neto del año? | 🔴 módulo vacío |
| A166 | ¿Cuánto debo a los proveedores? | 🔴 módulo vacío |
| A167 | ¿Cuál es el presupuesto de personal? | 🔴 módulo vacío |
| A168 | ¿Cuál es el EBITDA del hotel? | 🔴 módulo vacío |
| A169 | Dame el balance de tesorería | 🔴 módulo vacío |
| A170 | ¿Cuánto se ha gastado en energía? | 🔴 módulo vacío |

### Transversal / Multi-dominio (adicionales)

| # | Pregunta | Estado |
|---|---|---|
| A171 | ¿Puede mIA crear un empleado nuevo? | 🔴 solo lectura |
| A172 | ¿Puede mIA aprobar una solicitud de vacaciones? | 🔴 solo lectura |
| A173 | ¿Puede mIA publicar un turno? | 🔴 solo lectura |
| A174 | ¿Qué formaciones ha hecho Juan García? | 🔴 sin módulo formación (solo docs firmados) |
| A175 | ¿Cuáles son los festivos del convenio hotelero? | 🔴 sin calendario laboral |
| A176 | ¿Cuántos empleados tienen reducción de jornada? | 🔴 sin campo tipo_jornada |
| A177 | ¿Cuáles son las evaluaciones de desempeño del año? | 🔴 sin módulo evaluación |
| A178 | ¿Hay empleados con restricciones médicas para el turno de noche? | 🔴 sin datos salud laboral |
| A179 | ¿Qué empleados cumplen el plan de igualdad? | 🔴 sin módulo igualdad + sin campo género |
| A180 | ¿Puedo ver el historial de cambios de datos de Ana Torres? | 🔴 AuditEvent solo registra accesos, no modificaciones |
| A181 | Dame el informe de plantilla de toda la empresa en PDF | 🟢 plantilla + generar_informe |
| A182 | ¿Qué empleados de baja tienen también vacaciones pendientes? | 🟢 consulta_cruzada |
| A183 | Genera una presentación PowerPoint con todos los KPIs de hoy | 🟢 panel_rrhh + generar_informe(pptx) |
| A184 | ¿Qué pasa si Ana Torres coge baja y también está Pedro García de vacaciones? | 🟢 ausencias + vacaciones |
| A185 | Dame la comparativa de absentismo por departamento de los últimos 3 meses | 🟢 tendencia_ausencias + comparar |
| A186 | ¿Cuántos empleados tienen pendiente firma de contrato Y tampoco tienen nómina? | 🟢 consulta_cruzada |
| A187 | Genera el informe ejecutivo y envíalo por correo al director | 🟡 generar_informe_ejecutivo + enviar_borrador |
| A188 | ¿Cuántos candidatos tienen más de 5 años de experiencia? | 🟢 buscar_candidatos |
| A189 | ¿Hay empleados de Pisos sin turno publicado mañana que tampoco estén de baja? | 🟢 consulta_cruzada |
| A190 | Dame el panel de ETT del mes en curso | 🟢 boletines_tt / ett_hoy |
| A191 | ¿Cuántos empleados hay en total? | 🟢 plantilla |
| A192 | ¿Qué empleados tienen saldo de vacaciones negativo Y nóminas sin leer? | 🟢 consulta_cruzada |
| A193 | ¿Hay alguien cumpliendo años esta semana que también esté de vacaciones? | 🟢 consulta_cruzada |
| A194 | Dame el estado de toda la empresa en un gráfico de barras | 🟢 plantilla(agrupar) + presentación visual frontend |
| A195 | ¿Cuál es la cobertura de la semana del 15 al 21 de julio? | 🟢 cobertura_semanal |
| A196 | ¿Cuántos empleados de Animación tienen más de 50 años y están de baja? | 🟢 consulta_cruzada |
| A197 | Dame los empleados próximos a jubilación en Cocina en los próximos 10 años | 🟢 proximos_jubilacion(horizonte_anios=10, departamento=Cocina) |
| A198 | ¿Hay conflictos de vacaciones si aprobaramos todas las solicitudes pendientes? | 🟠 posible con consulta_cruzada, complejo |
| A199 | Dame el resumen semanal de RRHH | 🟢 panel_rrhh(fecha) |
| A200 | ¿Cuál es el ratio de personal ETT sobre plantilla fija hoy? | 🟢 ett_hoy + plantilla (cálculo) |
