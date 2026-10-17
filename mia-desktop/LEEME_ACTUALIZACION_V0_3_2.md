# mIA Desktop SBC V0.3.2 - Control explícito del micrófono

**Base:** mIA Desktop V0.3.1 sin modificaciones locales. Actualización incremental, únicamente archivos modificados y nuevos. No se modifica el backend ni los mundos web 2D, 3D y holograma.

## Problema corregido

El chat podía iniciar dictados después de «Hola mIA», al utilizar un atajo o al conservar activo el modo conversación, aun cuando no se había pulsado «Hablar». Además, Vosk/Whisper mantenía abierto el dispositivo de captura incluso estando en reposo. Esto podía hacer que el indicador de Windows mostrase el micrófono ocupado y causar transcripciones inesperadas.

## Los tres modos del chat

- **Desactivado**: cancela las capturas pendientes y apaga por completo el proceso de voz local. Deja de escuchar también las frases «Hola mIA», «Oculta mIA» y «Cierra mIA». La escritura y la reproducción de la voz de mIA siguen funcionando.
- **Activado - una pregunta**: espera hasta que el usuario pulse «Hablar»; captura una sola frase, luego cierra el dispositivo. Respeta la preferencia de revisar o enviar el dictado. **Si en Configuración sigue habilitada «Activar mIA al reconocer una frase», el micrófono sí podrá mantenerse abierto SOLO para reconocer comandos** (sin transcribir preguntas) y el chat mostrará «SOLO COMANDOS»; para privacidad completa elegir Desactivado.
- **Conversación abierta**: se inicia exclusivamente cuando el usuario lo elige activamente desde el chat o pulsa «Iniciar conversación». Detecta una pregunta, espera a la respuesta hablada de mIA y abre la siguiente escucha por turnos. «Detener» cancela el dictado y suspende la conversación. Al ocultar o cerrar el chat la conversación se detiene. Una configuración guardada de conversación nunca inicia dictado automáticamente tras abrir Desktop.

El desplegable está dentro del propio bocadillo Glass Premium, junto a un indicador APAGADO / EN ESPERA / SOLO COMANDOS / ESCUCHANDO / CONVERSANDO. No se alteran los colores del avatar ni la caja de texto blanca.

## Protección contra transcripciones tardías

- Un token de generación invalida transcripciones que llegan después de detener, ocultar o cambiar de modo.
- El proceso Electron aplica el modo OFF y cancela las capturas a nivel nativo; no depende únicamente del aspecto visual del botón.
- Los modelos locales pueden seguir cargados mientras el dispositivo de audio se cierra al terminar el dictado y cuando se detienen los comandos. Así se evitan recargas pesadas y capturas en reposo.
- Se deshabilitaron las preferencias heredadas `autoListenOnWake` y `autoListenOnShow`: el saludo, el atajo y la apertura de la ventana no empiezan a dictar.

## Instalación

1. Cerrar mIA Desktop completamente desde la bandeja de Windows (opción Salir).
2. Hacer copia de seguridad de la carpeta actual `mia-desktop` y de las preferencias si se desea.
3. Descomprimir el ZIP **en la raíz de `mia-desktop`**, respetando `src/...` y sobrescribiendo los archivos incluidos.
4. No borrar GLB, modelos de voz, `.venv` local, `node_modules` ni ajustes previos.
5. En la raíz ejecutar `npm start`. No se añaden dependencias.

## Pruebas en Windows recomendadas

1. Con chat abierto, seleccionar **Desactivado**. Hablar cerca del micrófono sin pulsar botones: no debe producirse dictado, ni permanecer capturando. «Hola mIA» no debe activarse en este estado.
2. Seleccionar **Activado - una pregunta**. No pulsar Hablar: no debe aparecer ninguna transcripción. Pulsar Hablar y dictar una pregunta de prueba no sensible. Debe capturarse una vez. Si los comandos se habilitaron expresamente, el indicador «SOLO COMANDOS» explicará la vigilancia local de las frases de control.
3. Elegir **Conversación abierta**: debe iniciar escucha automáticamente **solo por esa selección explícita**, enviar la consulta, reproducir la respuesta y volver a escuchar al finalizar la voz, nunca mientras habla.
4. Durante un dictado, cambiar inmediatamente a **Desactivado**: no debe llegar ninguna transcripción ni consulta tardía al chat.
5. Ocultar mIA en mitad de una conversación: no debe reabrirse la escucha cuando finalice cualquier respuesta anterior.
6. Cerrar totalmente y volver a arrancar. Si la preferencia era «Conversación abierta», debe permanecer **pausada** hasta que el usuario pulse «Iniciar conversación».

## Validación realizada

- 70 pruebas de Node superadas, incluidas 5 nuevas de configuración, bloqueo de captura y simulación del ciclo real de apertura/cierre de micrófono del worker Python.
- `node --check` y `python -m py_compile` superados.
- **Pendiente probar sobre Windows con el hardware real y el backend SBC**. No se ha confirmado aún el comportamiento del indicador físico de captura ni la latencia real del dispositivo en tu máquina.

## Seguridad

No se registran transcripciones, consultas, audio ni datos de empleados. Las llamadas al backend y ElevenLabs continúan como en V0.3.1, sin claves en el frontend.
