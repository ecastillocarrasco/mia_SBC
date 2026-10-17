# mIA Desktop SBC V0.3.1 — continuidad Employee360 y transiciones del avatar

**Base:** mIA Desktop V0.3.0, sin modificaciones locales. **Tipo:** parche incremental (solo ficheros modificados y nuevos).

## Novedades

- **«Hola mIA»:** apertura con `mIA_SEQ_BIENVENIDA` y saludo alegre mediante la ruta ElevenLabs existente; respeta opción de voz y fallback.
- **«Oculta mIA»:** antes de ocultar, reproduce `mIA_SEQ_DESPEDIDA` y una despedida corta. Si no puede reproducirse, la ocultación dispone de timeout de seguridad.
- **«Cierra mIA»:** primero solicita confirmación; si se acepta, se despide con animación y voz y entonces cierra completamente. Repeticiones del comando no abren varios cuadros.
- **Motor de voz:** se conserva cargado entre respuestas; no se apaga Vosk/Whisper cada vez que mIA habla. El cierre total y el modo de voz desactivado sí liberan los recursos.
- **Conversación:** reutiliza en RAM el `context` enviado por el backend (con límite de 24 KB) y conserva solo el nombre de una ficha de identidad comprobada. No escribe datos personales ni el historial en los logs o en disco.
- **Follow-ups:** «Sí, es él, dame su ficha» vuelve a consultar el expediente de la misma persona. «Sí, es él, dame la fecha» pide precisar de qué fecha se trata.
- **Empleado360:** se reconoce el contrato existente `data.presentation.schema = "mia.employee360.presentation"`, validando identidad por cabecera y/o empleado principal antes de mostrar KPI y apartados estructurados disponibles. No se mezclan otros empleados ni se declara «ficha completa» si la completitud no está acreditada.
- **Logs:** eliminada la doble anotación de cada comando de voz entre `voice.cjs` y `main.cjs`.

## Instalación

1. Cierra **totalmente** mIA Desktop desde la bandeja; espera a que salga el proceso.
2. Haz copia de seguridad de `mia-desktop` y sus preferencias.
3. Extrae el ZIP sobre la **raíz actual** de `mia-desktop`, conservando subcarpetas y sustituyendo solo los archivos contenidos.
4. No elimines el GLB, `node_modules`, los modelos locales Vosk/Whisper ni la configuración en `%APPDATA%`.
5. Ejecuta `npm start` (el script recompila el renderizador).

No requiere paquetes Python o npm adicionales. No modifica el backend, los mundos 2D/3D/HG ni el motor de informes.

## Pruebas sugeridas en Windows

1. Con mIA oculta: «Hola mIA» una vez; verificar voz, gesto de alegría y aparición.
2. Con mIA visible: «Oculta mIA»; verificar despedida previa y que permanece oculta.
3. «Cierra mIA»; verificar confirmación, voz y animación antes del cierre. Cancelar no debe cerrar.
4. Abrir por texto «Ficha completa de [nombre completo]», seguida de «Sí, es esa persona, dame su ficha» (sin nombres inventados).
5. Comprobar que el resultado presenta `Employee360` si el backend lo entrega; si solo entrega una fila de listado, debe identificarse como incompleto.
6. Preguntar por una **fecha concreta** (p. ej. «¿Cuál es su fecha de incorporación?»); una fecha ambigua debe pedir aclaración.
7. Revisar los logs: códigos `backend_chat`, `voice_command`, `backend_tts`, sin transcripciones ni datos personales.

## Validación técnica efectuada

- **65 pruebas Node automatizadas superadas** (regresión y nuevas pruebas con datos sintéticos).
- Revisión de sintaxis JavaScript en archivos modificados.
- **No se ha probado Electron con Windows, el micrófono ni el backend SBC real** en este entorno. Tampoco se ha validado la completitud de las fichas del backend.

## Límites conocidos

- Si el backend ofrece únicamente una fila del listado, Desktop no puede fabricar la ficha Employee360 ni consultar herramientas internas a las que el backend no conceda acceso. La verificación definitiva debe realizarse en el backend, manteniendo autenticación, permisos y filtros.
- Las consultas de turnos de una franja concreta deberán comprobarse frente al módulo real de turnos y su fecha de actualización. Los logs de Desktop no registran datos empresariales, por lo que no permiten validar los recuentos comunicados por el servidor.
- El modelo local de Whisper tarda aproximadamente 4,7–8,9 s en transcribir las frases de la sesión analizada; se necesita una futura ronda de optimización y medición en el equipo de Windows.
