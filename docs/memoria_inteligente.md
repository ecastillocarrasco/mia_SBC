# mIA — Memoria Inteligente V1

Fecha: 1 de noviembre de 2026. Repositorio: `C:\Users\enriq\Desktop\Proyectos\Sunset\mIA`.
Capacidad 6 de «las diez capacidades» (`RELEVO-MIA-COMPLETO.md`: «Memoria contextual
corporativa»). Este documento describe el **alcance reducido V1** entregado ahora, no la
capacidad completa — ver «Lo que NO es esto todavía» más abajo.

## Estado de entrega

Implementado y probado (backend: herramientas, repositorio, motor, endpoints, migración;
frontend: control visual en los cuatro mundos — 2D, 3D, Holograma y mIA Desktop). **Desactivado
por defecto** en dos niveles independientes:

1. Interruptor global (`MIA_MEMORY__ENABLED=false` por defecto): con él apagado no se registra
   ninguna herramienta, el endpoint responde `available:false` sin dar error, y el control visual
   no se muestra en ningún mundo (en Desktop, el checkbox aparece deshabilitado con el aviso
   correspondiente en vez de desaparecer — ver sección B).
2. Interruptor por usuario (`MemoryPreference.enabled`, `False` por defecto): cada usuario decide
   si quiere que mIA guarde o use recuerdos suyos, independientemente del interruptor global. Es
   el **backend** quien guarda esta decisión (nunca `localStorage` ni la configuración local de
   Electron), así que es la misma en los cuatro mundos y persiste entre sesiones y reinicios.

No se ha desplegado a PRE.

## A. Qué guarda y qué no

Solo recuerdos que el usuario pide guardar **expresamente** («mIA, recuerda que…», «acuérdate de
que…», «no olvides que…», «apunta que…» — tolerante a variación de lenguaje natural, no una
frase exacta). Activar la memoria **no** implica que mIA empiece a resumir o guardar
conversaciones por su cuenta: sin una petición explícita, no se crea ningún recuerdo.

### Aislamiento entre memoria y el historial conversacional operativo

Son dos cosas distintas, con tablas, ciclo de vida y políticas de retención independientes —
**no se ha tocado la política de conservación del historial existente**:

| | Historial conversacional | Memoria Inteligente |
|---|---|---|
| Tablas | `conversation_sessions`, `conversation_turns` | `user_memories`, `memory_preferences` |
| Qué guarda | Cada mensaje y respuesta, para dar contexto a la conversación en curso | Solo lo que el usuario pide expresamente recordar |
| Retención | Purga automática a los `conversation_retention_days` (30 días por defecto) — `mia.conversation.retention.run_retention_cleanup` | **Sin caducidad automática en V1**: se conserva indefinidamente hasta que el usuario borra ese recuerdo (o todos) expresamente |
| Alcance | Por sesión (`session_id`) | Por usuario (`user_id`), nunca por sesión ni por dispositivo — por eso se recupera y se activa/desactiva igual en 2D, 3D, Holograma y mIA Desktop |

## B. Arquitectura

- **Migración** `migrations/versions/0015_memoria_inteligente.py` (`EXPECTED_REVISION = "0015"`):
  tablas `user_memories` (`id`, `user_id`, `content`, `created_at`, índice compuesto
  `user_id, created_at`) y `memory_preferences` (`user_id` PK, `enabled`, `updated_at`).
- **Modelos**: `mia.data.models.UserMemory`, `mia.data.models.MemoryPreference`.
- **Repositorio**: `mia.data.repositories.MemoryRepository` (capa de datos, no en
  `mia.modules.memoria`, para que el propio motor de conversación pueda usarlo directamente sin
  depender de un paquete de dominio — ver el docstring de la clase). Aislamiento: toda consulta
  filtra por `user_id`; `delete_memory` trata un recuerdo ajeno igual que uno inexistente.
- **Permiso**: `Permission.MEMORIA_USAR`, en `_UNIVERSAL_CON_ROL` (`mia.auth.context`) — igual que
  `CORREO_LEER`/`NOTICIAS_LEER`: cualquier usuario con algún rol reconocido, nunca quien no tiene
  ninguno. Es un dato personal del propio usuario, no un privilegio de un rol de negocio.
- **Ajustes**: `mia.settings.MemorySettings` (`enabled`, `max_items_per_user`=50,
  `max_content_chars`=500, `max_items_in_context`=20) bajo `Settings.memory`
  (`MIA_MEMORY__*`).
- **Herramientas conversacionales** (`mia.modules.memoria.tools`, registradas solo si
  `settings.memory.enabled`): `recordar`, `ver_recuerdos`, `olvidar_recuerdo` (borra por
  coincidencia de texto, sin tildes/mayúsculas — no necesita un ID), `olvidar_todo` (exige
  `confirmar=true` explícito), `ajustar_memoria` (activar/desactivar conversacionalmente).
