# mIA Desktop SBC V0.2.5 | Visibilidad, identidad y control de voz

## Actualización incremental sobre V0.2.4

1. Cierra **completamente** mIA Desktop desde el icono de la bandeja (`Salir de mIA Desktop`).
2. Haz copia de seguridad de la carpeta `mia-desktop` y de `%APPDATA%\mia-desktop-sbc\desktop-settings.json` si existe.
3. Extrae el ZIP en la raíz de `mia-desktop`, conservando las rutas `src/...`, y sobrescribe solo los archivos incluidos.
4. Conserva el GLB, `node_modules`, los logos y tu configuración. **No ejecutes npm install ni npm audit fix --force.**
5. Ejecuta `npm start`. Este comando vuelve a compilar los renderizadores JS mediante el script `build` existente.

## Correcciones

- Minimización persistente: se impide que los callbacks retrasados de carga del avatar vuelvan a mostrar la ventana. Los comandos de voz tienen un periodo breve de protección tras ocultar el personaje. La orden de ocultación no cierra el proceso ni desactiva la bandeja.
- Frases independientes y configurables: `Hola mIA` (mostrar), `Oculta mIA` (ocultar) y `Cierra mIA` (salir completamente). El cierre requiere una coincidencia completa de la gramática local y un umbral de confianza superior. Solo están disponibles con la activación por voz habilitada y un motor SAPI `es-ES` funcional.
- Modos de entrada de voz en Configuración:
  - Desactivado: no se abre el micrófono ni se activa reconocimiento (la salida hablada se controla por separado).
  - Estándar: se escucha una consulta tras pulsar Hablar, el atajo o la frase configurada; se revisa el texto reconocido.
  - Manos libres: cuando se inicia desde Hablar o una activación configurada, se abre otra escucha tras terminar la respuesta. Si la confianza del dictado es inferior al 80 %, espera revisión antes de enviar. El botón «Terminar conversación» detiene la cadena.
- PowerShell/SAPI: reconocimiento de tres órdenes, ventanas de fin de silencio más cortas, dictado con espera máxima reducida. El proceso de escucha se pausa cuando mIA está reproduciendo su propia voz para limitar el eco.
- Ficha individual de empleado: ante una petición identificable como ficha/perfil/expediente, el cliente exige nombre y apellidos suficientes y comprueba que los datos estructurados coinciden con **una única persona**. Si encuentra identidades distintas o no puede verificarlas, bloquea la presentación. **Esto no repara la búsqueda del backend**: la autenticación, permisos y resolución inequívoca por identificador deben implementarse y verificarse allí.
- Se mantiene la exportación Excel/CSV y la interfaz premium de resultados, sin crear datos ficticios.

## Diagnósticos

Menú Configuración > Abrir carpeta de diagnósticos. Por defecto, `%APPDATA%\mia-desktop-sbc\logs`.
Los registros de esta revisión consignan solo categorías/códigos y duraciones, no consultas, nombres de empleados, respuestas, audios ni transcripciones.

## Pruebas y límites

49 pruebas Node.js superadas en esta entrega. Sintaxis JS verificada. Sin pruebas reales de micrófono SAPI, TTS, integración con el backend SBC ni renderizado Electron sobre el Windows del usuario en este entorno. Los cambios del reconocimiento reducen tiempos configurados, pero la latencia real puede seguir dependiendo de Windows, el controlador del micrófono y la disponibilidad del motor SAPI.

## Pruebas manuales recomendadas

1. Mostrar mIA; minimizar desde el botón; esperar 30 segundos: no debe reaparecer.
2. Ocultarla mediante voz y después decir `Hola mIA`: debe aparecer solo tras esta activación explícita.
3. Decir `Oculta mIA`; decir `Cierra mIA`; comprobar que el icono de bandeja desaparece tras el cierre.
4. Probar los tres modos de micrófono y verificar que manos libres no se escucha a sí misma mientras habla.
5. Solicitar una ficha con nombre completo; si el backend devuelve otra identidad, la aplicación debe bloquear esos resultados sin mostrarlos.
6. Realizar una consulta general de empleados y exportar la tabla para comprobar que no se ha alterado esa funcionalidad.
