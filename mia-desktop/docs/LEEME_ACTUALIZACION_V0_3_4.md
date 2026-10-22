# mIA Desktop SBC V0.3.4 — Evitar ocultaciones involuntarias

## Motivo

La V0.3.3 podía ocultar mIA sin una orden real: el reconocedor Vosk aceptaba `Oculta mIA` desde resultados **parciales** de una gramática cerrada, lo que favorecía las coincidencias falsas. El atajo global también tenía una acción de alternancia que **minimizaba** cuando el chat estaba visible. Adicionalmente, pulsar Escape podía ocultar la ventana.

## Cambios de seguridad y usabilidad

1. `Oculta mIA` y `Cierra mIA` nunca se ejecutan desde resultados parciales de Vosk. Deben tener un resultado final que coincida de forma exacta con la frase configurada **y** una segunda transcripción independiente con Whisper, también exacta. Si hay duda o falla un motor, no se oculta ni se cierra la aplicación.
2. La misma verificación doble se aplica si una orden aparece en el dictado del chat: Whisper y Vosk deben estar de acuerdo, o se rechaza la orden sin enviarla al backend.
3. `Hola mIA` continúa admitiendo una coincidencia parcial estable, al tratarse de una acción no destructiva.
4. El atajo global ahora **siempre muestra/abre mIA**; no sirve para minimizarla accidentalmente.
5. La tecla Escape **no minimiza** la ventana/avatar ni oculta el chat. En el campo de texto, Escape solo detiene la escucha.
6. Se admiten únicamente orígenes explícitos de ocultación: menú de bandeja, botón de minimizar del chat, menú contextual del avatar, cierre de ventana o voz verificada.
7. Cada ocultación real registra `visibility_change`, junto al código de origen, y las órdenes de voz no confirmadas registran `voice_command_rejected`. No se guarda audio, transcripciones, consultas ni datos de empleados.
8. Se conservan la despedida animada y ElevenLabs cuando **sí** se reconoce correctamente «Oculta mIA», y la confirmación para «Cierra mIA».

## Instalación encima de la V0.3.3

1. Cierra mIA Desktop completamente desde la bandeja de Windows.
2. Guarda una copia de seguridad de la carpeta de proyecto.
3. Extrae el ZIP encima de la carpeta `mia-desktop` y sobrescribe los ficheros suministrados (respeta la estructura `src/...` y `tests/...`).
4. Ejecuta `npm start`. No necesitas descargar modelos nuevos, reinstalar `node_modules` ni copiar el GLB.

No afecta al backend SBC ni a sus mundos web.

## Pruebas aconsejadas

- Abre el chat y utiliza el atajo global varias veces: mIA debe permanecer visible.
- Pulsa Escape mientras escribes: no se deben cerrar ni chat ni avatar.
- Con `wakePhraseEnabled` activado en Configuración y modo `Activado`, di frases normales cerca de mIA: no debe ocultarse.
- Di **«Oculta mIA»** con claridad: puede tardar algo más debido a la confirmación Whisper, pero debe despedirse antes de ocultarse.
- Vuelve a abrirla y di **«Cierra mIA»**: debe solicitar confirmación. No debe cerrarse sin tu confirmación.
- En modo **Desactivado**, no debe mantenerse la escucha ni producirse ocultación por voz.

### Si se vuelve a ocultar sola

En Configuración > **Abrir diagnósticos**, extrae únicamente los eventos técnicos `visibility_change`, `voice_command` y `voice_command_rejected` del momento del fallo. Los códigos indicarán la procedencia de la acción. No adjuntes información personal de empleados.

## Verificación

80 pruebas automatizadas (Node y simulación de audio local en Python), sintaxis JS y Python correcta. **Pendiente de validar con Vosk, Whisper y el micrófono reales en el equipo Windows del usuario.**
