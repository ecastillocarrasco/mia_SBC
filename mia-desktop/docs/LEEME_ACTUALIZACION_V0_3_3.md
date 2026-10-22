# mIA Desktop SBC V0.3.3 — Reparación de control del micrófono

## Incidencia corregida

En la V0.3.2 había una comilla HTML mal colocada en `src/ui/bubble.html`:
`id="voiceStatus class="...`. El JavaScript no encontraba el elemento `voiceStatus`.
Al entrar en el chat o cambiar de modo, `stateText()` fallaba antes de poder
invocar `setChatMicMode()`. En consecuencia, el motor de escucha anterior podía
seguir activo aunque la interfaz pareciera indicar el modo desactivado.

## Cambios

- Corregido el identificador HTML que impedía aplicar cambios de modo.
- Botón «Detener conversación» disponible también durante escucha activa.
- Cuando la detección de la frase de activación está habilitada, la interfaz
  advierte que el micrófono se encuentra escuchando **solo comandos**.
- Nuevas pruebas que verifican que todos los IDs usados por la interfaz
  existen realmente en el HTML.

## Distinción entre modos

1. **Desactivado**: apaga captura, vigilancia por comandos y dictado.
2. **Activado · una pregunta**: solo dicta después de pulsar Hablar; si
   «Activar mIA al reconocer una frase» está marcado en Configuración,
   Vosk mantiene abierto el micrófono exclusivamente para reconocer comandos,
   sin transcribir preguntas al chat.
3. **Conversación abierta**: abre el micrófono para conversar por turnos,
   hasta pulsar Detener, cambiar de modo o cerrar/minimizar el chat.

Para comprobar un **apagado físico del micrófono** en Windows, selecciona
«Desactivado» y verifica que desaparece el indicador de uso del dispositivo.

## Instalar

1. Cierra mIA Desktop por completo desde la bandeja.
2. Haz una copia de seguridad de la carpeta actual.
3. Extrae el contenido del ZIP encima de la raíz del proyecto `mia-desktop`;
   respeta las carpetas `src`, `tests` y `package.json`.
4. Ejecuta `npm start` o `INICIAR_MIA_DESKTOP.cmd`.
5. Comprueba, sucesivamente, apagado, una pregunta y conversación abierta.

## Mover el proyecto a otra ruta

Puedes mover **toda** la carpeta del proyecto, con Electron detenido.
La aplicación resuelve HTML, scripts y recursos con rutas del propio proyecto,
mientras que ajustes, personaje GLB importado y modelos Python están en la
carpeta de datos de usuario. No hay que reinstalar los modelos al moverlo.
Actualiza los accesos directos o tareas que apunten a la ruta antigua;
si cambias de equipo, estos datos de usuario no se transfieren automáticamente.

## Alcance de las pruebas

Pruebas de Node sobre código y controles DOM; no se ha realizado una sesión
con micrófono físico Windows. Si continúa el problema, adjunta el log técnico
sin contenido empresarial y precisa si se trata de un dictado automático,
micrófono ocupado o comandos que no se detectan.
