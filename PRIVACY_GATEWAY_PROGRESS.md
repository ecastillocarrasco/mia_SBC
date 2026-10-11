# mIA Privacy Gateway — seguimiento del proyecto

Este archivo existe para que cualquier sesión futura (de Claude Code o de otra persona) pueda continuar
este trabajo sin repetirlo ni perder las decisiones ya tomadas. Léelo antes de tocar `src/mia/privacy_gateway/`.

## Estado actual: APROBADO PARA DESARROLLO — PENDIENTE DE HOMOLOGACIÓN DE PRODUCCIÓN

El usuario dio la **aprobación condicionada del Bloque I** tras las Etapas 1-5, sujeta a 6 ajustes
finales (ver sección siguiente). Los 6 están hechos y verificados con pruebas reales en esta ronda.
Con esto, el **desarrollo principal del Bloque I queda cerrado** y empieza el Bloque II (Advanced
Intelligence & Reporting Engine). Esto **NO es una autorización de producción**: falta validación en un
entorno de preproducción real (no desplegado en ninguna sesión hasta ahora) y la autorización explícita
del usuario para activar `MIA_PRIVACY_GATEWAY__ENABLED=true` fuera de desarrollo/pruebas.

## Ajustes de la aprobación condicionada — verificados con evidencia, no solo declarados

| # | Ajuste pedido | Qué se hizo | Prueba que lo demuestra |
|---|---|---|---|
| 1 | Reforzar STRICT/AGGREGATED para no enviar importes individuales ligados a persona, sin anonimizar todo indiscriminadamente | `src/mia/privacy_gateway/economic_minimization.py` (nuevo): redacta `importe`/`liquido`/etc. SOLO cuando el mismo registro JSON ya tiene un campo de persona tokenizado, y SOLO bajo STRICT/AGGREGATED. Agregados (medias, totales) nunca se tocan. | `tests/test_privacy_gateway_integration.py::test_nominas_domain_individual_amounts_redacted_under_strict_policy` (nueva) — bajo STRICT, el importe no viaja; `test_nominas_domain_individual_names_and_amounts_are_protected` (existente, política por defecto) sigue pasando sin cambios → confirma que NO es indiscriminado |
| 2 | Medir con pruebas comparativas si la anonimización perjudica la recuperación semántica (antes/con datos sintéticos y consultas con resultado esperado) | Corpus sintético de 4 documentos + 2 juegos de consultas (por tema y por nombre), embeddings deterministas (`FakeLLMProvider.embed`) antes/después de `PrivacyGateway._anonymize_for_embedding` | `tests/test_privacy_gateway_embeddings_retrieval.py` (nuevo, 2 pruebas): precisión@1 por TEMA = 1.0 antes y después (sin degradación); precisión@1 por NOMBRE LITERAL baja tras anonimizar (degradación esperada y documentada, no un defecto — ver "Riesgos residuales") |
| 3 | Ampliar pruebas adversariales de prompt injection sobre herramientas/documentos/correos/BD; tratar la detección de patrones como defensa complementaria, nunca garantía completa | 10 frases conocidas nuevas + 3 evasiones novedosas con falso negativo documentado + prueba de que el envoltorio `wrap_untrusted` protege IGUAL aunque el escáner no detecte nada + prueba de escalada de permiso bloqueada por `ToolRegistry`, no por haber detectado la inyección | `tests/test_privacy_gateway_injection_adversarial.py` (nuevo, 17 pruebas) |
| 4 | Preparar pruebas de integración y contratos de seguridad para correo e informes (las del motor de informes se ejecutan en Bloque II, pero el contrato debe quedar fijado ya) | Correo: identidad del remitente tokenizada en un recorrido real (Graph simulado); confirmación de envío (`_send_blocker`, COR-001) demostrado que SOLO mira `ctx.user_message`, nunca contenido de herramienta. Informes: contrato de que el documento final se renderiza en el backend desde `LAST_TABLE` (datos crudos en memoria), nunca desde lo que vio el LLM — demostrado generando un informe real y abriendo el `.xlsx` | `tests/test_privacy_gateway_mail_integration.py` (nuevo, 3 pruebas); `tests/test_privacy_gateway_reporting_contract.py` (nuevo, 1 prueba) |
| 5 | Mantener fail-closed, documentar rutas multimodales bloqueadas, no activar producción sin validación en preproducción | Los validadores de `Settings._fail_closed_in_production()` y el bloqueo de `read_image()` YA EXISTÍAN, pero ninguna prueba los ejercitaba — se escribieron las pruebas que faltaban | `tests/test_privacy_gateway_production_posture.py` (nuevo, 6 pruebas): rechazo real de `enabled=False`, `fail_open=True` y `vault_key` vacía en producción; bloqueo real de `read_image()` con el gateway activo; control de que sigue funcionando con el gateway desactivado |
| 6 | Documentar en este archivo: aprobado-para-desarrollo, pendiente-de-homologación, riesgos residuales, pruebas hechas/pendientes, dependencias del motor de informes, configuración de activación segura | Este mismo archivo, reescrito en esta ronda | — |

