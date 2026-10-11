# Mía SBC V4.4 — Micrófono cíclico y esperas expresivas

**Parche INCREMENTAL sobre mIA V4.3 (loading dinámico), que debe incluir la corrección V4.2.1 de micrófono manual.**

## Instalación sin perder el trabajo anterior

1. Realiza copia de seguridad del `frontend` existente. Si se usa control de versiones, crea un commit o una rama previa.
2. Extrae este ZIP **directamente en la raíz de `frontend/`** preservando las rutas `src/...` y `tests/...`. Sobrescribe únicamente los archivos presentes en el ZIP.
3. No sustituye ni duplica `public/models/mIA_SBC_V4_84_ANIMACIONES.glb` (84 clips). Tampoco modifica el mundo 2D, backend, materiales, texturas, imágenes del loader, ni `dist`.
4. Desde `frontend/`, ejecuta:

   ```powershell
   npm ci
   npm run dev
   ```

5. Recarga el navegador con Ctrl+F5 y prueba primero el 3D y después holograma.
6. Solo tras validarlo ejecuta `npm run build` y publica el contenido generado de `dist` según tu proceso habitual.

## Exactamente tres estados del micrófono

| Pulsación | Estado | Captura de voz |
|---|---|---|
| Inicio | **APAGADO** | No pide permisos ni escucha |
| 1.ª | **UNA CONSULTA** (distintivo `1`) | Empieza a escuchar una frase; después de dictar se detiene físicamente |
| 2.ª | **CONTINUO** (distintivo `∞`) | Escucha varias consultas sucesivas, con pausas temporales durante el backend y TTS |
| 3.ª | **APAGADO** | Cancela cualquier captura, detiene reintentos y vuelve al principio |

Para respetar el orden de **las tres pulsaciones**, al terminar la primera consulta el micrófono deja de capturar, pero el control conserva visualmente la **etapa 1 en pausa**. Así la siguiente pulsación activa **CONTINUO**, aunque ya hayas recibido la respuesta.

- No se solicita el permiso al cargar la web; solo tras pulsar voluntariamente el botón.
- El botón flotante se mantiene donde está al pulsarlo; **no abre automáticamente la barra de escritura**.
- En CONTINUO, el reconocimiento puede cerrar sesiones a causa de los límites del navegador; se vuelve a activar solamente porque el usuario ha optado expresamente por CONTINUO.
- Durante la respuesta y la voz sintetizada, la captura se pausa para que Mía no se escuche a sí misma. Después se reanuda únicamente si CONTINUO sigue seleccionado.
- El botón con `∞` sigue indicando que el modo está seleccionado aunque esté momentáneamente en pausa.
- Al ocultar la pestaña se interrumpe la captura. Al volver, se recupera CONTINUO solo si estaba expresamente activado y no hay consulta suspendida.
- Los errores de permisos apagan el modo para que no haya una cadena de solicitudes.
- El reconocimiento de voz requiere compatibilidad del navegador y contexto seguro (HTTPS o localhost). La entrada escrita sigue disponible.

## Nuevas animaciones durante esperas largas

Las tres **ya forman parte del GLB de 84 clips**: no se reimporta ni se vuelve a Blender.

| Tiempo de espera aproximado | Movimiento | Comportamiento |
|---|---|---|
| 0–20 s | `mIA_THINK`, `mIA_SEQ_CONSULTANDO_DATOS`, `mIA_TYPING` | Procesamiento normal |
| 20 s y más | `mIA_SEQ_ESPERA` | Espera tranquila entre gestos normales |
| 35 s y más | `mIA_IDLE_SAD` | Breve gesto de aburrimiento/impaciencia discreta, sin quedar triste permanentemente |
| 65 s y más | `mIA_WALK_CIRCLE` | Pequeño recorrido circular controlado en 3D con suavizado y retorno a la posición original |

El paseo circular del **mundo 3D** es deliberadamente corto y suave: el GLB no contiene un desplazamiento físico de cadera completo (el track de cadera es constante), por lo que se añade una trayectoria local moderada desde Three.js. Se limita la orientación para que Mía siga mirando al usuario. Se detiene suavemente al llegar el resultado o iniciar otro gesto.

El **holograma** sí puede usar el gesto aburrido, pero no desplaza el personaje fuera de la proyección ni activa un paseo circular.

Los comentarios de progreso siguen utilizando texto natural, sin porcentajes inventados. Las animaciones se cancelan cuando llega la respuesta. No se cambian las presentaciones premium ni el comportamiento de ausencia de tarjetas en respuestas conversacionales.

## Archivos afectados

Consulta `docs/MANIFIESTO_MIA_V4_4.json` para rutas, SHA-256 y tamaños exactos. Este ZIP contiene exclusivamente componentes nuevos/modificados, documentación y pruebas.

## Validación realizada

- `node --check`: sintaxis de módulos modificados correcta.
- `node --test tests/mia-v42.test.mjs tests/mia-v43-loader.test.mjs tests/mia-v44.test.mjs`: **28 pruebas superadas**.
- HTML: identificadores de controles únicos. CSS: sintaxis analizada sin errores.
- Catálogo GLB revisado: los clips `mIA_IDLE_SAD`, `mIA_SEQ_ESPERA` y `mIA_WALK_CIRCLE` existen realmente.

**Pendiente de validar en tu equipo:** `npm ci`/build Vite (no disponible offline aquí), captura real de voz en Chrome/Edge, audio/TTS real y naturalidad visual del paseo circular en Three.js/WebGL.

## Pruebas manuales recomendadas

1. Entrar al mundo 3D: loading V4.3 y bienvenida; micrófono apagado.
2. Pulsar micrófono: indicador `1`, permitir permiso si el navegador lo pide y dictar una consulta.
3. Confirmar que al acabar de hablar NO sigue escuchando y el indicador `1` queda en pausa.
4. Pulsar de nuevo: aparece `∞` y pasa a modo continuo.
5. Dictar dos preguntas: durante procesamiento/TTS no debe escuchar y después debe reanudar.
6. Pulsar por tercera vez: micrófono apagado, sin reactivación posterior.
7. Repetir en el holograma: mismas tres pulsaciones.
8. Simular una consulta larga: a partir de 35 s aparece el gesto de aburrimiento y de 65 s en el 3D se prueba el breve paseo circular.
9. Cancelar o completar la consulta durante el paseo: Mía vuelve suavemente al centro, no salta de posición.
10. Comprobar conversación simple sin panel y fichas/KPI/tablas con paneles premium y paginación de 20 filas.
11. Comprobar voz/síntesis con micrófono continuo: Mía no debe transcribir su propia respuesta.

## Reversión

Restaura únicamente las rutas del manifiesto desde tu copia de seguridad de **V4.3**; no cambies el GLB, los activos del loading ni el mundo 2D. Haz de nuevo una prueba en modo desarrollo antes de compilar o publicar.