- **Recuperación pasiva** (`mia.conversation.memory_hint.memory_context_block`, invocada desde
  `ConversationEngine._load_memory_items`/`_prepare_request`): si el usuario tiene la memoria
  activada, sus recuerdos más recientes (hasta `max_items_in_context`) se añaden al contexto de
  cada turno — así no hace falta preguntar «qué recuerdas de mí» para que se tenga en cuenta.
  Deliberadamente fuera del bloque de sistema cacheado (`capabilities_for`): varía por usuario y
  por turno, igual que el resto de pistas de `_prepare_request` (foco, módulo detectado…).
- **Endpoints REST** (`mia.api.routes.memory`, prefijo `/api/memory`, exigen
  `Permission.MEMORIA_USAR`): `GET/PUT /settings` (activar/desactivar — nunca 404 aunque el
  interruptor global esté apagado: responde `available:false`), `GET /items`, `DELETE
  /items/{id}`, `DELETE /items` (borrar todo). Pensados para el control visual, no dependen del
  LLM para encender/apagar o borrar.
- **Control visual** (`frontend/src/core/memory-widget.js`, `mountMemoryWidget()`): botón
  flotante discreto (esquina inferior izquierda, para no chocar con los controles ya existentes
  en la inferior derecha de los tres mundos) que se monta solo — crea su propio DOM e inyecta su
  propio CSS, sin tocar el HTML de ningún mundo. Si el endpoint de ajustes responde
  `available:false` o falla, no se muestra nada (ver «si la memoria falla, el resto de mIA sigue
  funcionando»). Montado en los tres mundos web reales: `worlds/2d/mia-entry-v530.js` (el 2D de
  producción, `mia-2d.html`; **no** en `worlds/2d/main.js`/`src/worlds/2d/index.html`, que no está
  enlazado desde la portada y no es el entry real), `worlds/3d/main.js`, `worlds/hologram/main.js`.
- **Control visual en mIA Desktop** (Electron): un checkbox «Memoria inteligente» en el panel de
  Configuración ya existente (`mia-desktop/src/ui/settings.html`), con su propia sección nueva —
  nunca se mezcla con `cfg`/`state.config` (la configuración LOCAL de Electron que gestiona el
  botón «Guardar configuración»): se consulta y se aplica al vuelo, inmediatamente al marcar o
  desmarcar, directamente contra el backend. El renderer de Configuración tiene
  `connect-src 'none'` en su CSP (no puede hacer `fetch` propio): la petición real la hace el
  proceso principal, con la misma puerta de autenticación que el resto de Desktop
  (`mia-desktop/src/auth.cjs`, MSAL nativo) — dos funciones nuevas en `backend.cjs`
  (`getMemorySettings`, `setMemoryEnabled`) que llaman a los mismos endpoints
  `/api/memory/settings` que los otros tres mundos, dos canales IPC nuevos en `main.cjs`
  restringidos a la ventana de Configuración (`ownSender(event, [settingsWin])`, igual que
  `mia:probe-voice`/`mia:open-diagnostics`) y dos métodos nuevos expuestos en `preload.cjs`. Sin
  lista ni borrado de recuerdos individuales en Desktop (no pedido): solo el interruptor —
  consultar/borrar recuerdos sigue siendo conversacional («qué recuerdas de mí», «olvida que…») en
  los cuatro mundos, Desktop incluido, vía `sendPrompt`. Comportamiento ante fallos, reflejado en
  el texto de estado junto al checkbox (`#memoryStatus`): sesión caducada o sin permiso
  (401/403) → checkbox deshabilitado con aviso de volver a iniciar sesión; interruptor global
  apagado (404 al cambiarlo, o `available:false` al consultarlo) → deshabilitado con aviso de «no
  activada en este despliegue»; fallo de red → mensaje de error, el checkbox revierte al estado
  anterior en vez de quedarse en un valor no confirmado.

## C. Pendiente explícito (no es esto todavía)

- **Sin búsqueda semántica**: `olvidar_recuerdo` compara texto normalizado (sin tildes/mayúsculas,
  `mia.text.normalize_key`), no embeddings. Dado que no hay búsqueda semántica en V1, el riesgo
  de «una búsqueda semántica recupera recuerdos ajenos» (mencionado en el encargo de la capacidad
  completa) no aplica todavía — el aislamiento real hoy es SQL filtrado por `user_id`, verificado
  en `tests/test_memoria.py::test_two_users_never_see_each_others_memories`.
- **Sin resumen automático de conversaciones**: solo peticiones explícitas.
- **Sin memoria departamental/organizacional**: estrictamente por usuario.
- **Sin caducidad, corrección ni revalidación de permisos al recuperar** (sí previstas en la
  capacidad completa — «Memoria contextual corporativa» en `RELEVO-MIA-COMPLETO.md`).
- **Sin inteligencia proactiva** sobre los recuerdos (p. ej. sugerir guardar algo detectado solo).
- **Sin lista/borrado individual de recuerdos en el checkbox de Desktop** (no pedido en este
  encargo): esa parte sigue siendo conversacional en los cuatro mundos.