Regresión: las **724 pruebas** de la suite completa (incluidas las nuevas de esta ronda) pasan tras cada
cambio — ver `## Pruebas` más abajo para el desglose exacto por archivo.

## Decisión arquitectónica (confirmada por el usuario, no reabrir)

Capa de privacidad **global, transversal y obligatoria** para todo mIA SBC, no solo para nóminas.
Arquitectura: `Módulos mIA → Orquestador/Herramientas → LLMProvider.stream() → mia.llm.factory →
PrivacyGateway → proveedor real`. El punto de construcción único (`build_llm_provider()`) es la única
forma de obtener un `LLMProvider`: por diseño, **no hay ruta alternativa** para hablar con el proveedor
sin pasar por el gateway. Esto no depende de que cada módulo nuevo "se acuerde" de usarlo.

Jobs en segundo plano para el motor de informes (Bloque II): **sí, autorizados** por el usuario — pendientes
de implementar cuando se llegue a esa fase.

Presidio + modelo español: **sí, autorizado e instalado** (`es_core_news_lg`, ~568 MB).

## Estado por etapas (actualizado tras Etapas 2-5)

| Etapa | Contenido | Estado |
|---|---|---|
| 1 | Localizar llamadas LLM, centralizar, Presidio + fallo seguro | **Hecho** |
| 2 | Reconocedores españoles, políticas, Token Vault, restauración | **Hecho** |
| 3 | Secretos, inspección de respuesta, prompt injection, embeddings, multimodal, fail-safe | **Hecho, incluida la ronda adversarial del ajuste 3 y la medición comparativa del ajuste 2; ver límites reales abajo** |
| 4 | Integración real por dominio + rendimiento | **Hecho para 7 dominios reales** (empleados, turnos, vacaciones, nóminas, correo, informes, control) |
| 5 | Activación controlada en entorno de pruebas | **Hecho en entorno de pruebas**, con fail-closed de producción y bloqueo multimodal ahora cubiertos por pruebas (no en preproducción/producción real: no existe ese entorno desplegado en esta sesión) |

## Auditoría (sección 2 del encargo) — resultado real, no supuesto

- **Único punto de salida al LLM real**: `LLMProvider.stream()` en `src/mia/llm/base.py` (Protocol).
  Única implementación real: `src/mia/llm/openai_responses.py`. Factory: `src/mia/llm/factory.py:build_llm_provider()`.
  Confirmado con `grep` que nada instancia `OpenAIResponsesProvider` directamente fuera de la factory.
- **Hay un árbol paralelo muerto**: `src/llm/`, `src/api/`, `src/sources/`, `src/sync/`, `src/settings.py`
  (sin `mia/` en la ruta) son restos de "Fase 1" (ver `git log`). `pyproject.toml` solo empaqueta
  `src/mia`. No se tocan, no son una ruta de bypass real porque nunca se despliegan.
