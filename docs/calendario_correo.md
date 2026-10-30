# mIA — Calendario, agenda y reuniones dentro de Correo

Fecha: 29 de octubre de 2026. Repositorio: `C:\Users\enriq\Desktop\Proyectos\Sunset\mia`.
Base de referencia: `main`, HEAD `d74a818`, con los cambios locales previos conservados.

## Estado de entrega

Implementado y comprobado mediante pruebas automatizadas con Microsoft Graph y LLM simulados. La integración real con Microsoft 365, el comportamiento del modelo real y la validación visual/manual de los cuatro clientes quedan pendientes. No se han enviado correos, creado reuniones reales, cambiado permisos de Entra, aplicado migraciones a bases reales ni realizado despliegues. No se han realizado commits ni cambios de rama.

La funcionalidad queda **desactivada por defecto**. No se ha editado `.env`, infraestructura, paquetes, versiones ni configuración de despliegue.

## A. Implementación

- Calendario forma parte de `correo`, sin un dominio funcional nuevo.
- Contrato `CalendarProvider`, modelos normalizados, declaración de capacidades y factoría por configuración. Microsoft 365 es el proveedor predeterminado; un proveedor desconocido falla explícitamente sin usar otra cuenta.
- Graph delegado mediante el cliente y OBO existentes. Las rutas de agenda parten de `/me`; no heredan el buzón configurado ni compartido de Correo. No se permite app-only para calendario personal.
- Calendarios autorizados, agenda diaria/semanal, próxima reunión, filtros, detalles, respuestas de asistentes, invitaciones pendientes, solapamientos, huecos y disponibilidad de asistentes cuando Graph permite consultarla. Paginación limitada y validación del destino de los enlaces siguientes.
- Fechas relativas resueltas en código, zona IANA por usuario con respaldo de la configuración corporativa, y rechazo de horas ambiguas/inexistentes durante cambios horarios si no se especifica desplazamiento UTC.
- Propuestas de creación, modificación, reprogramación, cancelación, aceptación, rechazo, respuesta provisional y propuesta de otro horario cuando el evento lo admite.
- Eventos de día completo, reuniones Teams y recurrencias. Creación de recurrencias diarias, semanales, mensuales absolutas y anuales absolutas; consulta y operaciones sobre ocurrencias o series explícitas. Las recurrencias relativas existentes se conservan al no modificarlas.
- Cancelación mediante la acción del proveedor con comentario/disculpa, sin duplicar el aviso mediante un correo separado. Rechazar una invitación no cancela la reunión del organizador.
- Preparación de reuniones con búsqueda de correo mediante la herramienta existente. Los extractos se identifican como insuficientes para afirmar acuerdos: se requiere leer el correo/hilo correspondiente.
- Creación de reunión desde un correo y respuesta opcional: se reutilizan borradores, firma y salvaguardas existentes. La respuesta se envía solo después de verificar la reunión; el resultado parcial queda registrado y no repite la creación.
- Descripciones de reuniones online: al actualizar el texto se conserva el contenido previo requerido por Teams.

### Herramientas conversacionales

`calendarios_disponibles`, `consulta_agenda`, `detalle_reunion`, `disponibilidad_agenda`, `proponer_reunion`, `ejecutar_propuesta_agenda`, `preparar_reunion`.

Las propuestas muestran operación, fechas, zona, asistentes, alcance de recurrencia, comunicaciones y conflictos detectados. La confirmación admite «sí, confirmo» o «adelante» en un turno posterior si existe una única propuesta pendiente. Si hay varias, se solicita «confirma cambio 1» u otra referencia legible, sin mostrar GUID. El cliente no puede autorizar una operación mediante contexto enviado desde la pantalla.

La propuesta persistida se vincula al usuario, ámbito de conversación, proveedor y parámetros. Antes de ejecutar se comprueban caducidad, integridad y estado actual del evento/borrador. Si cambian, se requiere otra propuesta. Una transición atómica impide ejecutar dos veces la misma propuesta.

