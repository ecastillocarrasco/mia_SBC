# Arquitectura de mIA

## Identidad de producto y estado actual

mIA es el asistente conversacional de toda la organización. La arquitectura objetivo es un
orquestador común con dominios independientes (Community, RRHH, Correo, Legal, Finance, etc.),
cada uno con sus herramientas, fuentes y permisos de Entra ID. `Global` es el rol administrador
con acceso completo. Community es transversal y no exige permisos de dominio.

El producto todavía no ha alcanzado toda esa separación: RRHH es el dominio funcional más completo;
Finanzas e IT son registros parciales. Correo ya está separado como paquete/dominio en
`mia.modules.correo`; su lectura se habilita para todos los roles autenticados y se resuelve al buzón
de la sesión, mientras que el envío mantiene permiso propio. No se debe presentar la lista de
dominios objetivo como funcionalidades ya disponibles.

Las cuatro experiencias objetivo (web 2D, web 3D, holograma y mIA Desktop) deben compartir API,
identidad, permisos y capacidades; la presentación puede variar por cliente, nunca el alcance de
datos. La integración efectiva de cada cliente debe verificarse al incorporarlo. Las futuras acciones
de escritura (por ejemplo, actualizar SharePoint) deben añadir permisos por acción, validación de
parámetros, confirmación explícita de operaciones sensibles y auditoría antes de habilitarse.

## Principios

1. **Un solo flujo conversacional.** El LLM recibe la pregunta y herramientas
   tipadas; decide cuáles usar y con qué parámetros. La ejecución es código
   determinista. No hay reglas por frase ni recompilación a texto.
2. **Los datos salen solo de las herramientas.** El LLM narra; nunca inventa ni
   reescribe datos. Lo que se pinta en pantalla (`presentation`) viaja aparte y
   llega al frontend tal como lo produjo la herramienta.
3. **Estado en el servidor.** El cliente envía `session_id` y el mensaje. El
   contexto que envíe el cliente se ignora.
4. **El personaje es una especificación única** (`conversation/persona.py`):
   tono, estados del avatar y reglas de voz. Cambiar de modelo no cambia a mIA.
5. **Fallar cerrado.** Configuración insegura en producción no arranca; una
   fuente caída se comunica como tal, nunca como un cero.
6. **Todo proveedor está abstraído** (LLM, voz, identidad) y tiene un doble
   falso para tests.

## Un turno de conversación

```
cliente ──POST /api/chat/stream──▶ motor
  1. transacción corta: sesión, historial, turno del usuario
  2. LLM (streaming) con herramientas permitidas al usuario
       ├─ si pide herramientas → frase de espera + avatar "concentrada"
       │                         ejecución en paralelo, validada y auditada
       │                         vuelta al LLM con los resultados
       └─ respuesta final JSON {habla, estado_avatar, texto}
            "habla" se extrae frase a frase mientras llega → evento speech
  3. transacción corta: respuesta, estado y auditoría
```

La base de datos nunca queda bloqueada mientras se espera al LLM.

Eventos SSE: `session`, `avatar`, `speech`, `progress`, `tool`, `result`.

## Latencia

El objetivo es el tiempo hasta el **primer audio**, no el tiempo total:

- La respuesta estructurada pone `habla` en primer lugar para poder locutarla
  antes de que termine el resto.
- Cada frase se emite en cuanto se completa (`conversation/speech.py`).
- Las frases fijas (esperas, errores) se generan una vez y se sirven desde caché.
- Las herramientas se ejecutan en paralelo con límite de tiempo individual.
- Prompt de sistema estable al principio de cada petición para aprovechar la
  caché de tokens del proveedor.

## Seguridad

- `auth/`: cada petición lleva un `UserContext`; cada herramienta declara el
  permiso que exige. **El LLM solo ve las herramientas permitidas** al usuario.
- Modos de identidad: `dev` (local, bloqueado en producción), `easyauth` y validación de tokens
  Entra ID. El proveedor configurado y los app roles deben coincidir con el despliegue real.
- Auditoría de accesos a datos personales (`audit_events`).
- Una sesión solo puede usarla su propietario.
- Secretos solo en Key Vault; la aplicación accede con identidad administrada.
- La voz nunca locuta salarios, identificadores, salud ni contacto (regla del
  personaje); el texto que va a ElevenLabs sale de Azure.

## Decisiones

| Decisión | Motivo |
|---|---|
| FastAPI + Pydantic | Contratos tipados, OpenAPI, async y streaming nativos |
| Monolito modular, no microservicios | Tamaño del equipo; fronteras internas limpias permiten separar después |
| PostgreSQL (JSONB) | Base única para estado, datos sincronizados, histórico y auditoría; pgvector para CV |
| API Responses con salida estructurada | Tool calling y JSON garantizado en la misma llamada |
| Alembic | Migraciones versionadas y reversibles |
| Bicep | Infraestructura reproducible en Azure |