- **Ya existe seudonimización** en `src/mia/ingestion/pseudonym.py` (HMAC-SHA256 del DNI/NIE →
  `person_key`, irreversible) — distinta de la tokenización reversible de este gateway; no se duplican.
- **`cryptography>=43` ya era dependencia** — el Token Vault (Fernet) no añadió un paquete nuevo.
- **Control de herramientas (sección 4.2) ya existe y se verificó, no se reconstruyó**:
  `ToolRegistry._run()` (`src/mia/conversation/tools.py:230-233`) comprueba `ctx.user.has(tool.permission)`
  ANTES de ejecutar cualquier herramienta, y valida los argumentos con `tool.params.model_validate_json()`
  (Pydantic) antes de que el handler los vea — allowlist de permisos + validación de argumentos
  deterministas, ya cubiertas por decenas de pruebas de regresión existentes.
- **Rutas no protegidas, documentadas como tales, no ocultas**:
  - `LLMProvider.read_image()` — **bloqueado explícitamente** (`UnsafeContentBlockedError`) mientras el
    gateway esté activo: no hay protección real de píxeles. Apaga la lectura Vision de imágenes en
    adjuntos mientras `enabled=true`.
  - Correo y generación de informes: la arquitectura los protege igual (pasan por el mismo
    `LLMProvider.stream()`), y ahora SÍ tienen prueba de integración real (ver `## Pruebas`) — correo
    con Microsoft Graph simulado, informes con generación y lectura real del `.xlsx` resultante.

## Qué se construyó (`src/mia/privacy_gateway/`)

```
__init__.py              — fachada pública + resumen de estado
exceptions.py             — PrivacyGatewayError, UnsafeContentBlockedError, RestorationDeniedError
custom_recognizers.py     — DNI/NIE (checksum letra), IBAN español (mod-97), SS (checksum), con
                            validadores reales. Verificados con vectores de prueba oficiales.
presidio_engine.py        — AnalyzerEngine + AnonymizerEngine, carga perezosa, singleton por proceso.
                            drop_overlapping(): bug real encontrado y corregido — Presidio devuelve a
                            veces DOS entidades de TIPOS distintos (su ES_NIF nativo y nuestro
                            ES_DNI_NIE propio) sobre el MISMO tramo de texto; sin deduplicar por
                            solapamiento antes de sustituir, el texto queda corrupto.
policy_engine.py          — Policy (strict/standard/aggregated/public). Las 4 comparten la MISMA red
                            de seguridad base (toda entidad personal se tokeniza siempre, incluyendo
                            ES_NIF/ES_NIE nativos de Presidio además de los propios — doble cobertura
                            deliberada); strict añade fechas/NRP y baja el umbral de detección.
token_vault.py            — Correspondencia token↔valor cifrada (Fernet), en memoria del proceso, TTL,
                            aislada por (user_id, operation_id).
tokenizer.py               — Sustituye entidades por [TIPO_NNN]; mismo valor → mismo token dentro de una
                            operación. Limpieza por antigüedad (NO al final de cada stream(): una
                            operación implica varias rondas de herramientas, y un token de la ronda 1
                            debe restaurarse en la ronda 3 — purgar tras cada stream() rompía esto; se
                            corrigió durante esta sesión).
outbound_inspector.py     — Detección/redacción de secretos (claves, JWT, connection strings). Irreversible.
inbound_inspector.py      — Mismo filtro de secretos aplicado a la respuesta del LLM.
prompt_injection_guard.py — scan() detecta frases de inyección típicas (es/en) para auditoría;
                            wrap_untrusted() delimita el contenido de herramientas (role="tool") como
                            DATOS, nunca instrucciones, antes de entrar en el prompt.
context_manager.py        — ContextVar propio (independiente de mia.diagnostics) con (user_id,
                            operation_id); lo fija ConversationEngine.run() con un `set` simple (no un
                            gestor de contexto: evita el bug ya corregido en mia.diagnostics.trace de
                            resets de ContextVar en un contexto asyncio distinto al que los creó).
audit.py                  — Eventos vía mia.diagnostics (reutilizado): PRIVACY_GATEWAY_INSPECT/
                            BLOCKED/RESTORED, incluyendo recuento de posible prompt injection.
gateway.py                — PrivacyGateway(LLMProvider): la pieza central.
                            - stream(): sanea outbound (secretos + tokenización + envoltura de
                              contenido no confiable), restaura inbound con buffer para tokens
                              partidos entre fragmentos de streaming.
                            - embed(): anonimización de UN SOLO SENTIDO (no reversible, no usa el
                              Token Vault — un vector de embedding nunca necesita restaurarse).
                            - read_image(): bloqueado explícitamente si enabled=true.
                            - Fallo seguro: CUALQUIER excepción al sanear bloquea la llamada externa
                              (no solo UnsafeContentBlockedError) salvo fail_open=True, prohibido en
                              producción por el validador de Settings.
```