Los estados `running`, `applied`, `unknown` y `partial` no habilitan reintentos. Si la respuesta externa es incierta, se informa y se requiere comprobar el calendario; una propuesta distinta no debe utilizarse para reintentar a ciegas. Una interrupción entre Graph y la persistencia puede dejar `running`; se conserva el bloqueo y requiere reconciliación manual.

La verificación posterior compara los campos disponibles del evento. La propuesta de otro horario se marca como aceptada por Graph pero con entrega al organizador pendiente de verificar. `verified` en las pruebas significa comparación contra Graph simulado; no acredita integración real.

## B. Archivos

### Nuevos

| Archivo | Responsabilidad |
|---|---|
| `src/mia/modules/correo/calendar/__init__.py` | Paquete opcional de agenda |
| `src/mia/modules/correo/calendar/models.py` | Contrato de proveedor, personas, eventos y recurrencia |
| `src/mia/modules/correo/calendar/providers.py` | Selección de proveedor |
| `src/mia/modules/correo/calendar/microsoft365.py` | Adaptación de Microsoft Graph y normalización |
| `src/mia/modules/correo/calendar/agenda.py` | Fechas, zonas horarias, huecos y solapamientos |
| `src/mia/modules/correo/calendar/service.py` | Propuestas, validaciones, ejecución y verificación |
| `src/mia/modules/correo/calendar/store.py` | Persistencia, transición atómica, auditoría y retención |
| `src/mia/modules/correo/calendar/mail.py` | Coordinación con herramientas de Correo existentes |
| `src/mia/modules/correo/calendar/tools.py` | Herramientas tipadas e instrucciones condicionadas |
| `src/mia/data/calendar.py` | Modelo aislado de operaciones |
| `migrations/versions/0014_calendar_operations.py` | Tabla adicional, sin alterar tablas existentes |
| `tests/test_calendar.py` | Pruebas específicas y contratos conversacionales |
| `docs/calendario_correo.md` | Este informe y guía de activación |

### Existentes modificados

| Archivo | Motivo y compatibilidad |
|---|---|
| `src/mia/settings.py` | Configuración opcional anidada; confirmación obligatoria |
| `src/mia/modules/correo/__init__.py` | Mantiene el registro original y añade agenda solo al activarla |
| `src/mia/api/services.py` | Permite construir el cliente Graph para agenda sin exigir buzón de correo configurado |
| `src/mia/connectors/graph.py` | Política opcional sin reintentos de escritura; conserva el valor anterior para llamadas existentes y añade clasificación de resultados inciertos |
| `src/mia/conversation/engine.py` | Vocabulario/instrucciones de agenda solo si sus herramientas están registradas; evita confundir una reunión de Sistemas/Finanzas con dominios sin herramientas |
| `src/mia/data/__init__.py` | Registro del modelo en metadatos |
| `src/mia/data/schema.py` | Revisión 0014; admite 0013 si agenda está desactivada |
| `src/mia/api/routes/health.py` | Exige la nueva revisión únicamente con Correo y calendario activos |
| `src/mia/main.py` | Comprobación de esquema y ciclo de retención condicional de propuestas |

No se modifica el mapa de roles de autenticación. Se reutilizan `CORREO_LEER` para consultas y `CORREO_ENVIAR` para propuestas/ejecuciones, además de la autorización real de Graph. La resolución de nombres de empleados comprueba `EMPLEADOS_LEER` y reutiliza el resolutor existente; si no puede resolver un nombre de forma inequívoca, solicita aclaración. Las direcciones deben proceder del usuario o de una fuente autorizada, nunca ser inventadas por el modelo.

Los cambios locales previos de informes, trabajo temporal, comparaciones y documentos permanecen ajenos a esta entrega. La ampliación posterior solicitada por el usuario añade una vista de calendario en los paneles de resultados de 2D, 3D, Holograma y Desktop; conserva la navegación.

## C. Configuración

```env
MIA_MAIL__CALENDAR__ENABLED=false
MIA_MAIL__CALENDAR__DEFAULT_PROVIDER=microsoft365
MIA_MAIL__CALENDAR__CONFIRM_MUTATIONS=true
MIA_MAIL__CALENDAR__PROPOSAL_TTL_SECONDS=900
```

