# mIA Advanced Intelligence & Reporting Engine — seguimiento del proyecto (Bloque II)

Este archivo existe para que cualquier sesión futura pueda continuar este trabajo sin repetirlo ni
perder las decisiones ya tomadas. Léelo antes de tocar nada de lo listado aquí. El Bloque I
(`mia_privacy_gateway`) está documentado por separado en `PRIVACY_GATEWAY_PROGRESS.md` — no se repite
su contenido aquí, solo se referencia cuando es relevante para el motor de informes.

## Estado: Fase A — HECHA. Fase B — HECHA. Fase C — HECHA (alcance de esta ronda). Fase D — HECHA
(modelo documental completo, 8 tipos de bloque). Fase E — HECHA (PDF/XLSX/PPTX/HTML, los 4 formatos).
Fase F — EN CURSO (narrativa LLM + narrative_guard conectados y probados; planificador todavía sin
conectar a un pipeline real). Fase G — EN CURSO (motor de trabajos genérico hecho y probado; sin
conectar todavía a nóminas ni a la API/frontend). Fase H/I — sin empezar.

## 12. Fase G (Job Manager) — primer tramo: motor genérico real

- `src/mia/data/jobs.py` (nuevo modelo `ReportJob`) + migración Alembic
  `migrations/versions/0008_trabajos_de_informes_en_segundo_plano.py` — **verificada de verdad**:
  `alembic upgrade head --sql` genera el DDL completo y encadena limpiamente 0007→0008 (no solo "se
  escribió", se comprobó que aplica).
- `src/mia/reporting/job_manager.py` (nuevo): `submit()` (persistente, con idempotencia real —
  reintentar con la misma clave tras un fallo definitivo REUTILIZA la misma fila/`job_id`, no crea una
  duplicada), `claim_next()` (reparto entre workers sin duplicar trabajo: `UPDATE ... WHERE
  status='queued'` + `rowcount` para detectar la carrera perdida — portátil entre SQLite y PostgreSQL,
  sin depender de `SELECT FOR UPDATE` ni `RETURNING`), `heartbeat()`/`reap_stale_leases()` (recuperación
  tras caída de un worker: un lease vencido se libera para que otro worker lo reclame), `update_progress()`
  (progreso real, acotado 0–1), `complete()`/`fail()` (reintentos controlados hasta `max_attempts`, luego
  `FAILED` con el error visible — nunca un resultado incompleto disfrazado), `request_cancel()`/
  `check_cancel_requested()`/`finalize_cancelled()` (cancelación cooperativa: inmediata si estaba en
  cola, señalizada si ya estaba en curso, nunca una interrupción forzosa a mitad de escritura).
- Sin Celery, Redis ni ningún servicio externo nuevo — en proceso, respaldado por la tabla real, tal
  como se decidió en la Fase A de este bloque.
- **Bug real encontrado y corregido durante las propias pruebas** (no hipotético): el primer diseño de
  `submit()` intentaba insertar una fila NUEVA con la misma `idempotency_key` al reintentar un trabajo
  ya fallado, violando la restricción de unicidad de la columna — `sqlite3.IntegrityError` real, no
  simulado. Corregido reutilizando la fila existente (reinicio a `QUEUED`, mismo `job_id`), que además
  es la semántica correcta de idempotencia (la misma clave identifica siempre al mismo trabajo lógico).
- 13 pruebas en `tests/test_job_manager.py`, cada una ejercitando una propiedad pedida explícitamente
  en esta ronda (persistencia, idempotencia, concurrencia entre workers, recuperación de lease,
  progreso, reintentos, cancelación cooperativa, estados terminales inmutables).

## 13. Incidente de recuperación de `src/` y `tests/` — verificación completa

Mientras se integraba el Job Manager en `src/mia/api/services.py` (añadir el campo `registry` a
`Services`), un proceso AJENO a esta sesión (evidencia: manifiestos de una migración "V4" de frontend
en `docs/`, con timestamps del mismo día pero sin relación con este trabajo) eliminó por completo los
directorios `src/` y `tests/` del disco. El usuario los restauró manualmente. Verificación realizada
antes de reanudar nada:

1. **`src/mia` íntegro**: 190 archivos `.py`, `python -c "import cada submódulo de mia"` → **0 errores**
   en todo el paquete. Confirmado con grep que cada archivo nuevo de esta sesión (los 8 de
   `src/mia/reporting/` + `src/mia/analytics/homogeneity.py` + `src/mia/data/jobs.py` +
   `src/mia/modules/rrhh/informes/render_html.py` + la migración 0008) está presente y con su
   contenido correcto (verificado por grep de marcadores concretos: los 8 tipos de bloque en
   `document.py`, `RENDERERS["html"]`, `incluir_narrativa` en `tools.py`, `EXPECTED_REVISION = "0008"`).
   El edit interrumpido en `services.py` se completó (campo `registry: ToolRegistry`).
2. **`tests/` restaurado en dos pasos**: (a) `git checkout HEAD -- tests/` trajo de vuelta los ~67
   archivos ya confirmados por git (la suite original de mIA, nunca tocada por este bloque); (b) el
   usuario restauró manualmente, además, los archivos de prueba nuevos de esta sesión (incluida la
   suite de Privacy Gateway de antes de la compactación de contexto) desde su propia copia de
   seguridad — verificados uno a uno contra la lista exacta de archivos que esta sesión recuerda haber
   creado: **los 70 archivos están, ninguno falta**.
3. **Regresión real encontrada y corregida** (no hipotética): dos piezas de la sesión ANTERIOR a la
   compactación de contexto de esta conversación habían vuelto a un estado sin esas ediciones —
   confirmado y corregido con contenido literal (citado en esta misma conversación, no inventado):
   - `tests/conftest.py` había perdido el fixture `autouse` `_clear_payslip_amounts_cache()` (limpia la
     caché en memoria de `_amounts` en `nominas/estadisticas.py` entre pruebas). Reañadido literalmente.
   - `tests/test_query_engine.py` había perdido 3 pruebas de `PeriodEngine` de la Fase B de esta misma
     ronda (cardinales en palabras, "los últimos N años" sin "en", alias "último X"). Reañadidas
     literalmente (el código de producción en `mia/query/period.py` nunca se perdió, solo sus pruebas).
4. **Una discrepancia real, NO reconstruida por falta de contenido verbatim**: `tests/test_privacy_gateway.py`
   tiene 14 pruebas; `PRIVACY_GATEWAY_PROGRESS.md` documentaba 18 (de antes de la compactación). No se
   han inventado 4 pruebas de relleno — en su lugar, se verificó que las 14 actuales cubren el 100% de
   las categorías de garantía documentadas para ese archivo (ver nota ampliada en
   `PRIVACY_GATEWAY_PROGRESS.md`). Documentado como discrepancia de recuento sin impacto funcional
   conocido, no como una pérdida de cobertura oculta.
5. **Suite completa**: tras las dos correcciones reales, **829 pruebas, todas en verde, 0 fallos reales**.
   Por instrucción explícita del usuario, 829 NO se fuerza hacia 836 de forma artificial — 836 era la
   referencia previa al incidente, y la diferencia (7) se explica en su mayor parte por el punto 4
   (discrepancia de recuento documentada, sin hueco de garantía funcional conocido) más un margen de
   imprecisión en el conteo manual de alguna ronda anterior; no indica ninguna regresión real sin
   corregir.

**Nada del desarrollo de esta sesión se perdió de forma irrecuperable**: todo el código de producción
(`src/mia`) y la práctica totalidad de las pruebas estaban recuperables (por git para lo ya comprometido
en commits anteriores, por restauración manual del usuario para lo nuevo de esta sesión) o reconstruibles
literalmente (lo citado dentro de esta misma conversación).
- **Segundo hallazgo real**: añadir la migración 0008 rompió `tests/test_migrations.py::
  test_expected_revision_matches_the_latest_migration` — una prueba de seguridad YA existente que
  comprueba que `mia.data.schema.EXPECTED_REVISION` sea siempre la última migración real (para que mIA
  avise si una base de datos de producción no tiene las migraciones aplicadas). Corregido actualizando
  la constante de "0007" a "0008" — exactamente el tipo de regresión que esa prueba existe para
  detectar, y lo hizo.

Regresión: **836 pruebas, todas en verde** (recuento exacto antes del incidente de recuperación de la
sección 13 — ver esa sección para el recuento validado después: **829**, con la diferencia explicada y
sin hueco de garantía funcional conocido).

Pendiente de Fase G (no completado en esta ronda):
- Integración con `analisis_economico_nominas` para procesamiento masivo (sección 4.1) — el motor de
  trabajos existe, pero todavía no hay ningún tipo de trabajo real que ejecute el análisis económico ni
  la generación de informes a través de él.
- Límites de CPU/memoria reales (solo hay límite de tiempo por lease y límite de filas ya existente en
  `ReportSettings.max_rows`) — límites duros de CPU/memoria necesitan aislamiento a nivel de proceso/
  contenedor (cgroups), no solo código Python puro; esto se documenta como limitación real, no se
  simula.
- Limpieza de archivos temporales de trabajos cancelados/fallidos — no implementada todavía.
- Ningún endpoint de API ni integración de frontend para enviar/consultar/cancelar trabajos (eso es
  Fase H).
- Un bucle de worker real (`while True: claim → ejecutar → ...`) que se ejecute en el proceso de la
  API — hoy solo existen las operaciones individuales (`submit`/`claim_next`/...), no un runner que las
  encadene automáticamente.

## 14. Auditoría previa al commit integral de toda la solución — hallazgos y corrección de recuento

Antes de crear el commit integral solicitado por el usuario (backend + Privacy Gateway + Advanced
Reporting Engine + frontend 2D/3D/HG + recursos V4), se ejecutó una auditoría completa de `git status`,
seguridad y pruebas:

1. **Pérdida de datos detectada y resuelta**: `git status` mostraba 32 archivos 3D legacy eliminados del
   disco (`frontend/public/assets/blender/`, `/meshy/`, `/rigs/*.fbx`), sin archivo de respaldo reversible
   (el script `docs/LIMPIEZA_REVERSIBLE.ps1` esperaba crear `_MIA_ASSETS_FUENTE_ARCHIVO/`, que no existía
   en disco). Consultado el usuario, se confirmó restaurar los 32 archivos desde `git checkout HEAD --` y
   conservar también el nuevo modelo consolidado `frontend/public/models/mIA_SBC_V4_84_ANIMACIONES.glb`
   (39,5 MB, 84 animaciones) en el mismo commit, sin realizar ninguna limpieza adicional de los modelos
   antiguos (esa optimización queda pendiente, como operación independiente y reversible, para después de
   validar la sustitución).
2. **Duplicados obsoletos confirmados y excluidos del commit** (no borrados, solo no incluidos): raíz
   `src/core/`, `src/worlds/` (copias desactualizadas de `frontend/src/core|worlds`, escritas por error de
   ruta por el proceso V4 en una ronda anterior) y raíz `tests/mia-v43-loader.test.mjs` (copia
   desactualizada de `frontend/tests/mia-v43-loader.test.mjs`: la raíz comprueba `voice?.toggle(` —API ya
   sustituida— mientras que la copia correcta en `frontend/tests/` comprueba `voice?.cycle(`, que es la
   API real actual de `frontend/src/worlds/3d/main.js`).
3. **Artefactos transitorios excluidos del commit**: `informes/*.pdf` (13 ficheros, 2,1 MB — salidas de
   generación de informes de pruebas de esta sesión, regenerables, no código fuente) y el nombre de
   archivo corrupto `"C\357\200\272UsersenriqAppDataLocalTemppytest_out.txt"` (redirección de salida de
   pytest con la ruta mal escapada; sin contenido sensible, solo puntos de progreso).
4. **Sin secretos**: búsqueda de patrones de credenciales (api_key, client_secret, tokens, claves
   privadas) sobre todos los ficheros nuevos/modificados — únicamente coincidencias legítimas (nombres de
   campos de configuración en código/documentación, o valores de ejemplo dentro de los propios tests del
   detector de secretos de Privacy Gateway). Ningún secreto real encontrado.
5. **Corrección del recuento de pruebas backend — 817, no 829**: se relanzó la suite completa con
   `--junit-xml` (recuento autoritativo, no afectado por una carrera de buffer con los avisos de
   `PytestUnhandledThreadExceptionWarning` del cierre de hilos de `aiosqlite` que truncaba la línea de
   resumen en texto plano) y por separado con `--collect-only`, sumando el recuento por archivo a mano:
   ambos métodos coinciden exactamente en **817 pruebas recogidas, 817 pasadas, 0 fallos, 0 errores, 0
   omitidas**. El "829" documentado en la sección 13 era en sí mismo un recuento manual impreciso de
   aquella ronda (no una regresión nueva: no se ha tocado ningún archivo de pruebas entre ambos recuentos).
   Por instrucción explícita del usuario de no perseguir un número artificial, se corrige aquí a **817**
   como cifra real y verificada, sustituyendo a 829 como referencia válida para rondas futuras.
6. **Build de frontend verificado**: `npm run build` (vite) compila limpio — 41 módulos, sin errores, solo
   avisos no bloqueantes (config de Vite, atributos `type="module"` en scripts de `mia-2d.html`).
7. **Pruebas de frontend V4 (`node --test`) — 12 de 14 en verde, 2 fallos preexistentes documentados,
   fuera del alcance de esta sesión**: ambos fallos son discrepancias de texto/API entre pruebas y código
   fuente del dominio 3D/V4 (fuera del área de trabajo de esta sesión, que es el backend del Advanced
   Reporting Engine; no se ha modificado ningún archivo de `frontend/src` en esta sesión):
   - `mia-v41.test.mjs` → "Wait milestones are honest and grow over time": el hito de 35s en
     `frontend/src/core/waiting-v4.js` dice "Está tardando **un poquito** más de lo habitual", y la prueba
     exige literalmente `/tardando más/i` (sin "un poquito"). El comportamiento es correcto (mensaje
     honesto, escalona en el momento correcto); solo cambió el tono del texto en una ronda V4 posterior sin
     actualizar la prueba.
   - `mia-v41.test.mjs` → "Data and no-data paths remain distinct in 3D controller": la prueba exige el
     patrón `voice\?\.startIfPreviouslyAllowed`, una API de voz ya sustituida. `frontend/src/worlds/3d/main.js`
     usa ahora `voice?.cycle()` / `voice?.pause()` / `voice?.resume()` (modo apagado → una consulta →
     continuo → apagado), introducida en una ronda V4 posterior a la de este test.
   No se ha corregido ninguno de los dos — por instrucción explícita y reiterada del usuario de no tocar
   3D/HG/Avatar Engine/animaciones en esta sesión. Se documentan aquí para que el proceso V4 (u otra
   sesión con autorización explícita sobre ese dominio) pueda actualizar esas dos aserciones.

## 15. Incidencia: "comparativa de costes en nóminas por departamento" entregaba la plantilla ejecutiva genérica

**Síntoma reportado por el usuario**: la petición «Genera un informe completo de comparativa de costes en
nóminas por departamento en agosto de 2026» producía un PDF de 7 páginas con el título correcto pero
contenido de la plantilla ejecutiva genérica (plantilla, puestos, absentismo, vacaciones), usando además
octubre (el mes en curso) en vez de agosto — sin ningún coste salarial por departamento.

### Causa raíz (confirmada leyendo el código, nunca supuesta)

1. **Herramienta equivocada seleccionada por el LLM**: existen dos rutas para "informe" —
   `analisis_economico_nominas` (motor real de coste salarial por departamento, con periodo y
   k-anonimato ya validados en Fase B/C) y `generar_informe_ejecutivo` (plantilla genérica de
   plantilla/absentismo/vacaciones — **cero** lógica de coste salarial, confirmado por búsqueda
   exhaustiva en `src/mia/modules/rrhh/informes/executive.py`). La descripción de la segunda («informe...
   completo... por departamento... sin consultas previas») competía con la ruta correcta y el LLM eligió
   la equivocada.
2. **Sustitución silenciosa de fecha**: al no recibir `desde`/`hasta` explícitos, `generar_informe_ejecutivo`
   asumía «mes en curso» (octubre) sin avisar — de ahí los datos de octubre en vez de agosto.
3. **Fallo arquitectónico de fondo**: el `ReportPlanner` (Fase B/F, `src/mia/reporting/planner.py`) ya
   existía, validado y con sus propias pruebas, pero **nunca estaba conectado a ningún camino de
   ejecución real** — ninguna herramienta lo importaba fuera de sus propios tests.
4. **Gap de sinonimia real**: el registro semántico (`src/mia/query/fields.py`) no reconocía la frase
   literal de la incidencia («costes en nóminas») como sinónimo de `coste_empresa` — solo variantes como
   «coste salarial»/«costes salariales»/«coste de los salarios». Sin esta sinonimia, ni la validación
   semántica ni la redirección habrían detectado la petición.

### Corrección (mínima, sin reconstruir el motor ni tocar 3D/HG/sincronización)

- **`src/mia/query/fields.py`**: añadidas las sinonimias que faltaban para `coste_empresa` ("coste en
  nominas", "costes en nominas", "coste de nomina", "costes de nomina", "gasto en nominas", "gastos en
  nominas").
- **`src/mia/modules/rrhh/__init__.py`**: `build_registry()` ahora guarda una referencia a sí mismo en
  `deps.services["registry"]` — el único cambio de cableado necesario para que una herramienta pueda
  invocar a otra **a través del registro** (nunca llamando a su handler directamente, para no saltarse
  la comprobación de permisos, el trazado de diagnóstico ni el timeout de `ToolRegistry.execute()`).
- **`src/mia/modules/rrhh/informes/tools.py`**:
  - `generar_informe_ejecutivo` usa el `ReportPlanner` YA EXISTENTE (no se construye otro) sobre
    `ctx.user_message`. Si detecta un campo del dominio `"payroll"` (coste_empresa, líquido,
    devengado...), **redirección real, no un mensaje de error**: ejecuta de verdad
    `analisis_economico_nominas` a través de `deps.services["registry"]` y entrega ESE informe —
    nunca un error técnico ni una mera indicación de qué herramienta usar. El usuario obtiene
    directamente el informe que pidió, sin tener que volver a solicitarlo.
  - **Una sola magnitud económica, nunca mezclada**: `_infer_concepto()` prioriza determinísticamente
    coste_empresa > devengado > líquido según qué campo detectó el planner — nunca pasa más de un
    concepto a `analisis_economico_nominas` en la misma llamada.
  - Interpretación del periodo: si no hay fechas explícitas pero el texto menciona un periodo
    reconocible, se usa ESE periodo (vía el mismo `PeriodEngine` de Fase B) en vez de asumir el mes en
    curso en silencio — corrige también el síntoma de la fecha incluso para peticiones ejecutivas
    legítimas sin vocabulario económico.
  - Lógica de renderizado extraída a `_build_report_result()` (antes duplicada en `generar()`), reutilizada
    por ambos caminos — sin duplicar lógica de negocio.
- **`src/mia/modules/rrhh/nominas/analisis_economico.py`**: descripción de la herramienta reforzada
  ("Esta es la herramienta correcta para cualquier comparativa de costes/nóminas por departamento...")
  para reducir la ambigüedad desde el origen, además de la corrección estructural.

### Verificación de los puntos exigidos explícitamente por el usuario

1. **Redirección automática real** (no solo rechazo): `test_salary_cost_request_through_executive_tool_is_redirected_to_the_real_report`
   (NOT_FOUND honesto con datos insuficientes — nunca la plantilla genérica) y el test de extremo a
   extremo (OK con el informe real, sin que el usuario repita la petición).
2. **`ReportPlanner` no acoplado solo a `generar_informe_ejecutivo`**: `test_report_planner_resolves_domains_beyond_payroll`
   verifica, llamando al planner directamente (sin pasar por ninguna herramienta), que resuelve Nóminas
   (`payroll`), Turnos (`shift`), Vacaciones (`vacation`) y Plantilla (`employee`). La conexión general
   del planner con TODOS los dominios de ejecución queda, como indicó el usuario, para la Fase F — aquí
   solo se verifica que el catálogo semántico subyacente ya generaliza.
3. **Sin recursión, reintentos indefinidos ni llamadas duplicadas**: analíticamente, `_redirect_to_economic_analysis`
   hace una única llamada acotada a `registry.execute()`, sin bucles ni reintentos; `analisis_economico_nominas`
   no vuelve a llamar a `generar_informe_ejecutivo` en ningún punto (no hay ciclo posible). Verificado
   también empíricamente: la traza de diagnóstico del test de extremo a extremo muestra exactamente una
   invocación de cada herramienta (sin duplicados), y la suite completa (824 pruebas) corre en ~285 s,
   el mismo orden de magnitud que antes de esta corrección.
4. **Magnitud económica única y explícita**: verificado leyendo el PDF realmente persistido — contiene
   "Coste empresa" y "Gasto salarial por departamento" (una sola magnitud), y explícitamente NO contiene
   los marcadores de sección exclusivos de la plantilla ejecutiva genérica ("Absentismo ·", "Trabajo
   temporal ·") ni una advertencia de k-anonimato que no procede en este escenario.
5. **Permisos obligatorios en ambas rutas**: la ruta directa ya estaba cubierta (`test_needs_its_own_permission`
   en `tests/test_analisis_economico.py`, preexistente); la ruta indirecta (a través de
   `generar_informe_ejecutivo`) se cubre ahora con `test_payroll_redirect_still_enforces_the_nominas_permission`
   — un usuario con `INFORMES_GENERAR` pero sin `NOMINAS_IMPORTES` recibe `PERMISSION_DENIED` también por
   la vía indirecta, nunca una fuga de datos económicos.
6. **LLM simulado vs. flujo real, documentado explícitamente**: ver la cabecera de
   `tests/test_report_routing_semantic_validation.py` — todos los tests salvo uno llaman a
   `ToolRegistry.execute()` directamente (sin ningún LLM, real ni simulado);
   `test_incident_request_through_the_real_chat_entry_point_delivers_the_real_report` es el único que
   atraviesa `ConversationEngine.run()` (el mismo método que invoca `/api/chat`) con un `FakeLLMProvider`
   que elige PRIMERO la herramienta equivocada — reproduciendo fielmente el incidente real, no solo el
   rechazo ni una llamada directa al generador económico.
7. **Prueba funcional de referencia**: la solicitud exacta "comparativa de costes salariales por
   departamento en agosto de 2026" queda fijada como `INCIDENT_REQUEST` en
   `tests/test_report_routing_semantic_validation.py` — referencia para cualquier cambio futuro al
   routing de informes.

**Resultado de la suite completa tras la corrección**: 824 pruebas (817 + 7 nuevas/actualizadas de esta
incidencia), todas en verde, 0 fallos. Build de frontend no afectado (ningún archivo de `frontend/`
tocado). No se ha modificado Fase G, el Job Manager, ni los mundos 3D/HG/sincronización de datos.

## 16. Fase G — primera integración real: Job Manager + `analisis_economico_nominas`

Construido sobre el motor genérico de la sección 12 (sin tocarlo): worker persistente real, ejecutor
que conecta `analisis_economico_nominas`/`generar_informe` con el Job Manager, y endpoints
autenticados. Archivos nuevos/modificados: `src/mia/settings.py` (`JobsSettings`), `src/mia/main.py`
(arranque/cierre del worker en el `lifespan`, igual que diagnósticos/adjuntos), `src/mia/reporting/worker.py`
(`ReportJobWorker`, genérico por `kind`), `src/mia/modules/rrhh/informes/jobs.py` (el ejecutor concreto
de informes económicos de nóminas), `src/mia/api/routes/jobs.py` (`POST /api/jobs/informe-economico`,
`GET /api/jobs/{id}`, `DELETE /api/jobs/{id}`), `tests/test_job_manager_economic_integration.py` (27
pruebas).

### Verificación punto por punto de lo exigido explícitamente antes de cerrar la fase

1. **Arranque real + recuperación tras reinicio — VERIFICADO**: `test_real_app_startup_processes_jobs_and_recovers_after_a_simulated_restart`
   usa `create_app()` + su `lifespan` real (el mismo procedimiento de despliegue, con
   `MIA_JOBS__ENABLED=true` únicamente en la propia prueba), fuerza un trabajo a `running` con un lease
   de 1 s, lo deja expirar, y arranca una SEGUNDA instancia de la app contra el MISMO fichero de base de
   datos (simulando el proceso caído y reiniciado). El segundo arranque reclama el trabajo huérfano de
   verdad (vía `reap_stale_leases()` al iniciar el worker) y lo lleva a un estado terminal válido.
2. **Varios workers sin duplicados — VERIFICADO**: `test_concurrent_workers_never_execute_the_same_job_twice`
   ejecuta 4 trabajos reales alternando dos instancias de `ReportJobWorker`; los 4 completan con 4
   `report_id` distintos, ninguno compartido. La seguridad de la carrera en `claim_next` (el `UPDATE ...
   WHERE status='queued'` atómico) ya estaba probada con dos procesos reales en
   `tests/test_job_manager.py::test_two_workers_claiming_concurrently_never_get_the_same_job`.
3. **Reevaluación de permisos — VERIFICADO lo verificable; LIMITACIÓN ARQUITECTÓNICA documentada, no
   oculta**: el ejecutor vuelve a comprobar el permiso `NOMINAS_IMPORTES` EN EJECUCIÓN (no solo en el
   envío) contra los roles capturados en `_auth` en el momento del envío —
   `test_payroll_job_still_enforces_the_nominas_permission_at_execution_time` prueba que un trabajo cuyo
   snapshot de roles no incluye ese permiso falla, nunca completa con datos económicos. Lo que NO es
   posible sin añadir infraestructura nueva (fuera del alcance de esta ronda): este proyecto no tiene
   ningún directorio de usuarios al que volver a consultar roles en vivo — los tres `IdentityProvider`
   existentes (`Dev`/`EasyAuth`/`EntraId`) solo autentican a partir de una petición HTTP real, que un
   worker en segundo plano no tiene. Riesgo real y acotado: si a un usuario se le revoca
   `NOMINAS_IMPORTES` en la ventana entre el envío y la ejecución (normalmente segundos; como máximo, la
   profundidad de la cola), el trabajo ya encolado se ejecuta con el permiso que tenía al enviarlo. Un
   usuario que NUNCA tuvo el permiso no puede obtenerlo por esta vía (el envío ya lo exige vía `NominasDep`,
   y la ejecución lo vuelve a exigir de forma independiente).
4. **Idempotencia aislada por usuario — VERIFICADO**: `test_idempotency_is_isolated_per_user_not_shared_by_hash_coincidence`
   prueba que dos usuarios con los mismos parámetros de negocio obtienen claves de idempotencia (y por
   tanto trabajos e informes) distintos — la clave incluye siempre `user_id` (`src/mia/api/routes/jobs.py`).
5. **Sin datos salariales en los mensajes de error/logs — VERIFICADO**: `test_failure_messages_never_contain_salary_amounts`
   fuerza un fallo real (departamento inexistente) y comprueba que el mensaje persistido —el mismo texto
   que viajaría a los logs vía `log.exception`— no contiene ningún patrón de importe. Los mensajes de
   error de `analisis_economico_nominas` son siempre estructurales (periodo no reconocido, departamento
   inexistente, sin datos…), nunca cifras.
6. **Cancelación cooperativa y liberación de recursos — VERIFICADO, con la misma limitación ya
   documentada en el código**: `test_cancellation_requested_before_execution_is_honored_not_silently_run`
   prueba que un trabajo marcado para cancelar antes de ejecutarse nunca llega a correr el análisis
   económico. `test_heartbeat_task_is_cancelled_cleanly_after_execution` prueba que la tarea de
   heartbeat que mantiene vivo el lease durante una ejecución larga se cancela limpiamente al terminar
   (éxito o fallo), sin quedar huérfana. Limitación deliberada, documentada en el propio
   `mia.reporting.worker.ReportJobWorker._heartbeat_loop`: NO se interrumpe un trabajo a mitad de la
   llamada a `analisis_economico_nominas` (una operación atómica del motor analítico ya validado, que
   esta fase no modifica) — la cancelación cooperativa solo se comprueba antes de empezar a ejecutar.
7. **Migración 0008 — RE-VERIFICADA contra una base de datos real** en esta misma ronda (no solo
   recordada de una verificación anterior): `alembic upgrade head` sobre un SQLite nuevo, inspección de
   columnas/FK/índices reales, INSERT/SELECT de una fila real, y `alembic downgrade -1` elimina la tabla
   limpiamente.
8. **Rendimiento y ausencia de truncamiento silencioso — VERIFICADO al volumen practicable en una
   prueba unitaria; el umbral de protección real no se repite por coste de tiempo**:
   `test_large_multi_month_volume_has_no_silent_truncation` resuelve 3 meses × 3 departamentos (hasta 10
   personas) sin perder ningún mes ni departamento, en milisegundos (muy por debajo de
   `TIMEOUT_SECONDS=280`). El mecanismo que protege volúmenes verdaderamente grandes
   (`LARGE_VOLUME_WARNING=1000` en `analisis_economico.py`, y el truncamiento explícito con aviso de
   `annex_block()` en el modelo documental) es anterior a esta fase, ya validado, y esta ronda no lo
   modifica ni lo repite con >1000 nóminas sintéticas por el coste de generarlas en una prueba.
9. **Descarga solo para el propietario — VERIFICADO de extremo a extremo**:
   `test_report_download_is_only_available_to_the_job_owner` encadena un trabajo completado de verdad
   con el endpoint YA EXISTENTE `GET /api/reports/{report_id}` — el propietario descarga (200), otro
   usuario no (404) — sin duplicar esa lógica de propiedad en la nueva capa de endpoints de trabajos.
10. **Activación controlada en pruebas, nunca en producción — VERIFICADO**: `MIA_JOBS__ENABLED` es
    `false` por defecto (`JobsSettings.enabled`, igual que diagnósticos/adjuntos); se activa
    explícitamente solo dentro de `test_real_app_startup_processes_jobs_and_recovers_after_a_simulated_restart`
    (vía `make_settings(..., jobs={"enabled": True, ...})`), nunca en ningún fichero de configuración de
    despliegue ni variable de entorno real de este repositorio.

### Limitaciones reales pendientes (no ocultas, para que ninguna sesión futura las asuma resueltas)

- **Sin límites duros de CPU/memoria**: solo existen el timeout por lease (`lease_seconds`), el límite de
  filas ya existente (`ReportSettings.max_rows`) y el aviso de volumen de `analisis_economico_nominas`
  (`LARGE_VOLUME_WARNING`). Un límite duro real necesita aislamiento a nivel de proceso/contenedor
  (cgroups), no solo código Python — documentado como limitación real desde la sección 12, sin cambios.
- **Revocación de permisos durante la cola**: ver punto 3 arriba — riesgo acotado, no eliminado, sin
  directorio de usuarios al que consultar en vivo.
- **Cancelación no preemptiva**: ver punto 6 arriba — solo se comprueba antes de empezar a ejecutar, no
  interrumpe una llamada ya en curso al motor analítico.
- **Un único worker por proceso** en este incremento (el diseño de `claim_next` ya soporta varios
  procesos/instancias sin cambios si en el futuro hace falta escalar horizontalmente).

**Pendiente para fases futuras (no de esta ronda)**: endpoints de job para otros dominios (turnos,
vacaciones) — el worker y el Job Manager ya son genéricos por `kind`, solo falta registrar su propio
ejecutor cuando se necesite. La conexión general del `ReportPlanner` al pipeline conversacional completo
(selección automática de herramienta por dominio, no solo el guard puntual de la sección 15) queda,
según indicó el usuario, para la Fase F.

**Resultado de la suite completa**: todas las pruebas en verde (834 previas + los tests nuevos de esta
ronda). Ningún archivo de `frontend/` ni del Job Manager genérico (sección 12) modificado. No se ha
tocado sincronización ni caché de negocio.

## 17. Fase F — conexión general del ReportPlanner, niveles de modelo y validación de narrativa vía Privacy Gateway

Tres entregables, reutilizando en los tres casos piezas ya existentes y validadas (ningún motor nuevo):

1. **Conexión general del `ReportPlanner`**: `_report_hint()` (`src/mia/conversation/engine.py`) llama
   al MISMO `ReportPlanner`/`SemanticFieldRegistry` ya existente (no se construye otro) en CADA turno,
   para CUALQUIER dominio del catálogo semántico — nóminas, turnos, vacaciones, plantilla — no solo el
   caso puntual de nóminas ya resuelto en la sección 15. Es una pista no vinculante en el contexto del
   turno (mismo patrón ya usado para el aviso de "Finanzas no disponible"), reforzada con VALIDACIÓN
   REAL EN EL BACKEND (ver punto 1 de la verificación más abajo).
2. **Niveles de modelo configurables** (`ModelTier.FAST/BALANCED/ADVANCED`, `src/mia/settings.py`):
   BALANCED usa `LLMSettings.model` (GPT-4.1 mini, sin cambios respecto a antes de esta fase).
   `LLMRequest` ganó un campo `model: str | None` opcional (`src/mia/llm/base.py`), propagado por
   `OpenAIResponsesProvider.stream()` — nunca un segundo proveedor ni un segundo camino hacia el LLM.
3. **Validación de narrativa vía Privacy Gateway**: `PrivacyGateway.scan_text_for_pii()`
   (`src/mia/privacy_gateway/gateway.py`) reutiliza el mismo motor Presidio ya cargado del gateway;
   `narrative_guard.enforce_narrative_privacy()` bloquea cualquier afirmación narrativa con un dato
   personal detectado que no estuviera YA en el resumen del backend — ver el punto 4 de la verificación
   para la distinción crítica que evita inutilizar informes individuales legítimos.

### Verificación de los 5 puntos exigidos antes de cerrar la fase

1. **El plan no es solo una sugerencia — validación real en el backend**: además del hint no vinculante,
   `generar_informe` ahora RECHAZA la exportación (antes se exportaba sin comprobar nada) cuando la
   petición original resuelve un campo del dominio "payroll" pero la última tabla disponible
   (`LAST_CALL` en el estado de sesión, ya poblado por el motor para cualquier herramienta) no viene de
   `analisis_economico_nominas` —
   `test_generar_informe_rejects_a_payroll_request_exported_from_an_unrelated_tool`. Control negativo
   (`test_generar_informe_still_exports_normally_when_last_call_matches_the_request`) confirma que no
   hay falso positivo cuando sí coincide. **Alcance deliberado**: el bloqueo DURO solo cubre "payroll"
   (el único dominio con un incidente real demostrado — sección 15); turnos/vacaciones/plantilla tienen
   HOY varias herramientas legítimas cada uno (turnos_persona, ausencias, horas_trabajadas…;
   vacaciones, saldo_vacaciones…; plantilla, ficha_empleado, cumpleanos…) sin ningún incidente que
   justifique construir un mapa dominio→herramienta completo arriesgando bloquear exportaciones
   legítimas — para esos tres, la protección real sigue siendo el hint no vinculante más la ausencia de
   un fallo demostrado, documentado aquí como alcance pendiente, no como garantía ya cerrada.
2. **FAST/BALANCED/ADVANCED nunca saltan el Privacy Gateway**: el campo `model` de `LLMRequest` es un
   dato más que `PrivacyGateway._sanitize_request()` reconstruye con `dataclasses.replace()` — no hay
   ninguna rama de código que lo use para evitar la sanitización, sustituir el proveedor o saltarse la
   auditoría. Verificado con los tres niveles reales en
   `test_every_model_tier_still_goes_through_privacy_gateway_sanitization`: un secreto en el mensaje
   sigue redactado para los tres, y el modelo pedido llega intacto al proveedor interno. Modelo por
   defecto: GPT-4.1 mini (BALANCED), sin cambio de proveedor.
3. **Narrative Guard — casos explícitos probados**: importes incorrectos, porcentajes equivocados
   (`test_an_incorrect_amount_is_blocked`, `test_an_incorrect_percentage_is_blocked`) y conclusiones no
   respaldadas (`test_an_unsupported_fact_claim_is_rejected_before_it_ever_reaches_the_guard` — un
   "fact" sin evidencia ni se puede construir, y si el LLM lo devuelve en bruto, `_parse_statements` lo
   descarta). **Limitación real, documentada, no oculta**: "periodos incorrectos" en la PROSA libre NO
   se verifica — `verify_statement` comprueba el VALOR numérico contra el backend, nunca el periodo que
   el texto describe (`test_narrative_guard_does_not_verify_the_free_text_period_described_in_a_statement`
   prueba el hueco explícitamente). No se ha intentado un analizador de fechas en texto libre esta
   ronda: el riesgo de falsos positivos (bloquear comparativas legítimas entre varios periodos) es alto
   y no está validado.
4. **Privacidad contextual — motor real, sin inutilizar informes legítimos**:
   `test_privacy_gateway_scan_text_for_pii_detects_a_real_name_with_the_real_engine` usa el Presidio
   REAL (no un simulador) para confirmar que detecta un nombre real. La distinción crítica pedida — no
   bloquear informes individuales legítimos — se resuelve comparando el dato detectado contra TODOS los
   valores de texto que ya estaban en el resumen que el backend le dio al LLM
   (`known_safe_values` en `enforce_narrative_privacy`): citar el nombre de la persona de una ficha 360
   que el usuario SÍ está autorizado a ver nunca se bloquea
   (`test_generate_narrative_block_does_not_block_the_subject_of_an_individual_report`); un nombre que
   el LLM introduce de la nada, ausente del resumen, sí se bloquea
   (`test_enforce_narrative_privacy_still_blocks_a_name_absent_from_the_backend_summary`). Esto separa
   explícitamente la protección de lo que sale hacia el LLM (este escaneo) de la autorización sobre el
   contenido del documento final (permisos + NOM-004/NOM-005), que siguen aplicándose sin cambios en el
   motor analítico que calculó `backend_summary` antes de que exista ninguna narrativa — no se ha
   tocado ni debilitado ninguna de las dos reglas.
5. **Extremo a extremo por dominio, documentado explícitamente**:
   - **Integrado de verdad (ConversationEngine real → herramienta real → documento real persistido)**:
     Nóminas (sección 15/16, `test_incident_request_through_the_real_chat_entry_point_delivers_the_real_report`,
     con redirección real y permisos verificados); Turnos
     (`test_shift_domain_end_to_end_through_chat_to_a_real_document`, con `ausencias` y datos sembrados
     reales de `tests/hr_seed.py`); Vacaciones
     (`test_vacation_domain_end_to_end_through_chat_to_a_real_document`, con `vacaciones`); Plantilla
     (`test_employee_domain_end_to_end_through_chat_to_a_real_document`, con `plantilla`). Los cuatro
     atraviesan el mismo punto de entrada que usa `/api/chat`, con un LLM simulado, pero NINGÚN otro
     componente simulado (ToolRegistry, base de datos, renderizadores y persistencia reales).
   - **Solo reconocimiento semántico (el hint se calcula y llega al LLM, pero no hay un bloqueo duro
     backend para esos tres dominios — ver punto 1)**: Turnos, Vacaciones y Plantilla en el sentido de
     "impedir una exportación incompatible" — sí están plenamente integrados en el sentido de
     "ejecutar la herramienta real y generar el documento real" (ver arriba).

### Resultado de la suite completa

Todas las pruebas en verde tras corregir una regresión real detectada por esta misma regresión (no
oculta): `deps.settings.llm` asumía que `deps.settings` siempre tiene atributo `llm` si no es `None`,
lo que rompía dos pruebas existentes (`test_reports_narrative_integration.py`) que usan un
`SimpleNamespace` parcial como settings de prueba — corregido con `getattr(deps.settings, "llm", None)`.
Ningún archivo de `frontend/` ni de los mundos 3D/HG/sincronización de datos modificado.

## 18. Fase F — tercera ronda de revisión: autorización explícita, coherencia temporal estructurada y procedencia atada a la ejecución

Tres correcciones reales sobre lo entregado en la sección 17, pedidas antes de cerrar la fase.

### 1. Privacidad contextual: tres autorizaciones separadas, nunca inferidas del resumen

**Qué estaba mal**: `enforce_narrative_privacy` consideraba "autorizado" cualquier dato personal que
apareciera en `backend_summary`, confundiendo "el backend lo calculó" (autorización 2: inclusión en el
documento, ya resuelta por NOM-004/NOM-005 antes de que exista `backend_summary`) con "autorizado a
exponerse al LLM/a la narrativa" (autorización 3, la que de verdad decide esta pieza).

**Corrección**: `generate_narrative_block()`/`enforce_narrative_privacy()` ya NO infieren nada del
resumen. Reciben `authorized_subjects: frozenset[str]` EXPLÍCITO, que debe declarar quien llama —
reutilizando una autorización YA TOMADA por esa herramienta (p. ej. `ficha_empleado` ya comprobó el
permiso para esa persona exacta antes de construir su `profile["nombre"]`). `generar_informe`
(`src/mia/modules/rrhh/informes/tools.py`) extrae ese sujeto de `summary["nombre"]` —el mismo patrón ya
usado por las herramientas de ficha individual— y lo pasa explícitamente; por defecto (sin ese campo)
el conjunto está vacío y NINGÚN nombre propio se considera autorizado (fail-closed). La propia
evidencia que el LLM recibe ahora incluye una instrucción explícita ("este informe es sobre: X" o "no
menciones ningún nombre") para que la narrativa tenga una base legítima para citar al sujeto, no solo
que no se la bloquee después.

**Las tres autorizaciones, explícitas y nunca confundidas** (documentado también en el docstring de
`enforce_narrative_privacy`):
1. Acceso del usuario al dato → `Permission` en el registro de herramientas (sin cambios).
2. Inclusión en el documento final → NOM-004/NOM-005 dentro del motor analítico (sin cambios, resuelto
   antes de que exista `backend_summary`).
3. Exposición al LLM/aparición en la narrativa generada → `authorized_subjects`, explícito, nunca
   inferido (esta corrección).

**Pruebas**: `test_generate_narrative_block_blocks_a_name_in_the_summary_without_explicit_authorization`
(un nombre en el resumen, SIN autorización explícita → bloqueado — antes de esta corrección NO se
bloqueaba, era el propio fallo); `test_generar_informe_authorizes_the_narrative_subject_of_an_individual_report`
(extremo a extremo real, con base de datos y persistencia reales: `generar_informe` extrae y propaga el
sujeto, la narrativa de una ficha individual legítima se publica); los dos tests ya existentes de
autorización/bloqueo se mantienen, ahora exigiendo `authorized_subjects` explícito.

### 2. Narrative Guard: coherencia temporal mediante evidencia estructurada, nunca regex

**Qué se pidió evitar**: un analizador de fechas en la prosa libre (regex), por el riesgo de falsos
positivos en comparativas legítimas entre periodos.

**Corrección**: el esquema de salida estructurada (`NARRATIVE_RESPONSE_SCHEMA`) gana un campo opcional
`period` en la evidencia de cada afirmación `fact` — el LLM debe declarar ESTRUCTURALMENTE a qué
periodo corresponde su cifra, igual que ya declara `metric`/`value`. `verify_statement_period()`/
`enforce_narrative_period_coherence()` (`src/mia/reporting/narrative_guard.py`) comparan ESE campo
estructurado contra el periodo real del informe (`expected_period`, p. ej.
`summary["periodo_interpretado"]`, ya calculado por el motor analítico) — una comparación de cadenas
estructuradas, nunca un análisis de la prosa libre. Si la afirmación no declara periodo, o no hay
`expected_period`, se deja sin marcar — "no verificable" nunca se trata como "incorrecto" (mismo
principio ya aplicado a una métrica desconocida).

**Pruebas pedidas explícitamente ("periodos incorrectos con cifras correctas")**:
`test_an_incorrect_period_with_a_correct_amount_is_blocked_via_structured_evidence` (valor correcto,
periodo estructurado incorrecto → bloqueado), más el extremo a extremo
`test_generate_narrative_block_blocks_a_structurally_wrong_period_end_to_end`. Controles negativos:
periodo correcto no se marca; sin periodo declarado o sin `expected_period`, no se bloquea nada.

**Limitación que permanece, documentada, no un hueco oculto**: si el LLM NO declara el campo
estructurado `period` (aunque la prosa libre mencione un mes distinto), no hay nada que verificar —
deliberadamente no se analiza la prosa con regex. El sistema confía en que el esquema estructurado
obliga a declararlo para cualquier "fact"; si el LLM lo omite, la afirmación queda "no verificada", no
"verificada como correcta" ni "bloqueada".

### 3. Procedencia del análisis económico: atada a la ejecución, no a "la última herramienta llamada"

**Qué estaba mal**: el guard de `generar_informe` comprobaba `LAST_CALL` (la última herramienta
llamada en el turno, para CUALQUIER propósito) en vez de la herramienta que produjo específicamente la
tabla que se iba a exportar. Si el LLM llamaba a `analisis_economico_nominas` (correcto) y DESPUÉS a
una herramienta auxiliar sin presentación propia (p. ej. una consulta de capacidades), `LAST_CALL`
cambiaba pero `LAST_TABLE` seguía siendo la tabla económica correcta — el guard anterior habría
rechazado un informe legítimo por esa causa ajena a sus datos, exactamente el falso positivo señalado.

**Corrección**: `remember_table()` (`src/mia/conversation/tools.py`) gana un parámetro `source_tool`
que se guarda JUNTO a la tabla concreta (`__source_tool__`) — tanto `ConversationEngine.run()` como el
ejecutor de trabajos de Fase G (`src/mia/modules/rrhh/informes/jobs.py`) lo pasan ahora. El guard de
`generar_informe` comprueba `presentation.get("__source_tool__")` (atado al RESULTADO que se va a
exportar), nunca `LAST_CALL`. Además, se añadió una comprobación de periodo: si la tabla SÍ viene de
`analisis_economico_nominas` pero su `periodo_interpretado` no coincide con el periodo que la petición
actual resuelve (p. ej. una tabla de julio que seguía siendo la última de la sesión cuando llega una
petición nueva sobre agosto), también se rechaza — "evitando aceptar resultados de... otro periodo".

**Pruebas**: `test_generar_informe_is_not_fooled_by_an_auxiliary_tool_called_afterward` (reproduce
exactamente el falso positivo descrito y confirma que ya no ocurre);
`test_generar_informe_rejects_a_source_tool_result_from_a_different_period` (periodo distinto, misma
herramienta → rechazado); los dos tests de la sección 17 se actualizaron para usar `__source_tool__`
en vez de `LAST_CALL`. Sobre "otro usuario": no es un riesgo nuevo ni existente aquí — el estado de
sesión (`ctx.session_state`) ya está aislado por sesión/usuario en la capa de conversación, sin
relación con este guard.

### Garantías de Privacy Gateway que permanecen intactas, sin cambios en esta ronda

- El proveedor LLM sigue siendo SIEMPRE el mismo envuelto por `build_llm_provider()` — ninguna de las
  tres correcciones introduce un segundo camino hacia el proveedor.
- La sanitización de la petición saliente (`_sanitize_request`: secretos, inyección, tokenización
  Presidio) se sigue aplicando igual, independientemente del nivel de modelo (sección 17, punto 2, sin
  cambios en esta ronda).
- NOM-004/NOM-005 (minimización económica, k-anonimato) siguen resolviéndose enteramente DENTRO del
  motor analítico, antes de que exista ningún resumen o narrativa — ninguna de las tres correcciones
  los toca ni los debilita.
- El escaneo de PII en la narrativa GENERADA (`scan_text_for_pii`) sigue siendo el mismo motor Presidio
  real del gateway; lo que cambia es únicamente qué se considera "ya autorizado" frente a él
  (corrección 1), nunca el propio mecanismo de detección.

### Pruebas ejecutadas y resultado

`tests/test_fase_f_integration.py` (31), `tests/test_narrative_guard.py` (16) y la suite completa del
proyecto — sin fallos. Ningún archivo de `frontend/`, del Job Manager genérico (sección 12) ni de los
mundos 3D/HG/sincronización de datos modificado en esta ronda.

## 19. Fase H — integración premium del mundo 2D real

### Hallazgo arquitectónico previo (investigación, no se asume nada sin comprobar)

Existen DOS "mundos 2D" en el repositorio, y solo uno es real:
- **El real, servido en producción**: `frontend/mia-2d.html` carga `frontend/src/worlds/2D/mia-2d.js`
  (nótese `2D` en mayúsculas) — un script clásico (sin `type="module"`), ya incluido en
  `vite.config.js` como entrada `world2d`. Llama a `/api/mia/chat` (y `/api/mia/v4/chat`), **no** a
  `/api/chat`. Tiene su propio despachador (`detectResultKind`/`renderData`), su propio Employee360
  (`.e360*`), y es donde viven voz, navegación y todo lo que pide conservar el requisito 8.
- **El huérfano**: `frontend/src/worlds/2d/main.js` (minúsculas) + `index.html` — SÍ usa el contrato
  moderno (`presentations`, `/api/chat`) pero **no está en `vite.config.js`**: no se sirve nunca.
- `/api/mia/chat` (`src/mia/api/routes/compat.py`) NO es "legacy" en el sentido de CLAUDE.md (no es el
  MIA Backend Legacy de solo lectura): es un adaptador activo y mantenido que llama al MISMO
  `ConversationEngine.complete()` que `/api/chat`, y traduce el resultado con
  `mia.api.legacy_view.legacy_view()` al formato que `mia-2d.js` ya entiende.

**Decisión de diseño (satisface el requisito 7, "no crees otra interfaz paralela")**: Fase H trabaja
sobre el mundo 2D REAL (`mia-2d.js`/`mia-2d.css`/`compat.py`/`legacy_view.py`), nunca sobre el huérfano
ni promoviéndolo a entrada real — eso sí habría sido, de facto, una interfaz paralela.

### Causa raíz del hueco (investigación, confirmada leyendo el código)

`legacy_view.py` traduce cada presentación al formato de `mia-2d.js`, pero para `kind=="table"`
(`analisis_economico_nominas`, y cualquier tabla con KPIs/gráficos de primera clase) usaba
`table_view()`, que **solo traduce columnas y filas** — los campos `kpis`/`charts` que la propia
herramienta ya había calculado (ver `mia.modules.rrhh.common.table(..., kpis=.., charts=..)`) se
perdían por completo antes de llegar a la pantalla. Y `summary_view()` solo reconocía la clave
`alertas_calidad` en el resumen de cada herramienta — nunca `advertencias`, que es la clave REAL que usa
`analisis_economico_nominas` para sus avisos de k-anonimato/cobertura — así que esos avisos tampoco
llegaban nunca al 2D.

### Corrección (backend, `src/mia/api/legacy_view.py` — no toca `mia-2d.js` ni ningún archivo 3D/HG)

- `kpis_to_cards()` (nueva): traduce `p["kpis"]` (lista `{label, value, unit?, highlight?}`) al mismo
  formato `data.cards` que `mia-2d.js` YA pinta como `.kpis`/`.kpi` — **sin ningún cambio de frontend**:
  los KPI económicos (coste total, por mes…) ya se muestran como tarjetas en cuanto el backend los
  entrega correctamente.
- `_absorb()` ahora también recoge `p["charts"]` (gráficos de primera clase, ya tipados
  correctamente — donut/bar/line) en un acumulador separado, con prioridad sobre el gráfico derivado
  heurísticamente de la tabla final (`chart_from_table`) o de un resumen (`extra["charts"]`).
- `summary_view()` reconoce ahora también `"advertencias"` (lista de str), igual que ya reconocía
  `"alertas_calidad"` — **sin ningún cambio de frontend**: `renderQuality()` en `mia-2d.js` ya existía y
  ya lee `data.alertas_calidad`; solo faltaba que el backend llenara esa clave con el nombre real que
  usa el motor analítico.

Importante: estos tres cambios viven ÚNICAMENTE en `legacy_view.py`, que por su propio docstring es
"traducción... al formato que pinta el universo 2D anterior" — 3D y holograma consumen `/api/chat` y
`presentations` directamente (confirmado: no pasan por `compat.py`/`legacy_view.py` en ningún punto),
así que esta corrección no los toca ni los afecta, cumpliendo el requisito 9 sin necesidad de evitarlo
activamente.

### Corrección (frontend, `frontend/src/worlds/2D/mia-2d.js` + `mia-2d.css`)

El ÚNICO hueco de renderizado real que quedaba tras la corrección del backend: `data.charts` nunca se
pintaba en ningún punto de `mia-2d.js` (confirmado: cero código de canvas/SVG/gráficos en todo el
archivo antes de esta fase). Se añaden `renderDonutChart`/`renderBarChart`/`renderLineChart`/
`renderCharts()` (donut con `conic-gradient`, igual que el patrón ya usado en
`core/statistical-visuals.js`, pero con la paleta de color del propio `mia-2d.css`
—`--coral`/`--gold`/`--burgundy`— en vez de introducir una paleta nueva; barras con las mismas
proporciones de ancho ya usadas en `renderAnalyticsAgeBands`; línea con un `<svg><polyline>` simple,
sin librería nueva), llamadas desde `renderData()` para cualquier tipo de resultado con gráficos, no
solo "analytics". CSS nueva en la misma convención ya existente (`border/var(--line)`, `border-radius:
20px`, mismo `box-shadow` que `.kpi`/`.viz`/`.insight-panel`).

**No se tocó**: `detectResultKind`, Employee360, el panel de correo, voz (`speak`/`speakProgress`/
`setAvatarState`), ni ningún archivo de `frontend/src/worlds/3d/` o `frontend/src/worlds/hologram/`.

### Requisitos funcionales — qué queda satisfecho y cómo, qué queda pendiente

1. **KPIs/gráficos/tablas/advertencias directamente en el chat**: KPIs y advertencias se arreglaron
   SOLO con el fix de backend (reutilizando renderizado ya existente); gráficos necesitaron la nueva
   función de frontend; tablas completas ya funcionaban (`renderGenericTable`, sin cambios). Comparativas:
   el camino ya existente (`renderComparison`/`data.comparacion`) no se tocó.
2. **PDF/XLSX/PPTX/HTML desde los mismos resultados validados**: YA funciona por el camino conversacional
   existente — el LLM puede llamar a `generar_informe` tras `analisis_economico_nominas` dentro del
   MISMO turno, y el resultado (`{"type":"download",...}`) ya se traduce a un botón real
   (`_absorb()`, rama `kind=="download"`, sin cambios). **No se ha construido** un endpoint REST nuevo
   tipo "exporta el último resultado de esta sesión a formato X" como atajo directo (más rápido que
   repreguntar, pero una pieza nueva independiente) — queda como mejora futura explícita, no como algo
   resuelto en esta ronda.
3. **Job Manager real en la interfaz (progreso/estados/cancelación/historial/descargas), sin
   temporizadores simulados**: **implementado en la segunda ronda de esta fase** (ver "Segunda ronda"
   más abajo) — herramienta conversacional nueva (`informe_economico_en_segundo_plano`), endpoint de
   listado (`GET /api/jobs`) y sondeo/cancelación/historial/descarga reales en `mia-2d.js`/`.html`/`.css`.
4. **Paginación/virtualización sin truncamiento silencioso**: ya satisfecho SIN cambios —
   `renderGenericTable()` ya pintaba (y sigue pintando) TODAS las filas recibidas, con un filtro de
   búsqueda para tablas de más de 8 filas, nunca un `slice()` que recorte el conjunto de datos.
5. **Selección semántica de presentación**: sin cambios — `detectResultKind()` ya distingue
   conversación simple de resultado analítico; la nueva `renderCharts()` se activa únicamente cuando
   `data.charts` no está vacío, nunca para una respuesta conversacional simple.
6. **Advertencias en la interfaz, no solo en el documento**: resuelto con el fix de backend
   (`"advertencias"` → `data.alertas_calidad` → `renderQuality()`, ya existente).
7. **Reutiliza componentes/estilos/contratos existentes**: ver la decisión de diseño arriba — se
   trabajó sobre `mia-2d.js`/`.css`/`compat.py`/`legacy_view.py` reales, nunca el huérfano ni una página
   nueva; la CSS nueva usa las variables de color ya definidas.
8. **Employee360/comparativas/navegación/voz/funcionalidad existente**: ninguna de esas rutas de
   código se modificó; `renderCharts()` es una llamada nueva y aislada dentro de `renderData()`.
9. **Sin tocar 3D/HG/Avatar Engine**: ningún archivo de `frontend/src/worlds/3d/`,
   `frontend/src/worlds/hologram/` ni `Avatar Engine` se modificó. `legacy_view.py` es exclusivo del
   camino 2D (ver más arriba).
10. **Pruebas desde el chat hasta la visualización y la descarga**: ver abajo — cubre desde el chat
    hasta el CONTRATO DE DATOS que consume la pantalla (backend, con pytest real); NO cubre una prueba
    de navegador/DOM real de `mia-2d.js` (limitación honesta: este proyecto no tiene jsdom ni ningún
    arnés de pruebas de navegador para el mundo 2D, y añadir una dependencia nueva solo para esto no se
    ha considerado justificado en esta ronda — se verificó en su lugar que `npm run build` compila sin
    errores de sintaxis).

### Caso de aceptación obligatorio — verificado de extremo a extremo

`tests/test_fase_h_2d_presentation.py::test_cost_comparison_request_reaches_the_2d_screen_with_period_kpis_charts_and_table`:
la petición exacta de la incidencia ("comparativa de costes en nóminas por departamento en agosto de
2026"), a través de `/api/mia/chat` (el endpoint real que usa `mia-2d.js`, con datos sintéticos propios
con cotizaciones SS reales, igual que las pruebas de las secciones 15/16), produce `data.table` con
Cocina/Recepción de agosto, `data.cards` con el KPI de gasto total, `data.charts` con un gráfico donut
real (no derivado) con esas mismas etiquetas, y la presentación RAW (`body.presentations`) también
disponible — nunca el mes equivocado, nunca sin gráficos ni KPIs.

### Pruebas ejecutadas y resultado (primera ronda)

`tests/test_legacy_view.py` (15, 3 nuevas), `tests/test_fase_h_2d_presentation.py` (1, el caso de
aceptación obligatorio), `npm run build` (sin errores). Limitaciones de Fase F recordadas explícitamente
aquí, sin declararlas resueltas por integrar el frontend: el bloqueo semántico duro en `generar_informe`
sigue centrado solo en nóminas (sección 18, punto 1); las afirmaciones narrativas sin campo `period`
estructurado siguen sin verificar, no bloqueadas (sección 18, punto 2); el snapshot de permisos de un
trabajo en cola sigue pudiendo quedar obsoleto durante la espera (sección 16, punto 3) — ninguna de las
tres queda resuelta por el trabajo de esta fase, que es puramente de presentación en el mundo 2D.

### Segunda ronda — Job Manager en el 2D real, completitud de `legacy_view.py` y pruebas ampliadas

El usuario, tras aceptar el avance anterior, pidió explícitamente NO declarar cerrada la Fase H hasta
cubrir cuatro puntos adicionales. Estado de cada uno:

**1. Job Manager real integrado en `mia-2d.html`/`.js`/`.css`** — hecho, reutilizando ÍNTEGRAMENTE el
backend de la Fase G, sin segunda cola ni segundo gestor:
- Backend: `job_manager.list_for_user()` (nueva, `src/mia/reporting/job_manager.py`) — trabajos del
  usuario, más recientes primero, aislados por `user_id` (misma condición `WHERE` que ya usa la
  descarga de informes). `GET /api/jobs` (`src/mia/api/routes/jobs.py`, nueva ruta SIN segmento,
  verificada sin colisión con `GET /api/jobs/{job_id}`) la expone. `JobStatusResponse` ganó
  `kind`/`periodo`/`formato`/`cancel_requested` (antes solo en el objeto interno, nunca en la
  respuesta HTTP).
- Punto de entrada conversacional nuevo: `informe_economico_en_segundo_plano`
  (`src/mia/modules/rrhh/informes/jobs.py`) — llama exactamente a `job_manager.submit()` con el mismo
  `kind` (`JOB_KIND_INFORME_ECONOMICO`) y la misma fórmula de clave de idempotencia que ya usa
  `POST /api/jobs/informe-economico`: son dos puertas de entrada al mismo trabajo, nunca dos
  trabajos distintos para la misma petición. Solo se registra en el `ToolRegistry` cuando
  `settings.jobs.enabled` es `True` (`src/mia/modules/rrhh/nominas/tools.py::register_amounts`) —
  igual que ya exige el arranque del worker — para no ofrecer nunca un botón que un despliegue sin
  worker no podría cumplir.
- Frontend (`frontend/src/worlds/2D/mia-2d.js`/`.css`, `frontend/mia-2d.html`): tarjeta de trabajo
  (`buildJobCard`/`paintJobCard`) con estado, barra de progreso, mensaje y botón de cancelar
  (`DELETE /api/jobs/{job_id}`) o enlace de descarga (`/api/reports/{report_id}`) cuando corresponde.
  Sondeo controlado y real (`pollJobOnce`, cada 2.5 s mientras el estado sea `queued`/`running`, nunca
  un `%` incrementado por temporizador) que actualiza TODAS las tarjetas que representan ese trabajo a
  la vez (la del chat y la del panel de historial, si ambas existen — un único mapa de estado,
  `miaJobsState`, nunca dos fuentes de verdad). Avisos honestos de espera larga (sin inventar un
  fallo: "sigue en cola/en curso" pasados 2/4 minutos de sondeo real) y de error de red al consultar
  (reintento automático, nunca una tarjeta que se queda congelada en silencio).
  Botón nuevo en la barra superior (`#jobsBtn`/`#jobsPanel`) abre un panel de historial que llama a
  `GET /api/jobs` (`refreshJobsHistory()`), reutilizado también en `boot()` para la **recuperación
  tras refrescar la página**: el sondeo de cualquier trabajo no terminal se reanuda solo, sin depender
  de nada guardado en el propio navegador.
- Nada de esto toca Employee360, el panel de correo, voz, ni ningún archivo de `frontend/src/worlds/3d/`
  o `/hologram/`.

**2. Completitud de `legacy_view.py`** — auditado explícitamente bloque por bloque:
- `stats` (estadísticas de primera clase, p. ej. media/mediana por departamento): antes se perdían en
  silencio dentro de `kind=="table"`; ahora llegan como `data.stats` (su propia tabla con
  `table_view()`, nunca mezcladas con la tabla principal). Prueba:
  `test_table_stats_reach_the_screen_as_their_own_named_block`.
- `job` (la tarjeta de trabajo en segundo plano): nueva rama `kind=="job"` → `data.job`. Prueba:
  `test_job_presentation_passes_through_for_the_2d_job_card`.
- `narrativa`/`metodología`/anexos de documento: **sin equivalente a este nivel por diseño, no por
  descuido** — son bloques que solo existen dentro de `to_document()` en el momento de generar el
  archivo (PDF/XLSX/PPTX/HTML), nunca como una `presentation` independiente que viaje por el chat; no
  hay nada que traducir aquí porque el propio motor de documentos nunca produce una `presentation` de
  ese tipo. Documentado explícitamente en el docstring de `legacy_view.py`.
- Cualquier tipo de presentación no reconocido: cae en la rama `else` ya existente de `_absorb()` — un
  comportamiento explícito (se absorbe como tabla/resumen genérico), nunca una pérdida silenciosa sin
  ningún rastro.
- `tests/test_legacy_view.py` pasó de 15 a 17 pruebas (las 2 nuevas de arriba); las 15 anteriores
  siguen pasando sin cambios.

**3. Calidad visual premium** — verificación honesta, distinguiendo lo comprobado por inspección de
código de lo que requeriría un navegador real:
- Verificado por inspección directa del código añadido: ausencia de scroll horizontal (la tarjeta de
  trabajo y el panel de historial usan el mismo patrón de ancho relativo que el resto de tarjetas,
  `max-width`/`calc(100vw - 24px)` en el breakpoint móvil ya existente de 760px); no hay HTML no
  confiable insertado sin escapar — `paintJobCard()` usa `.textContent` para cualquier campo que puede
  venir del backend (`progress_message`, `periodo`, `formato`, `error_message`), nunca
  `.innerHTML` con esos valores; estados de carga y error tienen mensaje explícito propio
  (`.mia-job-note`), nunca un hueco en blanco; el panel de historial tiene su propio estado vacío
  explícito. Responsive: nuevo bloque CSS sigue el mismo vocabulario de variables
  (`--coral`/--gold`/`--line`/`--sand`) y el mismo breakpoint ya usado por el resto del 2D.
- Verificado también para el renderizado de gráficos de la primera ronda (`renderCharts`/
  `renderDonutChart`/`renderBarChart`/`renderLineChart`): usan `.textContent`/`encodeText()`
  consistentemente para cualquier etiqueta de origen backend (`chart.title`, `labels`) — no se
  encontró ningún punto donde un valor del backend se insertara como HTML sin escapar.
- **No verificado en un navegador real** (limitación honesta, ya señalada en la primera ronda): este
  proyecto no tiene jsdom ni ningún arnés de pruebas de navegador para el mundo 2D. No se han podido
  comprobar visualmente en un navegador real: la animación de la barra de progreso, los `tooltips`
  nativos, el comportamiento exacto del panel de historial al abrir/cerrar en pantallas muy pequeñas,
  ni accesibilidad real con lector de pantalla (los `aria-*` añadidos — `aria-haspopup`,
  `aria-expanded`, `aria-hidden` en el panel — son correctos por inspección de las pautas ARIA
  habituales para un menú desplegable, pero no se han probado con un lector de pantalla real). Se
  verificó en su lugar que `node --check` acepta la sintaxis de `mia-2d.js` y que las etiquetas
  `<div>` de `mia-2d.html` quedan balanceadas tras el cambio.

**4. Pruebas reales ampliadas** — los 10 puntos del checklist, verificados con la petición obligatoria
de agosto de 2026, en `tests/test_fase_h_2d_presentation.py` (ahora 7 pruebas, antes 1):
1. Periodo agosto 2026 ✓ (ya cubierto en la primera ronda).
2. Herramienta económica correcta ✓ (idem).
3. KPIs correctos ✓ (idem).
4. Costes salariales reales del escenario sintético ✓ (idem).
5. Gráficos coherentes ✓ (idem).
6. Tabla completa ✓ (idem).
7. **Advertencias de privacidad y cobertura** — nueva:
   `test_hidden_department_privacy_warning_reaches_the_2d_screen`, con un departamento de una sola
   persona (bajo el mínimo NOM-005 de 3): confirma que `data.alertas_calidad` recibe el aviso real y
   que la fila de ese departamento llega enmascarada (`"—"`) en `data.table`, nunca con su importe
   desglosado — el mismo comportamiento que ya protegía el backend, ahora confirmado en el contrato
   que ve el 2D.
8. **Trabajo persistente cuando corresponde** — nueva:
   `test_background_job_request_is_queued_tracked_and_downloadable_from_the_2d_world`: pide el informe
   "en segundo plano" por chat, confirma `data.job` con estado `queued`, lo ejecuta con el mismo
   `ReportJobWorker`/ejecutor ya validado en la Fase G, y confirma que una consulta nueva
   (`GET /api/jobs/{job_id}`, como la que haría el 2D tras refrescar) lo ve `completed`.
9. **Descarga autorizada** — misma prueba: `GET /api/reports/{report_id}` tras completar el trabajo.
10. **Coherencia documento↔pantalla** — misma prueba: el PDF descargado contiene los mismos
    departamentos (Cocina/Recepción) que el periodo solicitado.

Turnos/Vacaciones/Plantilla, con la selección semántica conservada: `test_shift_domain_reaches_the_2d_
screen_as_a_table`, `test_vacation_domain_reaches_the_2d_screen_as_a_table`,
`test_employee_roster_domain_reaches_the_2d_screen_as_a_table` (las tres contra `/api/mia/chat`, el
punto de entrada real del 2D — las de Fase F en `test_fase_f_integration.py` ya cubrían estos tres
dominios contra `/api/chat`; estas son su equivalente para el 2D), y
`test_a_simple_conversational_reply_never_gets_cards_in_the_2d_world` (un saludo simple no produce
`table`/`cards`/`charts`).

### Pruebas ejecutadas y resultado (segunda ronda)

`tests/test_legacy_view.py` (17, 2 nuevas sobre las 15 de la primera ronda) ·
`tests/test_job_manager.py` (15, 2 nuevas: `list_for_user` con aislamiento por usuario y límite) ·
`tests/test_job_manager_economic_integration.py` (22, 5 nuevas: `GET /api/jobs`, no colisión de rutas,
registro condicional de la herramienta conversacional, envío por chat equivalente al REST, permiso
exigido también desde el chat) · `tests/test_fase_h_2d_presentation.py` (7, 6 nuevas) ·
`node --check` sobre `mia-2d.js` (sintaxis correcta) · regresión completa de `tests/` (891 pruebas,
0 fallos tras corregir una prueba de orden sensible al reloj, ver nota abajo).

**Nota de regresión corregida**: `test_list_for_user_returns_only_that_users_jobs_most_recent_first`
falló intermitentemente en la suite completa (no en ejecución aislada) por un empate de `created_at`
entre dos envíos consecutivos — la resolución del reloj de Windows puede ser de ~15 ms, suficiente para
que dos inserciones muy próximas comparen igual. No es un defecto de `list_for_user()` en uso real (dos
envíos de un mismo usuario nunca ocurren con esa cercanía): se corrigió añadiendo un `sleep` real entre
envíos en las dos pruebas afectadas (`tests/test_job_manager.py` y
`tests/test_job_manager_economic_integration.py`), no el propio ordenamiento del backend.

**Limitaciones que siguen abiertas, sin declararlas resueltas por este trabajo** (recordatorio, igual
que en la primera ronda): el bloqueo semántico duro en `generar_informe` sigue centrado solo en nóminas
(sección 18, punto 1); las afirmaciones narrativas sin campo `period` estructurado siguen sin verificar,
no bloqueadas (sección 18, punto 2); el snapshot de permisos de un trabajo en cola sigue pudiendo quedar
obsoleto durante la espera (sección 16, punto 3); un trabajo en segundo plano ya `running` no se
interrumpe a mitad de ejecución al cancelarlo (cooperativo, ver `ReportJobWorker`, sin cambios en esta
fase); y la calidad visual del panel de historial/tarjeta de trabajo en un navegador real (animación,
accesibilidad con lector de pantalla, comportamiento en pantallas muy pequeñas) no se ha podido verificar
sin un arnés de pruebas de navegador, que este proyecto no tiene.

### Tercera ronda — verificación final antes del commit (regresión real, build real, hallazgo de empaquetado)

El usuario aceptó provisionalmente la segunda ronda (23/23 pruebas específicas + build Vite) y pidió una
última verificación antes del commit definitivo. Resultado de cada punto pedido:

**1. Regresión completa del backend (resultado real del XML JUnit, no estimado)**: `tests/` completo,
**898 pruebas, 0 fallos, 0 errores, 0 omitidas** (incluye la prueba nueva de aislamiento en cancelación,
punto 7 más abajo). Se ejecutó una vez, hasta el final, sin relanzar la suite que ya estaba corriendo.

**2. Suite V4 (`node --test`) que ya estaba en ejecución**: **no se ha reiniciado** (instrucción
explícita del usuario). Diagnóstico sin atribuirle un resultado que no tiene: el proceso (PID 27496,
iniciado a las 23:11) seguía vivo a las 05:00 — casi 6 horas después — y su fichero de salida
(`node_tests_full.txt`) no ha crecido ni un byte desde el arranque (975 bytes, sin cambios). Esto no es
el patrón ya conocido de "Node bufferiza stdout y solo lo vuelca al salir" (ese patrón explica silencio
sin escritura NUEVA, no una salida que nunca cambia de tamaño durante horas): es un proceso bloqueado, no
una ejecución lenta. Su resultado queda **indeterminado, no fallido ni pasado** — y, por tratarse del
mundo V4/holograma (archivos `frontend/src/core/*`, `frontend/src/worlds/{2d,3d,hologram}/*`, ninguno
tocado por la Fase H, confirmado con `git diff --stat`), es un hallazgo del mundo V4 que se documenta
aquí por separado, sin tocar 3D/HG para intentar resolverlo.

**3 y 4. Advertencias de Vite sobre `mia-2d.js`/`mia-enhance.js` y comprobación real sirviendo `dist/`**
— esto reveló un hallazgo real, no solo cosmético. La advertencia de `npm run build`:
```
<script src="/src/worlds/2D/mia-2d.js?..."> in "/mia-2d.html" can't be bundled without type="module" attribute
<script src="/src/worlds/2D/mia-enhance.js"> in "/mia-2d.html" can't be bundled without type="module" attribute
```
ya existía antes de la Fase H (`mia-2d.js` ya era un script clásico sin `type="module"` desde antes de
esta fase — confirmado en la investigación arquitectónica de la primera ronda). Lo que NO se había
comprobado hasta ahora es su consecuencia real: `npx vite build` **no copia esos tres archivos
(`mia-2d.js`, `mia-enhance.js`, `mia-2d.css`) a `dist/` en absoluto** — `dist/src/worlds/2D/` no existe
tras el build (verificado listando el árbol de `dist/`). Sirviendo `dist/` con `npm run preview` (el
mecanismo de producción que el propio `package.json` define) y pidiendo esas tres rutas, el servidor
devuelve `200 text/html` — pero es el *fallback* de SPA de Vite (confirmado comparando con una ruta
inventada que no existe en absoluto: devuelve exactamente el mismo `200 text/html`), no el archivo real.
Es decir: **si `dist/` se despliega tal cual mediante `vite preview` (o cualquier servidor estático con
el mismo fallback de SPA), el navegador recibe HTML donde esperaba JavaScript/CSS — los navegadores
modernos bloquean ejecutar `text/html` como script por comprobación de tipo MIME, así que el mundo 2D
completo (chat, avatar, y todo el trabajo de Job Manager de esta fase) no arrancaría en absoluto** bajo
ese despliegue concreto.

Esto es un **hueco preexistente en `vite.config.js`** (nunca copia scripts clásicos no-módulo a
`dist/`), no algo introducido ni corregido por la Fase H — esta fase solo añadió código DENTRO de
`mia-2d.js`, nunca tocó cómo se empaqueta o se sirve. Tampoco hay, en este repositorio, un mecanismo
committeado que sirva `dist/` en producción: el `Dockerfile` solo empaqueta el backend Python (no copia
`frontend/` ni `dist/`), y `docker-compose.yml` solo define los servicios `db` y `api` — ningún servicio
de frontend. Los comentarios de `vite.config.js` ("Los mundos 2D y 3D llaman directamente a
127.0.0.1:5001 y :5002, como antes") sugieren que, en el despliegue real actual, el frontend se sirve
como código FUENTE (no como `dist/` empaquetado) desde algún mecanismo externo a este repositorio — pero
eso no está confirmado aquí, y no se debe asumir sin preguntar. **Pendiente explícito**: confirmar con el
usuario cuál es el mecanismo real que sirve `frontend/` en su entorno de producción actual, para saber si
este hueco de `dist/` es o no relevante para ese despliegue concreto.

Siguiendo la instrucción explícita del usuario ("No cambies automáticamente a `type=module`"), **no se
ha aplicado ningún cambio** de empaquetado ni de servidor en esta ronda — solo se diagnosticó.

**5. Dependencias globales/orden de ejecución si se considerara `type="module"` en el futuro** (solo
diagnóstico, sin cambio): `mia-2d.js` es un script clásico que declara funciones/variables en el ámbito
global de `window` (p. ej. `ask`, `context`, `MIA_UI_BUILD`), y `mia-enhance.js` (que se carga justo
después en `mia-2d.html`) depende de que esas globales ya existan al ejecutarse — convertir cualquiera
de los dos a `type="module"` cambiaría ese orden (los módulos se ejecutan en modo diferido/estricto, con
su propio ámbito, no en el ámbito global) y rompería ese acoplamiento sin refactorizar también
`mia-enhance.js`. Confirma que la decisión de la primera ronda (no convertir a módulos dentro de esta
fase) sigue siendo la correcta — un cambio de este tipo es una decisión arquitectónica aparte, no un
ajuste de empaquetado trivial.

**6. Funciones de Job Manager en la versión compilada**: dado el hallazgo de los puntos 3/4, la
respuesta honesta es que **no se puede confirmar que funcionen en un despliegue de `dist/` aislado**,
porque el propio archivo que las contiene no llega a `dist/`. Sí se confirma que el CÓDIGO en sí es
correcto y sintácticamente válido (`node --check` sobre `frontend/src/worlds/2D/mia-2d.js`, sin errores)
y que usa los endpoints reales (`GET/DELETE /api/jobs/{id}`, `GET /api/jobs`, `GET /api/reports/{id}` —
nunca estado simulado), verificado por inspección directa del código. La confirmación de que SE EJECUTA
correctamente en un navegador depende de qué mecanismo sirva realmente `mia-2d.js` en producción (ver
punto 3/4) — no de este build de Vite en concreto.

**7. Los 23 tests específicos incluyen autorización y aislamiento; nada del 2D validado se ha perdido**:
de las 23 pruebas de `tests/test_job_manager_economic_integration.py`, 8 cubren explícitamente
autorización/aislamiento: `test_submit_endpoint_requires_the_nominas_permission`,
`test_payroll_job_still_enforces_the_nominas_permission_at_execution_time`,
`test_the_conversational_job_tool_still_requires_the_nominas_permission` (autorización); `test_a_user_
cannot_see_another_users_job`, `test_a_user_cannot_cancel_another_users_job` (nueva en esta ronda —
antes solo se comprobaba el aislamiento en consulta/descarga, no en cancelación),
`test_list_endpoint_returns_only_the_callers_jobs_most_recent_first`, `test_report_download_is_only_
available_to_the_job_owner`, `test_idempotency_is_isolated_per_user_not_shared_by_hash_coincidence`
(aislamiento). Ninguna funcionalidad 2D previamente validada se ha perdido: las 7 pruebas de
`tests/test_fase_h_2d_presentation.py` (KPIs/gráficos/tabla/advertencias de nóminas, Turnos, Vacaciones,
Plantilla, selección semántica) siguen pasando, y la regresión completa (898/898) las incluye.

**8. Pruebas visuales en navegador pendientes** (reiterado explícitamente, no resuelto por este trabajo):
animación real de la barra de progreso del trabajo, comportamiento del panel de historial al
abrir/cerrar en pantallas pequeñas, accesibilidad con lector de pantalla, y — hallazgo nuevo de esta
ronda — la propia carga del script en un navegador real contra un despliegue de `dist/` puro, dado el
punto 3/4. Ninguna de estas se ha podido ejecutar en este entorno (sin arnés de pruebas de navegador).

### Pruebas ejecutadas y resultado (tercera ronda)

Regresión completa de `tests/`: **898 pruebas, 0 fallos** (XML JUnit,
`full_regression_final.xml`) — incluye la prueba nueva `test_a_user_cannot_cancel_another_users_job`.
`npm run build`: éxito (`✓ built in 13.70s`), con las dos advertencias ya conocidas (scripts clásicos no
empaquetables) analizadas arriba. Suite V4 (`node --test`): indeterminada, proceso bloqueado desde hace
~6 horas, documentada por separado, sin reiniciarla ni atribuirle un resultado.

## 10. Cierre de Fases D y E (ronda de continuación tras el cierre de la validación de nóminas)

**Fase D — verificado, no reconstruido**: los 8 tipos de bloque que pedía esta ronda (KPI, Table,
Chart, Warnings, Narrative, Methodology, Annex, Section) YA estaban los 8 implementados de la ronda
anterior (`kpis`/`table`/`chart`/`warnings`/`narrative`/`methodology`/`annex`/`section` en
`document.py`) — no se repitió ningún trabajo.

**Fase E — HTML, el formato que faltaba, hecho y probado**: `src/mia/modules/rrhh/informes/render_html.py`
(nuevo). Mismo contrato `Document`/`Block`, sin motor de cálculo ni de gráficos paralelo:
- Gráficos como SVG generado en el propio servidor (sin librería JS ni CDN externo) a partir de la
  MISMA especificación `{type, labels, series}` que ya consumen PDF/XLSX/PPTX
  (`mia.modules.rrhh.charts`) — barras, barras horizontales, donut, línea, área.
- Logotipo SBC incrustado en base64 (nunca una ruta de archivo externa — sección 10: "no depender de
  rutas externas").
- Responsive (`@media (max-width: 600px)`, tabla con scroll horizontal), imprimible
  (`@media print`, `page-break-inside: avoid`), accesible (`lang="es"`, `<th scope="col">`,
  `role="img" aria-label` en los SVG).
- Seguridad: TODO texto que viene de datos pasa por `_esc()` (``html.escape``) antes de insertarse —
  probado explícitamente con una carga `<script>`/`<img onerror=...>` que queda neutralizada, nunca
  ejecutable.
- Integrado en `RENDERERS["html"]`, en el `Literal` de formato de `generar_informe`/
  `generar_informe_ejecutivo`, y en el mapa de `Content-Type` de la ruta de descarga
  (`src/mia/api/routes/reports.py`).
- 8 pruebas en `tests/test_reports_render_html.py` (los 8 tipos de bloque, XSS, accesibilidad,
  responsive, logo embebido) + la prueba de extremo a extremo de nóminas
  (`test_nominas_report_integration.py`) ampliada para incluir también el formato HTML.

## 11. Fase F (integración LLM) — primer tramo: narrativa conectada de verdad

Condición explícita de esta ronda: "Integra realmente `narrative_guard.py`. No dejes este componente
como una librería aislada sin invocación." — cumplida:

- `src/mia/reporting/narrative_generation.py` (nuevo): pide al LLM (vía `deps.llm`, el MISMO proveedor
  ya envuelto por el Privacy Gateway que usa el resto de mIA — nunca un segundo camino) afirmaciones
  narrativas con salida estructurada (`response_schema`, mismo mecanismo que ya usa
  `ConversationEngine`/`persona.py`), las verifica con `narrative_guard.enforce_narrative_integrity()`
  contra el resumen REAL del backend (aplanado con `_flatten_numeric()`, soporta métricas anidadas
  como `por_departamento.Cocina.total`), y solo entonces construye el `Block(kind="narrative")`.
- Resiliente a propósito: respuesta del LLM no interpretable, proveedor ausente, o fallo de red →
  `None`, nunca una excepción que rompa la generación del informe (los números y la tabla ya son
  correctos sin narrativa). Reintento limitado (`MAX_REGENERATION_ATTEMPTS=2`, sección 3.2: "con un
  número limitado de intentos").
- Conectado de verdad: `generar_informe` tiene un nuevo parámetro `incluir_narrativa` (default
  `False` — opt-in, no un coste de LLM oculto en cada exportación de tabla simple). Cuando es `True`,
  genera, verifica y adjunta el bloque ANTES de renderizar, en los cuatro formatos (PDF/XLSX/PPTX/HTML)
  por igual, porque todos consumen el mismo `Document`.
- 8 pruebas en `tests/test_narrative_generation.py` (respuesta correcta, discrepancia bloqueada con la
  cifra real visible, métrica anidada, JSON malformado, reintento, sin proveedor, hecho sin evidencia
  descartado) + 3 pruebas de extremo a extremo reales en
  `tests/test_reports_narrative_integration.py`: un PDF real generado por el tool con una afirmación
  correcta (sin bloqueo), uno con una afirmación incorrecta (bloqueada, cifra real visible en el PDF
  abierto de verdad), y un control que confirma que sin `incluir_narrativa=True` NUNCA se llama al LLM.

Pendiente de Fase F (no completado en esta ronda, para que ninguna sesión futura lo asuma hecho):
- El `ReportPlanner` (Fase B) sigue sin conectarse a un pipeline real de "solicitud natural → plan →
  autorización → consulta" — hoy la narrativa se genera sobre el resultado de una tabla YA existente en
  sesión, no a partir de interpretar una petición nueva de cero.
- Niveles de modelo configurables (FAST/BALANCED/ADVANCED) — no implementados; sigue habiendo un único
  modelo fijo en `LLMSettings`.
- `generar_informe_ejecutivo` todavía no tiene el parámetro `incluir_narrativa` (solo `generar_informe`).

Aprobación del usuario recibida tras la Fase A, con 5 condiciones obligatorias incorporadas al plan
(persistencia/idempotencia del Job Manager, conservar k-anonimato y permisos del catálogo, gráficos
como bloque documental de primera clase, selección de modelo aditiva sobre `mia_privacy_gateway`,
pruebas de integración + evidencia por capacidad). Se continúa de forma autónoma por fases, actualizando
este archivo después de cada una, según lo pedido.

## 1. Auditoría funcional inicial (Fase A) — resultado real, no supuesto

Auditoría de código real (no documental) de los 11 componentes pedidos. Veredicto por componente:

| # | Componente | Veredicto | Evidencia clave |
|---|---|---|---|
| 1 | Herramientas de informes (`mia/modules/rrhh/informes/`) | **FUNCIONA** (alcance limitado) | `Document`/`Block` con solo 3 tipos de bloque (`kpis`, `section`, `table`); gráficos se derivan de `table` en tiempo de render, no son un tipo de bloque propio. `RENDERERS` para pdf/xlsx/pptx ya producen portada (pptx), logo, paleta navy/gold, pie de página con número de página. `generar_informe`/`generar_informe_ejecutivo` funcionan de extremo a extremo, siempre SÍNCRONOS. |
| 2 | Motores estadísticos (`mia/analytics/`) | **FUNCIONA, pero NO conectado a informes** | `stats.py`/`insights.py`/`comparison.py` completos y usados por `analitica/universal.py`, pero `executive.py` (el generador de informes ejecutivos) recalcula todo a mano sin llamarlos. Existen **3 implementaciones de "analítica" en paralelo** con solape parcial: `analytics/` genérico, `modules/rrhh/analitica/` (RRHH), `modules/rrhh/nominas/estadisticas.py` (nóminas, con restricciones de privacidad propias que NO deben tocarse). |
| 3 | Catálogo semántico | **PARCIAL — existe pero huérfano** | `mia/query/fields.py`: `SemanticFieldRegistry` con ~20 campos, sinónimos en español y **permisos por campo** (`permission="NOMINAS_IMPORTES"` etc.) — es más catálogo de lo que se suponía. **Cero usos en producción** fuera de `query/` y su propio test. No tiene metadatos de procedencia/frescura/conteo de filas — eso sí falta de verdad. |
| 4 | Conectores / ejecución de consultas | **FUNCIONA (seguro)** | Cada herramienta de dominio hace su propio `select()` de SQLAlchemy sobre parámetros Pydantic tipados — el LLM nunca ejecuta SQL arbitrario, confirmado por grep (`text(` solo aparece en ingestion/schema, nunca en una ruta alcanzable por el LLM). `mia/query/engine.py` (`UniversalQueryEngine`, DSL de filter/group/pivot/join/rank) está **completo, probado y con cero llamadas en producción** — candidato natural a adoptar en vez de reinventar, pero adoptarlo es trabajo nuevo, no "encender un interruptor". |
| 5 | Selección de modelo LLM | **FALTA** | Un solo modelo fijo (`LLMSettings.model = "gpt-4.1-mini"`) para toda la app; `LLMRequest` no tiene ni campo `model`. No hay ningún mecanismo de niveles (FAST/BALANCED/ADVANCED) hoy. |
| 6 | Job Manager | **FALTA — 100% nuevo, confirmado** | Grep de todo el repo (`JobManager`, `job_id`, `QUEUED`, `celery`, `apscheduler`, `BackgroundTasks`...) sin resultados en Python. `generar_informe` es síncrono dentro de la propia llamada a herramienta. El único "job" existente en el proyecto es la sincronización de datos (`mia/ingestion/sync/__main__.py`), que es un proceso de línea de comandos para Azure Container Apps Jobs — otro dominio, no reutilizable como motor de trabajos de informes. |
| 7 | Frontend 2D | **PARCIAL** | El flujo actual (`generar_informe` → `{"type":"download",...}` → enlace `<a download>` en `mia-2d.js:510`) funciona hoy. Existe además una ruta legacy separada (`downloadGeneratedReport()`, `mia-2d.js:199`) con un ciclo de botón "Generando…/✓ Generado" ligado a un único `fetch` síncrono — no hay sondeo de `job_id`, ni lista de informes anteriores, ni cancelación. |
| 8 | Diagnóstico | **PARCIAL** | `EventStage` ya define `ANALYTICS_START/COMPLETE`, `REPORT_GENERATION`, `COMPARISON`, `FORECAST`, `INSIGHT_GENERATION`, `ANOMALY_DETECTION` — pero **ninguno se emite nunca** en el código actual (grep sin resultados). Son placeholders listos para usar. |
| 9 | Identidad SBC | **FUNCIONA (mínimo)** | Un único logo real en disco (`mia/assets/sunset_beach_club_logo.png`, 41 KB), `resolve_logo()` ya con fallback. Paleta navy/gold y tipografía están **hardcodeadas** en `render.py` (no configurables desde Settings) — suficiente para branding obligatorio, no para "colores/tipografía configurables" de la sección 10. |
| 10 | Módulo predictivo | **FALTA como módulo propio** | Solo existe un stub ABC (`PredictiveModel`) dentro de `analytics/__init__.py`, co-localizado, no en un paquete separado como exige CLAUDE.md. Confirmado ausente; fuera de alcance del Bloque II por instrucción explícita del usuario. |
| 11 | Cobertura de pruebas de informes | Base de regresión | `tests/test_reports_render.py` (9 combinaciones tipo×formato, aserciones superficiales: título en texto, hojas no vacías, ≥2 diapositivas — **nunca prueba con logo real**, nunca prueba gráficos ni branding). `tests/test_reports_route.py` (solo la ruta de descarga). `tests/test_privacy_gateway_reporting_contract.py` (el contrato de seguridad que CUALQUIER cambio en esta área debe preservar: el documento final se renderiza desde `LAST_TABLE`, datos capturados ANTES de que el Privacy Gateway sanee nada hacia el LLM). |

**Hallazgo transversal más importante**: existen ya 4 capas de "consulta/analítica" construidas y
probadas (`analytics/`, `modules/rrhh/analitica/`, `nominas/estadisticas.py`, `query/engine.py`) con
solape parcial y **sin que el usuario haya decidido cuál es la base para el Bloque II**. Construir una
quinta capa nueva violaría la regla 1.18 del encargo ("Toda funcionalidad existente que ya funcione
correctamente debe reutilizarse") y la prohibición explícita de "crear capas redundantes".

## 2. Decisiones arquitectónicas de esta ronda (Fase A → diseño)

Las secciones del encargo ya resuelven la mayoría de las decisiones grandes (no tocar Privacy Gateway,
mantener GPT-4.1 mini, autorizar jobs en segundo plano, logo SBC obligatorio). Las siguientes son
decisiones de ingeniería dentro de ese marco, tomadas aquí con su razonamiento — no reabrir sin motivo:

1. **Base del Analytics Engine (4.4) y del Catálogo Semántico (4.2): extender `mia/analytics/` +
   adoptar `mia/query/fields.py` (catálogo) y `mia/query/engine.py` (DSL), en vez de crear una quinta
   capa.** `analytics/` ya es el motor determinista genérico documentado como "el LLM redacta, los
   valores vienen de aquí" — es exactamente el contrato de la sección 16. `query/fields.py` ya modela
   permisos por campo; se ampliará con metadatos de procedencia/unidad/granularidad que le faltan, no
   se sustituye. `nominas/estadisticas.py` y `modules/rrhh/analitica/` **NO se tocan** (tienen
   restricciones de privacidad propias, p. ej. `MIN_GROUP=3`): el Bloque II los **consume** como
   fuentes de datos ya autorizadas, no los reimplementa.
2. **Document/Block (motor documental universal, sección 9): extender el `Document`/`Block` existente
   de forma aditiva** (nuevos tipos de bloque: `chart`, `comparison`, `narrative`, `methodology`,
   `warning`, `annex`; nuevos campos de metadatos: fuentes, periodo, procedencia), en vez de
   sustituirlo. Los 3 renderizadores actuales seguirán funcionando con los bloques existentes mientras
   se añaden los nuevos — compatibilidad hacia atrás por diseño (contrato innegociable 14).
3. **Job Manager (4.10): nuevo, en proceso, respaldado por una tabla de base de datos — sin Celery,
   Redis ni ningún servicio de pago nuevo.** No existe nada que reutilizar (confirmado). El proyecto no
   tiene hoy ninguna dependencia de cola/broker externa, y la regla 1.9 prohíbe introducir servicios de
   pago adicionales. Diseño: tabla `ReportJob` (estados `QUEUED/RUNNING/VALIDATING/COMPLETED/FAILED/
   CANCELLED`, aislada por `user_id`+`operation_id`) + un runner `asyncio` en el propio proceso de la
   API (igual que ya se hace con `asyncio.to_thread` para renderizar hoy). Si el volumen real exige más
   adelante un worker separado, es una evolución, no un bloqueo para empezar.
4. **Selección de modelo LLM (sección 5): nueva pieza de configuración, aditiva.** Se añade un mapa
   `LLMSettings.model_tiers: dict[str, str]` (`fast`/`balanced`/`advanced` → nombre de modelo) con
   `fast`/`balanced`/`advanced` apuntando todos a `"gpt-4.1-mini"` por defecto (ningún cambio de
   comportamiento hasta que se configure explícitamente otro modelo), y un parámetro `tier` opcional en
   `LLMRequest`/`build_llm_provider()` para que cada llamada declare su nivel. El Privacy Gateway sigue
   envolviendo CUALQUIER instancia resultante — no hay una segunda vía de salida al proveedor.
5. **Frontend (sección 20): extender `mia-2d.js`, no sustituir el flujo de descarga actual.** El enlace
   de descarga directa sigue funcionando para informes síncronos pequeños; se añade un estado de
   progreso ligado a `job_id` para los asíncronos. La ruta legacy (`downloadGeneratedReport()`) se deja
   intacta mientras no se demuestre que rompe algo (regla 6: no eliminar funcionalidad anterior).

## 3. Plan incremental por fases (Fase B en adelante)

| Fase | Contenido | Primer incremento concreto | Depende de |
|---|---|---|---|
| B | Catálogo semántico + planificador | Ampliar `query/fields.py` con metadatos que faltan (procedencia, granularidad, unidad, regla de agregación) para los dominios ya auditados (empleados, nóminas, turnos, vacaciones); `ReportPlanner` que traduce una petición en lenguaje natural a un plan estructurado validable (sin ejecutar nada todavía) | Fase A (hecha) |
| C | Motor analítico | Conectar `executive.py`-style agregaciones a `analytics/` (sustituir cálculo manual por `InsightEngine`/`stats.py` donde aplique, sin cambiar el resultado numérico — regresión obligatoria); añadir comparativas homogéneas (sección 8: comprobación de periodos/denominadores antes de comparar) | B |
| D | Motor documental + branding | Extender `Document`/`Block` (tipos nuevos aditivos); centralizar branding (colores/tipografía) en `ReportSettings` en vez de constantes hardcodeadas en `render.py` | C |
| E | Renderizadores premium | Portada en PDF/XLSX (hoy solo PPTX la tiene), gráficos nuevos (boxplot/heatmap/waterfall/pareto/treemap), paginación de tablas grandes, índice automático en PDF | D |
| F | Integración LLM configurable | `model_tiers`, narrativa con evidencia obligatoria (cada cifra citada debe venir de un resultado ya calculado, nunca inventada por el LLM) | B, C |
| G | Job Manager | Tabla `ReportJob` + runner asyncio + estados + cancelación + aislamiento por usuario | D, E |
| H | Frontend 2D | Estado de progreso por `job_id`, historial de informes, cancelación | G |
| I | Pruebas integrales | Extremo a extremo (sección 25), regresión completa, validación real de archivos (sección 24) | todas |

**Siguiente paso inmediato (ya autorizado a empezar, no requiere más decisiones del usuario): Fase B.**

## 4. Riesgos y superficie de regresión identificados en la auditoría

- **No reabrir `nominas/estadisticas.py` ni `modules/rrhh/analitica/`** al conectar `executive.py` con
  `analytics/`: tienen restricciones de privacidad propias (k-anonimato `MIN_GROUP=3`) que no deben
  diluirse al "unificar" motores analíticos.
- **`tests/test_privacy_gateway_reporting_contract.py` es la regresión más importante de todas**:
  cualquier cambio en cómo se genera un informe (incluido el futuro Job Manager asíncrono) debe seguir
  renderizando desde datos capturados ANTES del paso por el Privacy Gateway, nunca desde texto que haya
  pasado por el LLM.
- **`tests/test_reports_render.py` nunca prueba con logo real** (siempre `logo=None`) ni con gráficos —
  es una base de regresión débil para branding; se ampliará en Fase E, no se asume suficiente hoy.
- **Adoptar `query/engine.py`/`query/fields.py` es trabajo nuevo, no activar código ya probado "gratis"**
  — están probados de forma aislada pero nunca integrados; su primera integración real puede revelar
  supuestos no válidos contra datos de producción.
- Regresión de referencia: **724 pruebas** (Bloque I). Se ejecutará la suite completa tras cada fase
  relevante, sin excepción, por encargo explícito (sección 26).

## 6. Fase B — hecho (primer incremento), con evidencia

1. **Catálogo semántico ampliado** (`src/mia/query/fields.py`): `FieldDef` gana `source` (procedencia
   real, nunca inventada), `granularity` y `min_group`. Los 4 campos de nómina (`liquido`,
   `total_devengado`, `irpf`, `coste_empresa`) llevan `min_group=3`, reflejando (sin importar, para no
   invertir la dirección de dependencia `query→nominas`) el mismo `MIN_GROUP` real de
   `nominas/estadisticas.py` — con una prueba de consistencia que falla si divergen
   (`tests/test_query_fields.py::test_payroll_fields_mirror_the_real_k_anonymity_threshold`). Condición
   obligatoria 2 del usuario: cumplida, verificada, no solo declarada.
2. **`SemanticFieldRegistry.resolve_all()`** (nuevo): encuentra TODOS los campos mencionados en una
   petición, no solo el mejor candidato — necesario para peticiones de informe que combinan varias
   métricas y dimensiones a la vez.
3. **`PeriodEngine` — 2 gaps reales corregidos** (`src/mia/query/period.py`), encontrados al intentar
   resolver los ejemplos LITERALES de la sección 2 del encargo, no hipotéticos:
   - Cardinales en palabras ("los últimos tres años") no se reconocían, solo en dígitos. Corregido con
     `_spell_digits()` + `_relative_years()` (nuevo).
   - "los últimos N días/meses/años" (sin "en" delante) no se reconocía, solo "en los últimos...".
     Corregido ampliando el patrón opcional.
   - "último trimestre/mes/año/semana" (ordinal) no se reconocía, solo "trimestre pasado"/"anterior".
     Añadido como alias.
   - 3 pruebas nuevas en `tests/test_query_engine.py`.
4. **`ReportPlanner`** (nuevo, `src/mia/reporting/planner.py`): traduce una petición en lenguaje
   natural en un `ReportPlan` validado — métricas, dimensiones, periodo (con extracción de la frase de
   periodo incrustada en una oración más larga, ver `_extract_period()`), intención de comparación,
   formato solicitado, y avisos explícitos (permiso denegado, periodo no reconocido, campo
   desconocido). Determinista, sin LLM (esa integración es la Fase F). Al resolverse un campo con
   `min_group`, el plan lo marca con `requires_protected_route=True` para que la ejecución (Fase C)
   sepa que debe delegar en la herramienta de dominio ya auditada, nunca consultar la fuente
   directamente.
   - 8 pruebas de integración en `tests/test_reporting_planner.py`, incluidos 2 ejemplos casi literales
     de la sección 2 del encargo. Durante las pruebas se encontraron y corrigieron 2 sinónimos
     realmente ausentes del catálogo ("costes salariales", "vacaciones" a secas).
5. **Ningún motor analítico nuevo**: se extendió el catálogo y el motor de periodos ya existentes; no
   se tocó `mia/modules/rrhh/nominas/estadisticas.py` ni `mia/modules/rrhh/analitica/`.

Regresión: suite completa en verde tras Fase B, los dos incrementos de Fase C (`InsightEngine` en el
informe ejecutivo + motor de comparativas homogéneas) y el primer incremento de Fase D (gráfico de
primera clase, ver sección 7bis) — **766 pruebas, todas en verde** (recuento exacto de la ejecución
completa más reciente).

## 7. Fase C (motor analítico) — EN CURSO, no completa

Hecho hasta ahora:

- **Cerrada una laguna de pruebas real**: `build_executive_report()` (el generador del informe
  ejecutivo de RRHH) no tenía NINGUNA prueba — confirmado en la auditoría de la Fase A. Se añadió
  `tests/test_executive_report.py` (6 pruebas) como caracterización con datos sintéticos conocidos
  (siembra de `tests/hr_seed.py`), verificada a mano contra esos datos antes de escribirla, cubriendo
  KPIs, desglose por departamento/puesto, absentismo por tipo, tendencia mensual, distribución de
  saldos de vacaciones, y el filtro por departamento. Esta es ahora la base de regresión para cualquier
  cambio futuro en ese generador.

**`InsightEngine` conectado al informe ejecutivo — HECHO y verificado** (no solo diseñado):
`executive.py` genera ahora, de forma aditiva, un bloque `Block("section", "Hallazgos · Absentismo",
...)` a partir de `InsightEngine.from_time_series()` sobre la tendencia mensual de absentismo, pero
SOLO cuando hay suficientes puntos para que el motor detecte algo real (si no, no añade el bloque — sin
afirmaciones sin base). Se amplió la siembra sintética de pruebas a 2 meses (no existía antes, la
siembra estándar de `hr_seed` solo cubre un mes) específicamente para poder verificar el hallazgo con
un valor exacto y comprobado a mano (40,0% de aumento, `tests/test_executive_report.py::
test_executive_report_monthly_trend_includes_a_second_month_with_a_verifiable_finding`). No se tocó
ningún cálculo existente (medias, Counters) — sustituirlos por `stats.descriptive()` no aportaba nada
al no cambiar el resultado, así que no se hizo (ver razonamiento en el commit/sesión).

**Comparativas homogéneas (sección 8) — HECHO y verificado**: `src/mia/analytics/homogeneity.py`
(nuevo) separa, a propósito, "¿se puede comparar?" de "¿cómo se compara?" (esto último sigue siendo
`mia.analytics.comparison`, sin tocar). Tres comprobaciones puras, cada una con su propia prueba real,
no solo declarada:
  - `check_period_pair()`: bloquea comparar un periodo EN CURSO (llega hasta hoy) contra uno ya
    cerrado — el caso literal de la sección 8 ("no comparar periodos parciales como si fueran
    completos"); avisa (sin bloquear) cuando dos periodos cerrados tienen duraciones muy distintas
    (p. ej. una semana contra un trimestre).
  - `check_populations()`: bloquea si uno de los dos grupos no tiene ningún registro.
  - `check_denominator()`: bloquea el cálculo de una variación porcentual sobre un denominador cero o
    desconocido (sección 8: "no calcular variaciones porcentuales sobre denominadores inválidos").
  - 8 pruebas en `tests/test_analytics_homogeneity.py`, con periodos reales resueltos por
    `period_engine` (no fechas inventadas a mano).

Con esto, el incremento de Fase C planteado al cierre de la Fase B está completo: regresión del
informe ejecutivo cerrada, `InsightEngine` conectado de verdad (no solo diseñado), y el motor de
comparativas homogéneas construido y probado.

Pendiente (no completado todavía, para que ninguna sesión futura lo asuma hecho — explícitamente
diferido, no olvidado):

- Un hallazgo equivalente al de absentismo para la distribución por departamento/puesto
  (`InsightEngine.from_distribution()`, p. ej. concentración/outliers) — mismo patrón ya probado, no
  aplicado aún a ese bloque.
- Unificación completa de las 4 capas de analítica/consulta que coexisten (`mia/analytics/`,
  `mia/modules/rrhh/analitica/`, `nominas/estadisticas.py`, `mia/query/engine.py`) — se decidió
  reutilizar en vez de sustituir (sección 2 de este archivo), pero la adopción real de
  `query/engine.py` como ejecutor de consultas del nuevo motor sigue sin hacerse.
- `check_period_pair()`/`check_populations()`/`check_denominator()` todavía no están CONECTADOS a
  ningún punto de ejecución real (no existe aún el "Query Executor" que construya comparaciones de
  verdad) — son primitivas listas para que la Fase F (o un ejecutor de Fase C posterior) las use, no
  una validación que ya se aplique en producción hoy.
- Resto de fases (E-I): sin empezar — ver sección 3 de este archivo para el orden y las dependencias.

## 7bis. Fase D (motor documental universal) — primer incremento HECHO: gráfico de primera clase

**Condición obligatoria 3 de la aprobación de Fase A**: "Los gráficos deben ser bloques documentales
de primera clase, reutilizables en PDF, XLSX, PPTX y HTML, con datos y cálculos procedentes del
backend." — cumplida para PDF/XLSX/PPTX (HTML no existe todavía, ver pendientes).

- `Block.kind` admite ahora `"chart"` (`src/mia/modules/rrhh/informes/document.py`): su `data` es
  exactamente el dict que ya producían `mia.modules.rrhh.charts.chart_spec()` y sus constructores
  (`bar_chart()`, `donut_chart()`, `time_series_chart()`...) — ninguna estructura nueva que aprender,
  se reutiliza lo que YA EXISTÍA y funcionaba bien (hallazgo real de la auditoría de Fase A).
- Cambio mínimo en `render.py`: solo `_rows()` y `_chart_of()` (dos funciones ya compartidas por los
  tres renderizadores) distinguen ahora `kind=="chart"` — ni PDF, ni XLSX, ni PPTX necesitaron ningún
  cambio propio, porque los tres ya pasaban por esas dos funciones para CUALQUIER bloque. Esto es
  justo la ausencia de "capas redundantes" que pedía la condición: un solo punto de extensión, no
  tres.
- Compatibilidad hacia atrás verificada: un bloque `table` de 2 columnas sigue generando su gráfico
  derivado heurísticamente exactamente como antes (`tests/test_reports_render.py`, sin tocar, sigue
  en verde).
- 3 pruebas nuevas en `tests/test_reports_first_class_chart.py`: `_chart_of()` devuelve el spec
  explícito sin recalcularlo; `_rows()` reconstruye una tabla de datos consistente con el gráfico; y
  una prueba de extremo a extremo que renderiza el mismo bloque en PDF, XLSX y PPTX y verifica
  contenido real en cada uno (texto extraído del PDF, celdas de la hoja XLSX, número de diapositivas
  PPTX) — no solo "no lanzó una excepción".
- **Hallazgo útil, sin necesidad de código nuevo**: `ComparisonResult.to_table()`
  (`mia.analytics.comparison`, ya existente) genera exactamente la forma `{"type":"table", "columns",
  "rows"}` que un `Block("table", ...)` ya consume — una comparativa no necesita un `Block.kind`
  nuevo, ya cabe en lo que existe. Dato relevante para cuando se conecte de verdad un ejecutor de
  comparaciones al motor documental.

**Fase D cerrada en esta ronda**: los 4 tipos de bloque que faltaban —`warnings`, `narrative`,
`methodology`, `annex`— están implementados en `document.py` (constructores con validación: una
afirmación `fact` exige evidencia, una advertencia muda se rechaza, un anexo nunca trunca en silencio)
y se visualizan de verdad en los tres renderizadores (no solo se aceptan en el esquema):
- `warnings`: severidad en color (rojo bloqueante / ámbar calidad de datos / teal info) en PDF
  (bloques apilados), PPTX (diapositiva dedicada `_warnings_slide`) y XLSX (columna de severidad
  coloreada).
- `narrative`: cada afirmación etiquetada por tipo (HECHO VERIFICADO/INTERPRETACIÓN/HIPÓTESIS/
  RECOMENDACIÓN) con su evidencia visible cuando la tiene.
- `methodology`: lista de notas, una tabla de una columna en los tres formatos.
- `annex`: aviso explícito "Mostrando X de Y filas" en los tres formatos cuando se trunca — nunca una
  omisión silenciosa.
- Compatibilidad verificada: `ComparisonResult.to_table()` y los contratos de `chart` existentes NO se
  tocaron (condición 9 de la aprobación) — 10 pruebas nuevas en `tests/test_reports_document_blocks.py`
  + 5 en `tests/test_reports_fase_d_blocks.py` (extremo a extremo, abriendo los 3 archivos generados de
  verdad) + 4 pruebas nuevas de homogeneidad (3 niveles de severidad, `check_units`/`check_granularity`).
- **785 pruebas, todas en verde** (recuento exacto).

Pendiente de Fase D (deliberadamente fuera de esta ronda):
- Centralizar branding (colores/tipografía) en `ReportSettings` en vez de las constantes hardcodeadas
  de `render.py` (auditoría de Fase A, hallazgo 9).
- Portada en PDF/XLSX (hoy solo PPTX la tiene) e índice automático en PDF (sección 11).
- `check_period_pair()`/`check_units()`/etc. de `mia.analytics.homogeneity` siguen sin conectarse a
  ningún punto de ejecución real que alimente un `Block(kind="warnings")` de un informe real — ver
  sección 9 (integración con `analisis_economico_nominas`) para el primer caso real de esto.

## 9. Integración con `analisis_economico_nominas` (validación pedida por el usuario + requisitos nuevos)

**Verificación solicitada — confirmada por lectura de código, no reimplementada**: las correcciones que
el usuario preguntó si ya estaban aplicadas SÍ lo están, en esta misma rama, de sesiones anteriores:
- Interpretación de T3/rangos mensuales: `mia/query/period.py` (`_quarter`, `_from_to`, aceptan "T3
  2026", "julio-septiembre 2026", etc. — ampliado esta sesión en Fase B con cardinales en palabras y
  "último trimestre").
- K-anonimato por personas DISTINTAS (no observaciones): `dept_distinct_people` en
  `analisis_economico.py:303-337` (set de `person_key`, no contador de filas).
- Diagnóstico `TEMPORAL_SCOPE_MISMATCH`: `mia/diagnostics/models.py:189` + `analyzer.py:141-171`.
- Cobertura de pruebas real: `tests/test_analisis_economico.py` ya tiene 22 pruebas cubriendo
  exactamente estos escenarios (frases naturales de trimestre, consistencia de totales, k-anonimato no
  reconstruible por resta, escalado a 332/500 empleados, nóminas rectificativas no duplicadas).
No se ha modificado nada de esto — **regla seguida**: "no reconstruir los motores analíticos
existentes."

**Hallazgo real durante la integración documental (no una suposición)**: `to_document()` (Fase D) para
bloques de tipo `"table"` solo leía `presentation["__summary__"]` para derivar gráficos/KPIs — nunca
leía `presentation["charts"]`, `presentation["kpis"]` ni `presentation["stats"]`, que es exactamente
donde `analisis_economico_nominas` (vía el helper `table(..., charts=, kpis=, stats=)` de
`mia/modules/rrhh/common.py:195`) ya adjunta sus gráficos reales (donut/bar/line), sus KPIs (gasto
total, por mes, variación, mayor gasto) y su tabla de estadísticas. **Se estaban descartando en
silencio** al generar un informe — justo el riesgo de "motores paralelos y diferencias entre cifras"
que señala el requisito 3 del usuario. Tampoco existía ninguna vía para que las `advertencias` del
análisis (meses sin datos, periodo incompleto, departamentos ocultos por NOM-005, sustitución de
coste_empresa evitada) llegaran a un informe — vivían solo en `ToolResult.summary`, nunca en la
presentación. Corregido en esta ronda — no se modificó `analisis_economico.py` en absoluto, solo
`document.py` (la capa que faltaba, de la que SÍ es responsabilidad este Bloque II).

### Estado de los 7 requisitos adicionales de esta ronda

| # | Requisito | Estado |
|---|---|---|
| 1 | Job Manager para volúmenes grandes de nóminas | **NO HECHO** — depende de la Fase G (Job Manager), que no existe todavía en ningún formato (ver auditoría de Fase A). No se ha simulado ni prometido como hecho. |
| 2 | Pruebas de inferencia de k-anonimato (totales/departamentos/periodos/filtros cruzados) | **HECHO**, `tests/test_nominas_k_anonymity_inference.py` (6 pruebas, las 6 en verde a la primera): filtrar directamente al grupo oculto sigue ocultándolo; cada mes individual del trimestre lo oculta igual que el agregado; el conjunto de grupos ocultos es idéntico entre `liquido` y `devengado`; dos grupos pequeños simultáneos se ocultan ambos sin fuga cruzada. Ningún cambio en `analisis_economico.py` — la lógica existente ya superaba estos ataques. |
| 3 | PDF/XLSX/PPTX deben usar los mismos resultados validados (sin motores paralelos) | **HECHO** — ver el hallazgo de `to_document()` arriba: ahora los tres formatos consumen exactamente `presentation["charts"/"kpis"/"stats"]`, nunca una re-derivación. |
| 4 | Advertencias de cobertura/sustitución vía bloques `warnings` | **HECHO** — `summary["advertencias"]` (de cualquier herramienta, no solo nóminas) se convierte automáticamente en un `Block(kind="warnings")` visible en los tres formatos. |
| 5 | Trazabilidad persistente y segura de ejecuciones, sin PII innecesaria | **HECHO** — investigado primero: la tabla `reports` (`mia.data.Report`) YA es persistente (BD real) y YA guarda solo metadatos (usuario, título, formato, fechas), nunca el contenido analizado. Lo que faltaba (confirmado en la auditoría de Fase A: `EventStage.REPORT_GENERATION` definido pero nunca emitido) se conectó en `mia/modules/rrhh/informes/tools.py` — ambos generadores (`generar_informe`/`generar_informe_ejecutivo`) emiten ahora ese evento con el `report_id`, enlazando la fila persistida con la traza de diagnóstico del turno. 2 pruebas nuevas en `tests/test_reports_traceability.py`, incluida una que verifica explícitamente que ningún campo persistido contiene contenido analizado (nombres de departamento, etc.). |
| 6 | Prueba de extremo a extremo con una petición real hasta los 3 formatos | **HECHO** — `tests/test_nominas_report_integration.py`, con una petición casi literal del usuario ("julio a septiembre de 2026" / costes salariales por departamento), verificando totales, gráficos, advertencias de k-anonimato, y el logotipo oficial SBC real (`mia.assets.LOGO`) en los tres formatos generados de verdad. |
| 7 | Las conclusiones del LLM deben coincidir con las cifras del backend; bloquear discrepancias | **Primitiva lista y probada, NO conectada todavía** — `mia/reporting/narrative_guard.py` (`verify_statement`/`verify_narrative_block`/`enforce_narrative_integrity`): compara el `evidence.value` de una afirmación `fact` contra `backend_values` real y, si no coincide (con un margen del 1% para redondeo de presentación), sustituye el texto por un aviso de "CONCLUSIÓN BLOQUEADA" con la cifra real visible — nunca "corrige" inventando qué quiso decir el LLM. 8 pruebas en `tests/test_narrative_guard.py`. Sigue sin conectarse a ningún punto de ejecución real porque **la Fase F (integración LLM / narrativa) no se ha empezado** — mismo patrón que `mia.analytics.homogeneity` en la Fase C: la pieza determinista existe y está probada antes de que exista el punto que la necesite, no al revés. |

Regresión tras los 7 requisitos: 803 pruebas. Tras cerrar las Fases D/E (HTML) y el primer tramo de la
Fase F (narrativa + narrative_guard conectados): **823 pruebas, todas en verde** (recuento exacto de
la ejecución completa más reciente).

## 8. Qué NO se ha hecho todavía (para que ninguna sesión futura lo asuma)

- Ningún archivo de los mundos 3D/HG, Avatar Engine, ni Employee360 se ha tocado.
- No existe todavía ningún `ReportJob` (Fase G), ni gráficos como bloque documental de primera clase
  (Fase D/E — condición obligatoria 3, pendiente), ni selección de modelo por operación (Fase F —
  condición obligatoria 4, pendiente).
- `mia/modules/rrhh/informes/`, `mia/analytics/`, `mia/settings.py`, `mia/llm/` y el frontend siguen sin
  modificarse; `mia/query/` y `mia/modules/rrhh/informes/executive.py` son los únicos tocados hasta
  ahora (catálogo/periodos ampliados de forma aditiva; executive.py solo ganó pruebas, su código de
  producción no ha cambiado todavía).