## Pruebas (8 archivos específicos del gateway, 53 pruebas; 724 en toda la suite)

- `tests/test_privacy_gateway.py` (**14 pruebas** — ver nota de incidente de recuperación más abajo;
  esta sección decía "18" antes del incidente): checksums, intercepción real de lo que "saldría" hacia
  el proveedor, restauración dentro de la misma operación, DENEGACIÓN de restauración entre
  operaciones/usuarios distintos, token partido entre fragmentos de streaming, fallo seguro cuando
  Presidio falla, paso directo si `enabled=False`, envoltura de contenido no confiable (`role="tool"`),
  detección de prompt injection, **latencia medida** (no estimada).

### Incidente de recuperación (post-sesión, antes de continuar con el Bloque II)

Un proceso externo a este trabajo (no esta sesión) eliminó accidentalmente los directorios `src/` y
`tests/` completos del disco. El usuario los restauró manualmente. Verificación tras la recuperación:
- `src/mia` íntegro: 190 archivos, **0 errores de import** en todo el paquete.
- `tests/`: 70 archivos .py, incluidos TODOS los archivos nuevos de esta sesión (verificados uno a uno).
- Comparación exhaustiva de cada recuento de pruebas documentado explícitamente en este archivo contra
  el recuento real tras la recuperación: TODOS coinciden exactamente (`test_privacy_gateway_integration.py`
  6/6, `test_privacy_gateway_embeddings_retrieval.py` 2/2, `test_privacy_gateway_injection_adversarial.py`
  17/17, `test_privacy_gateway_mail_integration.py` 3/3, `test_privacy_gateway_production_posture.py`
  6/6) **excepto `test_privacy_gateway.py` (14 reales frente a 18 documentadas)**.
- Esas 4 pruebas no se han podido reconstruir de forma literal: se escribieron ANTES del resumen de
  compactación de esta sesión, así que no hay contenido verbatim al que recurrir (a diferencia de
  `tests/test_query_engine.py` y el fixture `autouse` de `tests/conftest.py`, que SÍ se reconstruyeron
  literalmente porque su contenido seguía citado en este mismo archivo/sesión — ver sección de Fase G
  de `ADVANCED_REPORTING_PROGRESS.md`).
- **No se han inventado 4 pruebas de relleno** para alcanzar "18": se ha verificado en su lugar, categoría
  por categoría, que las 14 pruebas actuales cubren el 100% de las garantías descritas arriba (checksums,
  intercepción real, restauración, denegación entre operaciones, token partido, fallo seguro, paso
  directo, envoltura, detección de inyección, latencia) — ninguna garantía funcional documentada carece
  de prueba hoy; solo el recuento exacto de variantes dentro de esas categorías es menor que antes.
