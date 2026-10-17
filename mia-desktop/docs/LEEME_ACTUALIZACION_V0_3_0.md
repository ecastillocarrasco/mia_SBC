# mIA Desktop SBC V0.3.0 — motor de voz local renovado

**Base exacta:** V0.2.6 (sin modificaciones locales). Este ZIP contiene *solo archivos modificados o añadidos*, no incluye el backend, el GLB, los modelos de voz, ni credenciales. Mantiene Electron, Three.js, el motor único de informes y los mundos 2D, 3D y holograma intactos.

## 1. Instalación sobre V0.2.6

1. Sal completamente de mIA desde el icono de la bandeja (no basta con minimizarla).
2. Haz una copia de seguridad de tu carpeta `mia-desktop` y guarda por separado su configuración en `%APPDATA%\mia-desktop-sbc`.
3. Descomprime este ZIP **dentro de la raíz de `mia-desktop`**, preservando rutas `src/voice/`, `src/main.cjs`, `src/ui/`, `tests/`, etc. Sobrescribe los archivos incluidos. **No** borres `node_modules`, `assets`, `avatar.glb` ni la configuración.
4. Ejecuta `INSTALAR_VOZ_LOCAL.cmd` desde la carpeta raíz. Necesitarás **Python 3.11 o 3.12 de 64 bits**, Internet y espacio libre suficiente para instalar librerías y modelos (varios cientos de MB). Se guardan en `%APPDATA%\mia-desktop-sbc\voice-runtime` y `%APPDATA%\mia-desktop-sbc\voice-models`, **fuera** del repositorio, de las rutas web y del backend. La instalación es explícita y puede tardar varios minutos. Puede requerir el runtime de Microsoft Visual C++ en Windows. La descarga es solo de bibliotecas y modelos, no de audio.
5. Inicia con `npm start` (no es necesario `npm install` para el código Electron). En Configuración, pulsa **Comprobar motor local**. Debe informar de que Vosk + faster-whisper está preparado. Activa `Activar mIA al reconocer una frase` si quieres escuchar comandos en segundo plano; selecciona el modo Estándar o Conversación.
6. Si aparece `MODEL_MISSING`, `DEPENDENCY_MISSING` o `MICROPHONE_UNAVAILABLE`, abre Diagnósticos y revisa los permisos de Windows (Configuración > Privacidad > Micrófono > Permitir que las aplicaciones de escritorio accedan al micrófono). Reinicia la aplicación tras instalar los modelos.

La **primera carga** de ambos modelos puede tardar varios segundos. Cuando el estado indique `Comandos locales preparados` la escucha continua estará activa. No hables hasta que aparezca `Micrófono preparado. Habla ahora` en el dictado; así comprobaremos la latencia real desde la primera versión.

## 2. Qué se cambia

- **Vosk en memoria**: escucha únicamente órdenes configuradas de mostrar/ocultar/cerrar; reconoce «Hola mIA», «Oculta mIA» y «Cierra mIA» sin reiniciar PowerShell. Las frases se modifican en Configuración. Para **cerrar totalmente** solicita confirmación por seguridad.
- **faster-whisper `base` local (int8 CPU)**: transcribe preguntas; usa captura continua de micrófono con VAD, aproximadamente 500 ms de audio anterior al inicio detectado y silencio final de 680 ms. Solo se abre un capturador local para las dos funciones; el modo dictado tiene prioridad y los comandos no se envían como consultas al backend.
- **Modos**: Off = sin captura (puedes seguir escribiendo y utilizar ElevenLabs para la salida); Estándar = una captura con revisión antes de enviar; Conversación = alternancia de dictado y respuesta hablada. La activación por frase es un ajuste independiente del modo de dictado. El micrófono se suspende mientras mIA reproduce audio para evitar realimentación.
- **Logs**: solo códigos de error y duraciones, sin transcripciones, nombres de empleados, preguntas, audio, respuestas ni identificadores privados. Eventos nuevos `speech_local_ready`, `speech_detected`, `speech_transcription`, `speech_local_error`.
- **Misma API SBC** y ElevenLabs. No se modifican el backend, el modelo GLB ni la protección de identidad de las fichas de empleados.

## 3. Privacidad

En **tiempo de ejecución**, el audio se procesa localmente y permanece en RAM, no se guardan WAV ni textos transcritos en ficheros de log. La instalación inicial descarga modelos desde Alphacephei y Hugging Face. No hay streaming de audio a esos proveedores. Las **preguntas resultantes** sí se envían al backend SBC existente, tal como ocurre en los mundos web. Antes de desplegar empresarialmente, valida suministro de modelos, permisos, actualizaciones y aceptación de privacidad.

## 4. Pruebas necesarias en Windows

1. `Comprobar motor local` con micrófono disponible. Comprueba `speech_local_ready` y tiempo de arranque del modelo.
2. Orden «Hola mIA» una vez (desde mIA oculta) y cronometra hasta que aparezca; después «Oculta mIA» y verifica que queda minimizada.
3. Pronuncia «Cierra mIA» y verifica que pide confirmación, no se cierra sin ella.
4. En modo Estándar dicta: «Necesito una lista de turnos»; confirma que se transcribe **completa**, que puede corregirse y que no se envía sin autorización cuando `Enviar automáticamente` está desmarcado.
5. En modo Conversación prueba la alternancia: pregunta → ElevenLabs → escucha, sin que la propia voz de mIA dispare órdenes.
6. En modo Off comprueba que escribir sigue funcionando y que no hay proceso de reconocimiento reteniendo el micrófono. Comprueba que las órdenes no se interpretan como preguntas.

## 5. Validación y límites

Comprobado con `node --test tests/*.test.cjs` (58 pruebas) y `python -m py_compile` (scripts de Python). **No se ha ejecutado en Windows ni descargado o probado físicamente los modelos** en este entorno: hay que validar PortAudio, dispositivo local, latencia, versiones de Python y exactitud de Vosk/Whisper. No se promete una precisión o tiempo de respuesta determinados antes de esas pruebas. Si el motor no está instalado, informa del problema en vez de utilizar SAPI silenciosamente.

**Reversión:** restaura los archivos originales de la V0.2.6. Puedes mantener o borrar la carpeta `voice-runtime`/`voice-models` sin modificar ningún dato del backend.
