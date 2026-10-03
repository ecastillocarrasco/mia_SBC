# Arquitectura de mIA

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
- Modos de identidad: `dev` (local, bloqueado en producción) y `easyauth`
  (Azure). Entra ID con MSAL se añadirá como un proveedor más.
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

El buzón se resuelve en un único punto (`mia/modules/rrhh/correo/mailbox.py`) a partir del usuario de la sesión:

| Fase | `MIA_MAIL__MAILBOX_SOURCE` | Buzón |
|---|---|---|
| Desarrollo (hoy) | `configured` | El declarado en `.env` (`MIA_MAIL__MAILBOX`), el mismo para todos |
| Con MSAL / Entra ID (fase 7) | `user` | El de la cuenta con la que inicia sesión cada usuario (`UserContext.email`) |

Garantías ya en su sitio, para que el cambio sea solo de configuración:

- Las herramientas de correo **no reciben el buzón como parámetro**: ni el modelo ni el usuario pueden apuntar a la
  bandeja de otra persona.
- Cada **borrador queda ligado al buzón** en el que se creó; otro usuario no puede enviarlo aunque comparta sesión.
- Las instrucciones al modelo llevan el buzón del usuario **en cada turno**, no uno fijo al arrancar.
- Si la sesión no trae email/UPN, el correo se declara no disponible en lugar de abrir otro buzón.

**Decisión pendiente para la fase 7.** Hoy Graph se llama con la aplicación (certificado) sobre `users/{buzón}`.
Con buzones personales hay dos caminos: (1) **permisos delegados**, usando el token del propio usuario (flujo
on-behalf-of): cada persona solo puede ver su bandeja y no hace falta conceder acceso a toda la organización; es
lo recomendable; (2) **permisos de aplicación** con una *Application Access Policy* de Exchange que limite a qué
buzones puede entrar la aplicación (sin ella, `Mail.Read` de aplicación da acceso a todos los buzones del tenant).