- **Validación manual de Desktop pendiente de ejecutar con un backend y una cuenta Entra reales**:
  lo automatizado (`mia-desktop/tests/backend.test.cjs`) cubre la lógica de `getMemorySettings`/
  `setMemoryEnabled` con `fetch` simulado (éxito, 401/403, 404 con interruptor global apagado,
  fallo de red, JSON inválido) — **no** se ha abierto la app Electron real para comprobar
  visualmente el checkbox, ni se ha reproducido con una cuenta real: cerrar/abrir Desktop, cambiar
  de usuario, o cambiar la preferencia desde otro mundo y ver el reflejo en Desktop. No se declara
  superada ninguna de esas comprobaciones manuales — quedan para cuando haya un entorno con
  backend y login reales disponible.

## D. Archivos

### Nuevos
`migrations/versions/0015_memoria_inteligente.py`, `src/mia/modules/memoria/__init__.py`,
`src/mia/modules/memoria/tools.py`, `src/mia/conversation/memory_hint.py`,
`src/mia/api/routes/memory.py`, `frontend/src/core/memory-widget.js`,
`frontend/tests/memory-widget.test.mjs`, `tests/test_memoria.py`, este documento.

### Modificados
`src/mia/data/models.py` (`UserMemory`, `MemoryPreference`), `src/mia/data/__init__.py`,
`src/mia/data/repositories.py` (`MemoryRepository`, `MemoryLimitReachedError`),
`src/mia/data/schema.py` (`EXPECTED_REVISION`, `memory_enabled` en `schema_problem`),
`src/mia/settings.py` (`MemorySettings`), `src/mia/auth/context.py` (`Permission.MEMORIA_USAR`),
`src/mia/conversation/engine.py` (inyección pasiva, `_module_hint` con aviso si está apagada
globalmente), `src/mia/api/services.py`, `src/mia/api/schemas.py`, `src/mia/api/routes/health.py`,
`src/mia/main.py`, `frontend/src/worlds/2d/mia-entry-v530.js`, `frontend/src/worlds/3d/main.js`,
`frontend/src/worlds/hologram/main.js`, `mia-desktop/src/backend.cjs` (`getMemorySettings`,
`setMemoryEnabled`), `mia-desktop/src/main.cjs` (canales IPC `mia:get-memory-settings`,
`mia:set-memory-enabled`), `mia-desktop/src/preload.cjs`, `mia-desktop/src/ui/settings.html`
(sección «Memoria inteligente»), `mia-desktop/src/ui/settings.js` (`refreshMemory`,
`describeMemoryState`), `mia-desktop/tests/backend.test.cjs`.

## E. Pruebas ejecutadas

`tests/test_memoria.py` (13 casos): interruptor global (sin herramientas registradas si está
apagado), interruptor por usuario (recordar no hace nada hasta activarla; recuerdos conservados
al desactivarla, invisibles mientras tanto, visibles de nuevo al reactivarla), guardado/listado,
borrado por lenguaje natural sin tildes/mayúsculas, confirmación obligatoria antes de borrar todo,
límite por usuario sin error, aislamiento entre dos usuarios, inyección pasiva en el contexto del
motor (presente si está activada, ausente si no), y los cuatro endpoints REST (incluida la
respuesta `available:false`/404 con el interruptor global apagado). `tests/test_migrations.py`
verifica que la migración 0015 coincide exactamente con los modelos. Suite completa de Python
ejecutada dos veces (antes y después de la integración de Desktop) sin regresiones.

`frontend/tests/memory-widget.test.mjs` (4 casos, con el loader `tests/support/css-stub-loader.mjs`
que ya usaba el proyecto para este mismo problema): no se muestra nada con la memoria apagada
globalmente ni si la primera consulta falla; se monta el botón/panel y el interruptor activa y
desactiva correctamente; borrar todos los recuerdos pide confirmación. Build de Vite del frontend
sin errores.

`mia-desktop/tests/backend.test.cjs` (5 casos nuevos sobre `getMemorySettings`/
`setMemoryEnabled`, con `fetch` simulado como el resto del fichero): la consulta y el cambio usan
el endpoint real `/api/memory/settings` (nunca configuración local); sesión caducada o sin permiso
(401/403) se informa como tal sin lanzar excepción; con el interruptor global apagado (404),
responde `available:false` con un aviso claro en vez de un error genérico; un fallo de red no
lanza excepción en ninguna de las dos funciones. Suite completa de `mia-desktop` ejecutada
(`npm test`): 125 pruebas, 122 superadas, mismos 3 fallos preexistentes de antes de este cambio
(no relacionados — confirmado por el delta exacto: +5 pruebas nuevas, +5 superadas, 0 fallos
nuevos): uno sensible a fin de línea CRLF/LF en `desktop-v025.test.cjs` (entorno, no código) y dos
en `mail-watch.test.cjs` por llamar a `checkOnce()` sin pasar antes por `start()`, un camino que
nunca ocurre en producción.

**No ejecutado — validación manual pendiente**: abrir la app Electron real, iniciar sesión con una
cuenta de verdad, marcar/desmarcar el checkbox y comprobarlo visualmente; cerrar y volver a abrir
Desktop; cambiar de usuario; cambiar la preferencia desde 2D/3D/Holograma y comprobar que Desktop
la refleja al reabrir Configuración. Ver sección C.
