# Qué se le puede preguntar a mIA

Cada fila es un tipo de pregunta y la herramienta que la resuelve. Las consultas de grupo son siempre de la
plantilla activa (POB-001) salvo que se pida expresamente «incluyendo inactivos».

## Personas y organización
| Pregunta | Herramienta |
|---|---|
| «Ficha completa de Sandra», «¿está activa?», «¿quién es su responsable?» | `buscar_empleado`, `ficha_empleado` (`detalle=true` para el histórico) |
| «¿Cuántos empleados hay?», «edad media», «por puesto / departamento / nacionalidad» | `plantilla` |
| «Cuéntame cómo está Pisos», «resumen de Cocina» | `ficha_departamento` |
| **Compuestas**: «camareras de pisos con turno de noche mañana», «quién de cocina está de vacaciones y tiene saldo negativo», «quién cumple años este mes en recepción», «cuántos de baja por puesto» | `consulta_cruzada` |
| «De esos, ¿qué puesto / saldo / turno hoy / última nómina?» | `datos_de_personas` |

## Turnos y ausencias
| Pregunta | Herramienta |
|---|---|
| «Turnos de Ana esta semana», «¿cuándo libra?» | `turnos_persona` |
| «¿Quién trabaja mañana / de noche / a las 16:00?» | `turnos_dia` |
| «¿Con quién coincide Ana el lunes?» | `companeros_de_turno` |
| «¿Quién está de baja / desde cuándo / quién lleva más / duración media?» | `ausencias` |
| «¿Quién se reincorpora (tras baja, permiso, vacaciones o asuntos propios)?» | `reincorporaciones` |
| «Disponibilidad real de un departamento hoy (con vacaciones y ETT)» | `disponibilidad_dia` |
| Histórico real, horas y nocturnidad (por departamento o persona) | `turnos_historico`, `metricas_turnos` |
| Catálogo de turnos, plantillas, comentarios de semana, publicado frente a real | `catalogo_tipos_turno`, `plantillas_turno`, `comentarios_semana_turno`, `auditoria_publicacion_turnos` |

## Vacaciones
| Pregunta | Herramienta |
|---|---|
| «¿Quién está de vacaciones hoy / en agosto?» (con puesto) | `vacaciones` |
| «Saldo de X», «saldos negativos», «quién tiene más días» | `saldo_vacaciones` |
| «¿Cuándo vuelve X?» | `reincorporacion` |
| Cobertura, vacaciones por semana, comparativas entre departamentos | `cobertura_semanal`, `analitica_vacaciones`, `comparar_departamentos` |

## Selección
| Pregunta | Herramienta |
|---|---|
| «Dos CV de cocina con inglés y cocina japonesa» (metadatos primero, después el CV), «sin inglés» | `buscar_candidatos` |
| «Alguien con experiencia en hoteles de lujo» (por significado) | `candidatos_parecidos` |
| «Resúmeme el CV de X» | `ficha_candidato` |
| «¿Algún candidato ya trabaja aquí / es un antiguo empleado?» | `candidatos_y_plantilla` |

## Nóminas y documentos
| Pregunta | Herramienta |
|---|---|
| «¿Cuántas nóminas tiene X?», «la última», «quién no tiene la de agosto» | `nominas_persona`, `nominas_periodo`, `consulta_cruzada` |
| Importes de una nómina, evolución | `nomina_importes`, `evolucion_nominas` (permiso propio) |
| **«Salario medio de un cocinero»**, líquido medio por departamento | `estadisticas_salariales` (solo agregados, mínimo 5 personas, permiso propio) |
| **«Los 3 que más cobraron en Cocina»** (ordenado sobre todo el grupo, con la cobertura de nóminas leídas) | `ranking_salarial` (máx. 10, grupos de 5+, solo en pantalla, permiso propio) |
| Documentos firmados, faltantes, contenido de un documento | `documentos_persona`, `documentos_faltantes`, `leer_documento` |

## Otros
Correo (`correos_sin_leer`, `buscar_correos`, `preparar_respuesta`…), trabajo temporal (`trabajadores_tt`,
`boletines_tt`, `estimar_coste_tt`, `anomalias_tt`, `comunicaciones_tt`), panel de RRHH (`panel_rrhh`),
altas, calidad de datos e informes PDF/Excel/PowerPoint (`generar_informe`). Cualquier pregunta general
(fuera de Sunset Beach Club) se responde con el conocimiento del modelo y la búsqueda web.


## Correo desde la pantalla
Cada correo del listado tiene **Abrir correo** y **Proponer respuesta**. Un borrador se muestra como tarjeta con
**Confirmar y enviar** (pide una segunda confirmación y solo se habilita si el envío está activado), **Modificar** y
**Descartar**. Nada se envía sin que el usuario lo confirme en su último mensaje.

## Gráficos y fuentes
- Los recuentos por categorías (p. ej. empleados por departamento) se dibujan como **barras**, **anillo** (hasta 6
  categorías) o **línea** (series por mes o día), en pantalla y en los informes (PDF, Excel y PowerPoint).
- Las consultas externas (búsqueda web) muestran **enlaces a las fuentes** consultadas; son solo http(s), sin
  duplicados y sin el rastreo del proveedor.
- Todos los informes llevan el **logo de Sunset Beach Club** en la cabecera.