- `tests/test_privacy_gateway_integration.py` (6 pruebas): recorrido COMPLETO con `ConversationEngine`
  real + `ToolRegistry` real + BD sembrada con datos sintéticos — no solo el gateway en aislado:
  - Empleados (`buscar_empleado`)
  - Turnos (`turnos_dia`, nombre viene de `ShiftDay` en BD)
  - Vacaciones (`saldo_vacaciones`, dos nombres + saldo)
  - **Nóminas** (`ranking_salarial`, Escenario B de la sección 30: nombre e importe INDIVIDUALES de 3
    personas — el caso más sensible), bajo política por defecto
  - **Nóminas bajo STRICT** (ajuste 1): el importe individual, ya desligado del nombre, tampoco viaja
  - Control: gateway desactivado deja pasar todo en claro (confirma que la protección es la variable,
    no la funcionalidad)
- `tests/test_privacy_gateway_embeddings_retrieval.py` (2 pruebas, ajuste 2): precisión@1 por tema
  (1.0 antes y después de anonimizar) vs. precisión@1 por nombre literal (degrada tras anonimizar, a
  propósito).
- `tests/test_privacy_gateway_injection_adversarial.py` (17 pruebas, ajuste 3): 10 frases conocidas
  detectadas, 3 evasiones con falso negativo documentado, envoltura estructural pese a detección
  fallida, inyección en contenido tipo documento/correo, y escalada de permiso bloqueada por
  `ToolRegistry` aunque el "modelo" decida obedecer una instrucción inyectada desde un campo real de
  base de datos.
- `tests/test_privacy_gateway_mail_integration.py` (3 pruebas, ajuste 4): identidad del remitente
  tokenizada en un recorrido real sobre Microsoft Graph simulado; una frase de confirmación de envío
  inyectada en el CUERPO de un correo nunca se consulta como consentimiento real (control positivo
  incluido).
- `tests/test_privacy_gateway_reporting_contract.py` (1 prueba, ajuste 4): genera un informe `.xlsx`
  real a partir de un ranking salarial con PII, confirma que el LLM solo vio pseudo-tokens, y abre el
  archivo generado para comprobar que SÍ contiene el nombre e importe reales.
- `tests/test_privacy_gateway_production_posture.py` (6 pruebas, ajuste 5): rechazo real en producción
  de `enabled=False`, `fail_open=True` y `vault_key` vacía; bloqueo real de `read_image()` con el
  gateway activo; paso directo de imagen con el gateway desactivado (control).

Todas interceptan `FakeLLMProvider.requests` (lo que de verdad habría recibido el proveedor), no solo
el analizador Presidio aislado — tal como exige la sección 11.4/30 del encargo.

## Rendimiento — medido de verdad, no estimado

```
Primera llamada del proceso (carga del modelo es_core_news_lg + análisis): ~3.2 s  — UNA vez por proceso
Llamadas siguientes (modelo ya cargado), frase corta realista:            ~12.6 ms/llamada
Texto ~20x más largo (≈1840 caracteres):                                  ~172 ms
```
El modelo se carga una sola vez por proceso (singleton con doble comprobación y cerrojo en
`presidio_engine.py`), nunca por petición. No se hizo prueba de carga/concurrencia con tráfico
simultáneo real — pendiente si se quiere una cifra bajo concurrencia, no solo secuencial.

## Bug real encontrado y corregido en esta ronda (Etapas 2-5)

**Solapamiento de entidades de Presidio**: al añadir `ES_NIF`/`ES_NIE` (reconocedores NATIVOS de
Presidio, con su propio checksum) a la red de seguridad además de los propios `ES_DNI_NIE`/`ES_IBAN`,
un DNI podía ser detectado DOS VECES (una por cada reconocedor) sobre el mismo tramo de texto.
Sustituir ambas entidades por separado, sin deduplicar, corrompía la cadena de salida (ej.:
`"[ES_NIF_001]IE_001]"` en vez de un token limpio). Corregido con `drop_overlapping()` en
`presidio_engine.py`: se queda una sola entidad por tramo solapado (la de mayor puntuación). Las
pruebas correspondientes se adaptaron para no depender de CUÁL de los dos reconocedores "gana" el
empate (ambos protegen igual) — ver `test_gateway_tokenizes_dni_before_it_would_reach_the_provider` y
`test_split_token_across_stream_chunks_is_still_restored`.