## Capa de datos (fase 2)

```
SharePoint (RRHH) ──sincronización──▶ source_items (réplica, seudonimizada)
                                    └─▶ hr_* (modelo canónico) ◀── herramientas de mIA
```

- **Completa**: lee la lista entera siguiendo la paginación, reconstruye la tabla
  canónica y marca los borrados. El change token se toma antes de leer.
- **Incremental**: `GetChanges` con el change token; descarga solo los elementos
  cambiados por ID (columna siempre indexada: sin throttling en listas grandes).
- **Automática**: incremental cada 10 minutos y completa diaria; si el token
  caduca, completa.
- `source_sync_state` guarda el estado de cada fuente; `/api/admin/sources` lo
  expone y mIA podrá avisar cuando un dato no esté al día.
- **Privacidad**: los campos sensibles (DocIdentidad, DNIEmpleado) se sustituyen
  por un HMAC antes de escribir nada. Cuando haga falta el dato real (p. ej. para
  localizar la carpeta de nóminas) se consultará en el momento, sin persistirlo.
- Un elemento defectuoso no detiene la sincronización: se registra y se continúa.

## Herramientas de RRHH (fase 3)

| Dominio | Herramientas |
|---|---|
| Empleados | `buscar_empleado`, `ficha_empleado`, `plantilla`, `estructura_departamentos` |
| Turnos | `turnos_persona`, `turnos_dia`, `ausencias`, `reincorporaciones` |
| Vacaciones | `vacaciones`, `saldo_vacaciones`, `reincorporacion` |

- **Personas**: coincidencia por palabras sin tildes; activos primero; si hay varias,
  la herramienta devuelve `ambiguous` con los candidatos y mIA pregunta. Si no hay
  ninguna, sugiere nombres parecidos. Nunca elige al azar.
- **Foco**: las herramientas fijan `foco_persona`, `foco_departamento` y
  `foco_periodo`; el motor los resume en el prompt de cada turno para que «¿y su
  saldo?» use el `empleado_id` correcto.
- **Frescura**: cada resultado indica si sus fuentes están al día; si no, mIA lo avisa.
- **Reglas**: TUR-001/002 (franjas por inicio, presencia por solape), AUS-001 (periodo real de la
  ausencia), POB-001 (activos por defecto), VAC-001 (reincorporación = primer turno
  de trabajo publicado; si no hay, no se afirma), VAC-002 (saldos negativos), DAT-001.
- Lo que ve el modelo está limitado a 40 filas; la interfaz recibe la tabla completa.

## Privacidad, retención y almacenamiento

- Presidio inspecciona y anonimiza lo que sale hacia el proveedor LLM; no evita la persistencia local.
  Los mensajes y respuestas se guardan en `conversation_turns` y el foco conversacional en
  `conversation_sessions`. La aplicación elimina sesiones inactivas y sus turnos tras 30 días
  (configurable con `MIA_CONVERSATION_RETENTION_DAYS`); esa limpieza se ejecuta cada seis horas.
- El registro de auditoría (`audit_events`, evidencia de acceso a recursos sensibles para ENS/RGPD)
  conserva los argumentos reales de cada herramienta ejecutada. Se elimina tras 1095 días/3 años
  (configurable con `MIA_AUDIT_RETENTION_DAYS`, justificado por el plazo de prescripción de las
  infracciones muy graves del art. 76 LOPDGDD), con limpieza cada seis horas. Ver detalle en
  [auditoria_detalle/audit_ciclo_vida_datos.md](auditoria_detalle/audit_ciclo_vida_datos.md).
- Las trazas no conservan consulta ni respuesta libre cuando está activa la máscara de PII; en
  producción el código obliga a habilitar esa máscara si se activan los diagnósticos.
- Los informes viven en almacenamiento local durante desarrollo. Producción usa el contenedor
  privado Azure Blob con identidad administrada; el registro incluye el propietario, el permiso
  sensible y caducidad. La limpieza elimina blobs y registros caducados cada seis horas.
- El modelo documental, los gráficos y los renderizadores son ahora compartidos en `mia.reporting`;
  RRHH es el primer dominio conectado. La composición basada en datos de negocio y la orquestación
  conversacional todavía residen en herramientas de RRHH: eso sigue siendo trabajo para completar
  antes de llamar al motor transversal completo. El formato Word (DOCX) ya está habilitado junto a
  PDF, XLSX, PPTX y HTML.
