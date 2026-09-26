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