Zona horaria específica por identificador `oid` de usuario, opcional:

```env
MIA_MAIL__CALENDAR__USER_TIMEZONES={"oid-del-usuario":"Europe/Madrid","otro-oid":"America/New_York"}
```

Sin preferencia individual, se reutiliza `MIA_TIMEZONE` como zona de la instalación. El código no introduce un modelo multiempresa que no exista previamente. Las confirmaciones no se pueden desactivar: `false` en `CONFIRM_MUTATIONS` provoca error de configuración.

Con calendario desactivado no se registran sus herramientas ni se realizan sus llamadas Graph ni se inicia su tarea de retención. La revisión 0013 sigue siendo válida para las capacidades anteriores. El registro y los esquemas originales de Correo tienen una prueba de equivalencia.

## D. Microsoft Graph y seguridad

El usuario confirma que los permisos están asignados en Entra. No se ha consultado ni modificado la aplicación registrada ni inspeccionado un token real en esta sesión. Debe comprobarse en integración que son **delegados**, están consentidos y llegan al flujo OBO de la API mIA. Los permisos de aplicación no se utilizan como alternativa.

- Consulta de detalles y descripción: `Calendars.Read` o el permiso superior correspondiente.
- Creación, cambios, cancelación y respuestas: `Calendars.ReadWrite` delegado para el calendario del usuario.
- La coordinación de correo conserva los permisos delegados y restricciones ya utilizados por Correo; no concede privilegios nuevos.
- No se añaden permisos de directorio ni `People.Read`: se utiliza el resolutor autorizado existente, direcciones expresas o participantes de correos/eventos autorizados.
- Graph valida cada acceso. Una denegación o sesión caducada no se convierte en una agenda vacía ni provoca fallback a una cuenta técnica.