- La retención propia de mIA no configura las políticas del proveedor LLM. La configuración de
  Azure, sus características habilitadas y el estado de Modified Abuse Monitoring deben verificarse
  en el recurso y la suscripción; el código por sí solo no puede garantizar que Microsoft no conserve
  contenido marcado para revisión.

## Fase 4: resto de dominios

| Dominio | Herramientas | Fuente |
|---|---|---|
| Selección | `buscar_candidatos`, `candidaturas`, `ficha_candidato` | CurriculosVitae + CVDocs (texto extraído y embeddings) |
| Correo | `correos_sin_leer`, `buscar_correos`, `leer_correo`, `preparar_respuesta`, `enviar_borrador` | Microsoft Graph, en el momento |
| Nóminas | `nominas_persona`, `nominas_periodo` | Biblioteca Nominas (solo metadatos) |
| Documentación | `documentos_persona`, `documentos_faltantes` | DocumentosFirmadosV2 (solo tipo) |
| Trabajo temporal | `trabajadores_tt`, `boletines_tt` | EmpresasTT, EmpleadosTT, BoletinesTT |
| Informes | `generar_informe` | Última tabla de la conversación → PDF/Excel |

- **Interruptores**: `MIA_DOMAINS__ENABLED`. Un dominio desactivado no se ofrece al modelo,
  no se sincroniza y mIA lo declara como no disponible.
- **Carpetas por DNI/NIE** (nóminas y documentos): al sincronizar, las rutas se
  seudonimizan y cualquier DNI/NIE de los nombres de fichero se oculta. El cruce con la
  plantilla se hace por el mismo seudónimo HMAC que Empleados y Turnos.
- **CVs**: el texto se extrae una vez por versión del fichero (`hr_cv_texts`), fuera del
  ciclo de sincronización; la búsqueda se hace en memoria sobre embeddings normalizados.
  Con ≈1.400 CVs responde en milisegundos; si el volumen crece se pasará a pgvector sin
  cambiar las herramientas.
- **Correo (COR-001)**: enviar exige un borrador preparado en un turno anterior y la
  confirmación expresa en el mensaje actual; además `MIA_MAIL__SEND_ENABLED`. Las tres
  condiciones se comprueban en código.
- **Informes**: solo los descarga quien los pidió y caducan (`MIA_REPORTS__TTL_HOURS`).
  En producción conviene moverlos a Blob Storage (la cuenta ya está en la infraestructura).
- **CI**: toda la batería se ejecuta también contra PostgreSQL, además de subir y bajar
  las migraciones.


## Correo y autenticación

El dominio independiente `mia.modules.correo` resuelve el buzón personal por el `oid` inmutable del usuario Entra
y conserva la identidad del buzón al que pertenecen las referencias de mensajes y borradores:

| Fase | `MIA_MAIL__MAILBOX_SOURCE` | Buzón |
|---|---|---|
| Desarrollo (`MIA_AUTH__MODE=dev`) | `configured` | El declarado en `.env` (`MIA_MAIL__MAILBOX`), para pruebas |
| Usuario autenticado (Entra ID, OBO) | `user` | `/users/{oid}` para su cuenta; si indica un compartido, `/users/{UPN o dirección}` |

Garantías ya en su sitio, para que el cambio sea solo de configuración:

- Cada referencia y borrador queda ligado al buzón de origen. La persona puede pedir un buzón compartido concreto,
  pero el acceso delegado a Graph y los permisos efectivos de Exchange deciden si puede leer, modificar o enviar.
- Las instrucciones al modelo llevan el buzón del usuario **en cada turno**, no uno fijo al arrancar.
- La cuenta personal se direcciona por el `oid` firmado de Entra; el buzón configurado solo se usa en desarrollo.

**Autenticación delegada implementada, pendiente de habilitar en Entra/despliegue.** En modo `MIA_AUTH__MODE=entra`,
la API valida el token de la persona y lo intercambia mediante OBO por un token delegado de Graph. Los buzones
compartidos se solicitan por su dirección/UPN explícitos; Graph y Exchange aplican los permisos efectivos de esa
persona. No hay una lista global de buzones compartidos: las personas pueden tener accesos distintos.
Para ello se necesitan permisos delegados `Mail.*.Shared` y
permisos Full Access/Send As según las operaciones. El certificado de la app sigue siendo necesario para OBO y debe
estar registrado en la misma app API cuyo ID recibe el token. El modo `easyauth` no proporciona el token de entrada
necesario para OBO en esta implementación; el despliegue debe habilitar el modo `entra` y exponer el scope API de
mIA. Mantener permisos de aplicación Mail en Entra conservaría un acceso app-only paralelo: retirarlos solo después
de probar OBO con una cuenta propia, un buzón compartido autorizado y otro no autorizado.