**Import circular real**: `mia.llm.factory` importaba `PrivacyGateway` a nivel de módulo; `gateway.py`
importa tipos de `mia.llm.base`, y cargar `mia.llm.base` dispara `mia/llm/__init__.py`, que a su vez
importa `factory.py` — ciclo real si algo importaba `mia.privacy_gateway` antes que `mia.llm`.
Corregido con un import perezoso (dentro de la función, no al nivel de módulo) en `factory.py`.
Verificado con los tres órdenes de import posibles.

**Falso negativo de NER por nombre de prueba poco realista**: una prueba usaba nombres como "Cocinero
López" (mezclando el puesto dentro del campo nombre); spaCy fallaba en detectar ESE nombre concreto
(aunque sí los otros dos) por la repetición confusa de "Cocinero" cerca en el mismo JSON. Verificado
que con nombres propios reales (p. ej. "Carlos López") los tres se detectan sin problema — era un
defecto del dato de prueba, no del motor. Documentado aquí porque es un ejemplo real de cómo el NER
puede tener falsos negativos dependientes del contexto (ver "Riesgos residuales" abajo).

## Auditoría del entorno `.venv` (a petición del usuario, tras instalar Presidio)

- `pip check`: limpio, sin dependencias rotas.
- NumPy 2.4.6, Cryptography 48.0.1, spaCy 3.8.16, Presidio analyzer/anonymizer 2.2.364, `es_core_news_lg`
  3.8.0 — todos resueltos dentro del `.venv` del proyecto.
- Python 3.12.10 confirmado como el intérprete usado por mIA.
- Restos de instalación incompleta encontrados: `~ryptography`, `~umpy`, `~umpy.libs` en
  `site-packages` (~34 MB), carpetas "papelera" que pip no pudo borrar del todo al actualizar
  NumPy/Cryptography por versiones anteriores. Inertes (ningún módulo empieza por `~`, nada los
  importa; `pip check` y la suite completa pasan igual). **No se han borrado**: sus binarios están
  bloqueados por un proceso en marcha (probablemente la extensión Python/Pylance de VS Code) y el
  usuario pidió explícitamente no tocar el entorno mientras VS Code esté trabajando. Pendiente: si se
  quiere liberar ese espacio, cerrar VS Code (o reiniciar Pylance) y borrar esas tres carpetas a mano.
- Rutas `mIA`/`mia`: inconsistencia de mayúsculas real pero inofensiva (Windows no distingue
  mayúsculas en rutas de archivo); no es un bug de Python/pip, es solo cómo cada herramienta imprime
  la ruta. Mismo fenómeno ya visto con `frontend/src/worlds/2D` vs `2d` en git.

## Riesgos residuales — sin inventar porcentajes, sin declarar seguridad absoluta

- **Falsos negativos de NER son posibles y reales** (demostrado en esta misma sesión, ver arriba): un
  nombre en un contexto suficientemente ambiguo puede no detectarse. La red de seguridad combina NER
  (nombres) con reconocedores deterministas (DNI/NIE/IBAN/SS con checksum) precisamente porque el NER
  solo no es suficiente — pero el NER es la única defensa para nombres propios sueltos, y no es 100%.