Referencias: [crear eventos](https://learn.microsoft.com/en-us/graph/api/calendar-post-events?view=graph-rest-1.0), [cancelar eventos como organizador](https://learn.microsoft.com/en-us/graph/api/event-cancel?view=graph-rest-1.0), [permisos de Graph](https://learn.microsoft.com/en-us/graph/permissions-reference).

Auditoría: usuario, operación, proveedor, referencia de operación/evento, fecha, estado y tipo de error. No se incluyen tokens ni cuerpos de correo en los nuevos detalles de auditoría. Las propuestas y resultados contienen datos necesarios para revisar/revalidar; su limpieza usa `conversation_retention_days`, cada seis horas cuando calendario está activo. La auditoría conserva la política existente. Si se desactiva calendario, su tarea de limpieza se detiene: los registros anteriores requieren la política operativa de conservación/borrado de la instalación.

## E. Pruebas y limitaciones

- Batería ampliada: **214 pruebas Python aprobadas**, con calendario, Correo, resumen, herramientas, autenticación, orquestación, migraciones, chat, compatibilidad, dominios, salud y continuaciones conversacionales.
- Repetición tras revisión: **71 pruebas aprobadas** de calendario, salud, migraciones y configuración de autenticación.
- Comprobación final de desactivación/factoría y selección de proveedor: **5 pruebas aprobadas**, incluidas dos pruebas adicionales; la suite específica de calendario contiene 59 casos.
- **28 pruebas JavaScript aprobadas** de presentación de Correo, holograma y backend/presentación de Desktop.
- **3 pruebas de Privacy Gateway + Correo aprobadas** utilizando la lista PSL incluida en `tldextract`, sin acceso a red ni caché en `site-packages`. La ejecución inicial estándar falló por la restricción de escritura de esa caché; no se modificó el código de mIA para resolverlo.
- La suite nueva cubre además selección de proveedores por configuración, registro desactivado, agenda, zonas horarias, cambio horario, confirmación vinculada a propuesta, usuario/sesión incorrectos, caducidad, concurrencia, alteración de propuesta/evento/borrador, direcciones inventadas, nombres ambiguos, recurrencias, día completo, Teams, errores Graph, resultado incierto y acciones compuestas con resultado parcial.
- Contratos `/api/chat`, `/api/mia/v4/chat`, SSE y NDJSON comprobados con Graph/LLM simulados. Son pruebas de transporte/presentación estructurada, no validación visual de los clientes ni evaluación de comprensión de un LLM real.
- Migraciones probadas sobre SQLite temporal; DDL PostgreSQL generado sin conectar a una base real. No se ha comprobado aplicación/concurrencia sobre PostgreSQL real.
- Ruff pasa en los archivos nuevos y los demás puntos pequeños de integración; formato comprobado en esos archivos. `engine.py` y `main.py` conservan las mismas 20 advertencias previas de importación diferida/complejidad, con las nuevas inserciones limitadas a calendario.
- Mypy pasa en el nuevo paquete de calendario y modelo. El análisis global devuelve **175 errores**, idénticos por archivo y mensaje al código anterior, incluidos los cambios locales previos. No se han corregido incidencias ajenas.

No se ha ejecutado toda la batería del proyecto ni se declara ausencia absoluta de regresiones. Quedan pendientes pruebas reales de permisos, consentimiento/OBO, disponibilidad de otros asistentes, respuestas y notificaciones, propuestas de nuevo horario, recurrencias complejas y validación manual de 2D, 3D, Holograma y Desktop.

## F. Activación en PRE — instrucciones, no ejecutadas

1. Conservar la versión actual y una copia de seguridad de la base; revisar este cambio mediante el procedimiento habitual.
2. Mantener `MIA_MAIL__CALENDAR__ENABLED=false` al introducir el código. Comprobar la funcionalidad actual de Correo. No requiere la tabla nueva mientras agenda esté desactivada.
3. Con autorización operativa independiente y apuntando expresamente a PRE, aplicar la migración incremental con el procedimiento Alembic existente hasta `0014`. No altera tablas anteriores ni copia calendarios externos.
4. Confirmar los permisos delegados indicados, certificado/OBO y una cuenta de pruebas. No sustituir la autenticación de correo ni ampliar acceso global.
5. Configurar el proveedor y las zonas horarias apropiadas. Activar `MIA_MAIL__CALENDAR__ENABLED=true` mediante el mecanismo actual de configuración/reinicio.
6. Validar lectura con la cuenta de pruebas y, tras autorización explícita para efectos externos, crear/modificar/cancelar únicamente convocatorias de prueba. Comprobar notificaciones únicas y resultados parciales.
7. Comprobar manualmente los cuatro clientes y repetir los casos negativos de usuario sin permiso y calendario no autorizado.
8. Para desactivar, cambiar `ENABLED=false` y seguir el procedimiento habitual de recarga/reinicio. Conservar la tabla para historial y reconciliación; no es necesario ejecutar un downgrade destructivo.

No se cambian IIS, proxies, puertos, servicios, imágenes ni paquetes de despliegue en esta entrega.

## G. Añadir otro proveedor posteriormente

Implementar `CalendarProvider`, traducir datos/errores en su adaptador, declarar capacidades reales y registrar su factoría en `calendar/providers.py`. Seleccionarlo por `DEFAULT_PROVIDER`. Reutilizar los contratos de agenda, confirmación, persistencia y presentación. Incorporar autenticación/autorización propia del proveedor sin reutilizar tokens de Microsoft. Añadir las pruebas de contrato y seguridad equivalentes. No se incluye ninguna integración real con Google en esta entrega.


## H. Mejora de presentación y confirmación — 29/10/2026

- Agenda estructurada de tipo `calendar`, con columnas por día, hora de inicio y fin, asunto, ubicación y detalle desplegable. No genera tarjetas KPI ni un indicador de total para los resultados de calendario.
- Componente compartido en 2D, 3D, panel privado de Holograma y resultados de Desktop. La proyección física del ventilador conserva la privacidad: avisa de que la agenda está disponible en el panel privado.
- Confirmación natural vinculada al usuario, conversación y propuesta persistida. Con varias propuestas se requiere una referencia legible. Se conservan caducidad, revisión de cambios, permisos e idempotencia; la unicidad se comprueba también al reclamar la operación.
- Fechas y horas completas en el resumen del cambio y en el detalle del evento, con zona horaria explícita.
- Verificación: 131 pruebas Python aprobadas; 21 pruebas JavaScript relevantes aprobadas; Ruff y Mypy del paquete (12 módulos) aprobados. Compilación web Vite aprobada. Inspección visual del componente compartido con datos simulados, incluyendo apertura del detalle y ambas horas.
- La batería general de frontend tiene comprobaciones históricas incompatibles con el código actual (por ejemplo exige `client.speak` aunque HEAD ya usa `hologramVoice.speak`), restricciones de alcance de antiguos parches y cargas CSS sin navegador. No se declara que toda esa batería pase.
- El build completo de Desktop no termina en este entorno restringido: esbuild intenta acceder a un directorio superior sin permiso. Se compiló el módulo de resultados con sus dependencias locales explícitas y se copió la hoja de estilos. No se generó instalador ni se actualizó una aplicación instalada.
- Para DEV: reiniciar backend; recargar con Ctrl+F5 los clientes web (o servir el build actualizado cuando no se usa Vite). Reiniciar Desktop de desarrollo. Una versión instalada requiere volver a empaquetar e instalar mediante el procedimiento habitual. Estas mejoras no añaden variables `.env` ni migraciones adicionales.


## I. Confirmación mediante clic

Las propuestas incluyen un botón «Sí, confirmo · cambio N» en los paneles de 2D, 3D, Holograma privado y Desktop. El botón envía `confirma cambio N` como un turno normal del chat; no llama directamente a Graph. Muestra los parámetros antes de confirmar y bloquea el doble clic. Si falla el transporte permite reintentar. La validación de usuario, sesión, propuesta, caducidad y ejecución única sigue en el backend. En Desktop, un canal IPC limitado a la ventana de resultados y al prompt de la propuesta mostrada traslada la confirmación al chat existente. La agenda y las propuestas abren automáticamente Resultados.

Validación posterior: 24 pruebas de calendario/presentación/botones y 25 de compatibilidad Desktop aprobadas; 15 pruebas Python de confirmación aprobadas. Ruff aprobado. Web compilado y módulos de resultados/chat Desktop compilados. Clic y desactivación comprobados visualmente con una propuesta simulada; no se modificó ninguna reunión real. No se ha probado el flujo completo en una aplicación Electron instalada.


## J. Filtro espurio en consulta de agenda

La traza de 29/10/2026 22:33 mostraba `consulta_agenda(periodo="mañana", filtro="Muestrame")`: el verbo de la petición se estaba interpretando como término de búsqueda y ocultaba las reuniones. Se reforzaron el esquema y las instrucciones para distinguir verbos de consulta de asuntos/personas y «mañana» de «por la mañana». Una comprobación determinista descarta un filtro que sea el verbo inicial de la petición, conservando filtros explícitos por asunto o citas. El resumen diferencia reuniones del intervalo y coincidencias del filtro. Pruebas con Graph simulado; no se cambiaron reuniones reales. Reiniciar el backend para cargar la corrección.


## K. Calendario al repetir una consulta

Una respuesta del LLM sin llamada a herramienta podía reutilizar el texto del historial y devolver cero presentaciones. Las consultas explícitas y sin filtros de «mi agenda/calendario/reuniones» para hoy, mañana o una semana consultan ahora `consulta_agenda` antes de redactar la respuesta. Cada turno recibe datos nuevos y su presentación, independientemente de que el LLM decida llamar herramientas. Se utiliza el registro autorizado de herramientas y no se fuerzan mutaciones, búsquedas filtradas ni agendas de terceros. Once pruebas aprobadas, incluida repetición en la misma sesión con una reunión nueva entre turnos y los contratos JSON/SSE/NDJSON. Se requiere reiniciar el backend; no cambia Vite ni el esquema de base de datos.
