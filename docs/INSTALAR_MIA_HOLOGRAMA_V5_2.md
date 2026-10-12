# mIA Sunset Beach Club — Holograma V5.2

## Qué incluye

Versión **solo del mundo holograma**, incremental sobre **V5.1**.
No se modifica nada de los mundos 3D/2D, ni `src/core`, backend, GLB,
texturas, rig o biblioteca original de 84 animaciones.

Esta versión distingue de forma explícita dos objetivos:

1. **Pantalla de desarrollo/operación:** holograma híbrido, narrativa premium,
   datos de contexto, botón de micrófono de tres estados y chat a la derecha.
2. **Salida para ventilador LED:** negro absoluto, encuadre centrado dentro de
   disco 1:1, **rostro frontal opaco con textura original**, cuerpo cian
   translúcido, voz predominante, un máximo de dos KPIs o una gráfica corta.
   No se renderizan tablas, textos largos ni controles sobre el ventilador.

## Instalar

1. Guarda una copia de la carpeta `frontend/src/worlds/hologram/`.
2. Descomprime el ZIP desde la raíz de `frontend/`, respetando rutas.
3. Se sustituyen **cuatro** archivos existentes:
   - `src/worlds/hologram/main.js`
   - `src/worlds/hologram/index.html`
   - `src/worlds/hologram/hologram-material-v51.js`
   - `src/worlds/hologram/hologram-premium-v5.js`
4. Se incorporan **dos** archivos nuevos:
   - `src/worlds/hologram/hologram-director-v52.js`
   - `src/worlds/hologram/hologram-projection-v52.css`
5. **No sobrescribas** `src/worlds/hologram/style.css`: V5.2 usa una capa CSS
   adicional. Las dependencias de core, incluido `MiaBootLoader` V4.9,
   se reutilizan sin alterarlas.
6. Ejecuta `npm run dev` o el procedimiento IIS ya utilizado y recarga `Ctrl+F5`.

## Entrar y escuchar bienvenida

- El loading utiliza el progreso REAL del GLB hasta el 100 %.
- Prepara el audio `/api/voice/stream` mientras descarga el GLB.
- Cuando está listo muestra **«Continuar · escuchar a Mía»**.
- Al pulsarlo, `welcomeVoice.replay()` llama a `audio.play()` desde el
  `click` verdadero, sin clics simulados ni `await` previo. A la vez se
  inicia **la animación de bienvenida específica del holograma**, diferente
  de `mIA_SEQ_BIENVENIDA` del mundo 3D.
- Si el navegador lo bloquea, aparece la opción de reintentar o continuar
  sin sonido; si falla el servidor de voz puede usar síntesis del navegador.
- El micrófono **permanece apagado por defecto**.

> El éxito de la reproducción inicial aún depende de las políticas del
> navegador y del dispositivo de audio. No puede garantizarse sin prueba real.

## Abrir y comparar modos

Añade los parámetros a la URL **actual** del mundo holograma:

| Parámetro | Resultado |
| --- | --- |
| Sin parámetros | Modo de operación V5.1 híbrido en monitor, pero con animaciones propias V5.2 |
| `?fan=1` | Salida LED negra, cara opaca, cuerpo translúcido, sin chat ni tablas |
| `?fan=1&controls=1` | Ensayo del ventilador con control de chat visible al operador |
| `?fan=1&shot=portrait` | Ensayo de primer plano facial; no para proyección final a cuerpo completo |
| `?fan=1&quality=ultra` | Más supermuestreo en pantallas rápidas, con más consumo GPU |
| `?fan=1&avatar=hybrid` | Comparar el shader híbrido previo |
| `?fan=1&avatar=classic` | Comparar la radiografía V4 con rostro menos definido |
| `?fan=1&avatar=natural` | Comparar materiales 3D naturales |
| `?fan=1&face=0.90&glow=1.25` | Afinar textura facial y halo |
| `?softNormals=1` | Atenuar relieve normal/bump si hay manchas o arrugas oscuras |

Si el enlace termina en una URL con `?`, añade los demás parámetros con `&`.

### Manejo del micrófono durante proyección sin controles

Por seguridad y continuidad con V4.4, el micrófono **NO** empieza a escuchar
cuando pulsas Continuar. Desde el teclado del ordenador conectado al
ventilador, **M** recorre los tres estados:

`apagado -> una consulta -> escucha continua -> apagado`.

Es una operación explícita del usuario. También puede utilizarse
`?fan=1&controls=1` para visualizar el control durante pruebas.
No se incluye en este parche un sistema de control remoto entre dos navegadores.

## Perfil de animaciones holográfico

`hologram-director-v52.js` sustituye solo en holograma a `MiaBehaviorV4`.

- Bienvenida: `mIA_SEQ_OFRECER_AYUDA`, con alternativas frontales.
- Escucha: `mIA_SEQ_ESCUCHA_ACTIVA`.
- Consulta: `mIA_SEQ_CONSULTANDO_DATOS`, `mIA_SEQ_PENSANDO`, `mIA_SEQ_ESPERA`.
- Voz: `mIA_TALK_ALT3`, `mIA_SEQ_RESPUESTA_CORTA`, etc.
- Indicadores: gestos de explicación, asentimiento y señalización suaves.
- Esperas largas: gestos contenidos y pacientes, **sin caminar ni girar**.
- Las transiciones se coordinan por estados y se cancelan al cambiar de
  operación. No se modifica ningún clip dentro del GLB.

Esto constituye un repertorio y una coreografía propia del holograma;
**no se han creado nuevos ficheros de animación**: se reutilizan selectivamente
los 84 clips existentes y se secuencian de una forma diferente al mundo 3D.

## Comprobaciones realizadas y pendientes

Realizadas:
- 27 pruebas unitarias de V5, V5.1 (adaptadas) y V5.2.
- Sintaxis JavaScript `node --check` de los archivos tocados.
- Pruebas unitarias de materiales, personalidad, datos y micrófono.
- Chromium headless: negro exacto RGB(0,0,0), 1–2 KPIs, barra oculta y sin
  scroll horizontal en resoluciones 1920×1080, 1440×900, 1080×1080 y 390×844.
- Chromium: simulación del loading V4.9, progreso al 100 % y **activación de
  usuario válida (`navigator.userActivation.isActive === true`)** al pulsar
  Continuar; una sola llamada a la función de voz.

Pendientes:
- **Renderizar con el GLB real y validar el shader en WebGL/GPU de destino.**
- **Probar la reproducción ElevenLabs en tu Chrome/equipo.**
- **Probar físicamente el ventilador RD-150 HDMI PRO**, pues resolución,
  giro, brillo y tamaño de rostro varían entre dispositivos.
- Build completo Vite (no disponible la instalación de dependencias
  en este entorno de preparación del parche).

La cara opaca será más legible que una silueta radiografiada *si la
resolución y el contraste del equipo físico lo permiten*. El efecto no
convierte al ventilador en una pantalla volumétrica real.

## Reversión

1. Restaura `main.js`, `index.html`, `hologram-material-v51.js` y
   `hologram-premium-v5.js` de la copia V5.1.
2. Elimina `hologram-director-v52.js` y `hologram-projection-v52.css`.
3. No hay que modificar ni reexportar el GLB.