- **El importe desacoplado del nombre sigue viajando en claro bajo la política por defecto**
  (ver `test_nominas_domain_individual_names_and_amounts_are_protected`): una vez que el NOMBRE se
  sustituye por un token, el número (p. ej. 1700.0) ya no es atribuible a esa persona fuera del backend
  — pero la cifra en sí no se cifra ni se oculta bajo STANDARD. **Ajuste 1 (esta ronda)**: bajo
  STRICT/AGGREGATED, `economic_minimization.py` ya redacta también el importe cuando queda ligado a una
  persona ya identificada en el mismo registro — ver `test_nominas_domain_individual_amounts_redacted_under_strict_policy`.
  Sigue siendo pseudonimización del identificador, no cifrado homomórfico de la cifra, y sigue siendo
  responsabilidad de cada dominio elegir STRICT/AGGREGATED cuando el caso lo exija.
- **Embeddings de CVs/documentos**: medido esta ronda con un corpus sintético y consultas con resultado
  esperado (ajuste 2) — recuperación por TEMA sin degradación (precisión@1 = 1.0 antes y después);
  recuperación buscando el NOMBRE LITERAL de una persona SÍ degrada tras anonimizar, a propósito. No se
  propone mitigación técnica sobre el embedding porque no hace falta: la localización de una persona
  concreta en mIA ya se resuelve con búsqueda estructurada por clave (`name_key`/`person_key`, p. ej.
  `buscar_empleado`), nunca con recuperación semántica por vector.
- **Prompt injection**: la guardia sigue siendo determinista pero básica (patrones + delimitación de
  contenido no confiable). Esta ronda (ajuste 3) demostró, con pruebas reales y no solo con la
  afirmación, que el escáner de patrones TIENE falsos negativos genuinos frente a formulaciones nuevas
  u ofuscadas (`test_pattern_scan_has_known_false_negatives`), incluso para una frase "clásica"
  incrustada de forma natural en un campo de texto libre de base de datos. Lo que de verdad sostiene la
  seguridad no es la detección: es que ninguna política, permiso o selección de herramienta se decide a
  partir de texto del LLM (todo pasa por `ToolRegistry` y `policy_engine`, código determinista) — y esa
  afirmación ya tiene su propia prueba de escalada de permiso bloqueada
  (`test_injected_instruction_in_db_sourced_content_cannot_escalate_tool_permission`), detectada la
  inyección o no.
- **Único "bypass" conocido, y es solo de pruebas**: `tests/conftest.py`'s `services` fixture inyecta un
  `FakeLLMProvider` directamente a `Services.build(llm=...)`, evitando `build_llm_provider()` y por
  tanto el envoltorio del gateway. Es deliberado (permite a los tests leer `services.llm.last_prompt`
  directamente) y NUNCA alcanzable en producción (ahí no existe ese parámetro de inyección) — pero se
  documenta aquí para que quede explícito, no oculto.
- **No hay rotación de claves del Token Vault**, ni métricas agregadas expuestas en el panel
  administrativo (solo eventos individuales de diagnóstico), ni autorización granular de restauración
  más allá de usuario+operación (secciones 6.2/6.3 parcialmente cubiertas, no al 100%).
- **No hay entorno de preproducción real desplegado** en esta sesión: "activación controlada" significa
  aquí "activado y probado de extremo a extremo en un entorno de pruebas con datos sintéticos", no un
  despliegue real verificado en un servidor de preproducción.

## Decisión deliberada: `enabled=False` por defecto en la clase, pero obligatorio en producción

El gateway envuelve SIEMPRE (no hay bypass arquitectónico). El *default* del campo
`PrivacyGatewaySettings.enabled` sigue siendo `False` para no sorprender a quien use la clase fuera de
producción (tests, scripts locales) — pero `Settings._fail_closed_in_production()` ya exige
`enabled=True`, `fail_open=False` y una `vault_key` no vacía cuando `environment=production`, así que en
un despliegue real no hay forma de que quede desactivado por descuido. Verificado con pruebas reales
esta ronda (ajuste 5, `tests/test_privacy_gateway_production_posture.py`): cada una de esas tres
desviaciones, probada por separado, hace que `Settings()` lance `ValueError` al arrancar.

### Configuración de activación segura (resumen para quien despliegue)

| Variable | Valor en producción | Por qué |
|---|---|---|
| `MIA_PRIVACY_GATEWAY__ENABLED` | `true` | Obligatorio; `Settings` rechaza el arranque si falta |
| `MIA_PRIVACY_GATEWAY__FAIL_OPEN` | `false` (o no definir: es el default) | Un fallo de Presidio debe bloquear la llamada, nunca enviarla sin proteger |
| `MIA_PRIVACY_GATEWAY__VAULT_KEY` | clave real desde Key Vault, nunca hardcodeada | Cifra el Token Vault (Fernet); vacía solo se permite fuera de producción |
| `MIA_PRIVACY_GATEWAY__DEFAULT_POLICY` | `standard` por defecto; usar `strict`/`aggregated` explícitamente en dominios de datos muy sensibles (nóminas individuales) | Política contextual, ver ajuste 1 |
| `MIA_PRIVACY_GATEWAY__VAULT_TTL_SECONDS` | según necesidad operativa (900 por defecto) | Cuánto puede tardarse en restaurar un token antes de que caduque |

Ninguna de estas variables se activa sola en producción por "olvido" — están bloqueadas por el
validador. Lo que SÍ requiere decisión humana explícita, no automatizable: activar
`environment=production` en sí mismo, y confirmar que se ha validado en preproducción real antes.

## Bloque II (Advanced Intelligence & Reporting Engine) — por empezar

Autorizado para empezar tras el cierre del desarrollo principal del Bloque I (esta ronda). Jobs en
segundo plano ya autorizados para este bloque. Requisitos explícitos del usuario que el diseño debe
cumplir desde el principio (no como adaptación posterior):

- **Integra el Privacy Gateway desde su arquitectura**: cualquier llamada LLM del motor de informes
  pasa por `build_llm_provider()` igual que el resto de mIA — no se construye un segundo camino.
- **Marca obligatoria**: todo PDF/XLSX/PPTX generado debe llevar el logotipo oficial de Sunset Beach
  Club. El mecanismo ya existe hoy para los informes RRHH actuales
  (`mia.assets.resolve_logo`, usado en `src/mia/modules/rrhh/informes/tools.py`) — el motor de Bloque II
  debe reusarlo, no reinventarlo.
- **Contrato heredado del ajuste 4 de esta ronda, ya verificado sobre el generador actual** (ver
  `tests/test_privacy_gateway_reporting_contract.py`): el documento final se renderiza en el backend
  directamente desde los datos originales autorizados (nunca reconstruido a partir de lo que "recuerde"
  o repita el LLM). El motor de Bloque II debe preservar este contrato, no debilitarlo.
- **Pruebas de extremo a extremo obligatorias**: desde la petición del usuario hasta la apertura real
  del archivo generado, para los tres formatos — no basta con que el renderizador aislado funcione
  (mismo principio que ya exige este proyecto para cualquier flujo conversacional).
- **No declarar producción lista** hasta verificar AMBOS bloques (Gateway + Reporting Engine) en un
  entorno de preproducción real.

## Cómo continuar en la próxima sesión

1. Lee este archivo completo antes de tocar nada.
2. Si se decide avanzar a producción real para el Bloque I: seguir la checklist de "Decisión deliberada"
   abajo, validar en preproducción real, y medir rendimiento bajo concurrencia real (no solo
   secuencial) — nada de esto se ha hecho todavía en ninguna sesión.
3. Empezar el diseño del Bloque II (Advanced Intelligence & Reporting Engine) respetando los requisitos
   de la sección anterior.
4. No reabras las decisiones ya tomadas (cobertura global no solo nóminas; Presidio sí; jobs en segundo
   plano sí para el Bloque II; política contextual de importes, no anonimización indiscriminada) salvo
   que el usuario lo pida explícitamente.
