# mIA Desktop SBC V0.3.7 — Corrección del arrastre del avatar

## Incidencia

La ventana transparente del avatar puede quedar en modo `setIgnoreMouseEvents(true)` al pasar el cursor por un píxel transparente. En Windows, cuando la ventana ignora los clics, no es fiable depender de `pointermove` del navegador para reactivarla. En consecuencia, se ve el avatar pero el ratón atraviesa la ventana y no puede arrastrarse.

## Corrección

- El proceso Electron principal consulta periódicamente la posición global del cursor mientras la ventana del avatar está visible y no se arrastra. La posición se transforma a coordenadas locales, incluso en monitores situados a la izquierda del principal.
- El renderer verifica la geometría visible y una zona central de agarre tolerante para el modelo animado. Si el cursor está sobre el avatar, desactiva el modo de clics transparentes y permite arrastrarlo.
- Durante el arrastre nunca puede reactivarse `setIgnoreMouseEvents(true)`, aunque llegue un evento de hit-test atrasado.
- La posición del avatar se actualiza desde Electron y permanece dentro del área útil del monitor; el chat abierto acompaña el desplazamiento.
- El cambio de foco de la ventana no cancela por sí solo un arrastre en curso; se detiene por `pointerup`, `pointercancel` o el límite de seguridad existente.
- El encabezado del chat continúa siendo arrastrable; su redimensionado permanece intacto.

## Instalación incremental (sobre V0.3.6)

1. Sal completamente de mIA Desktop desde el icono de la bandeja; no basta cerrar el bocadillo.
2. Haz copia de seguridad de la carpeta de mIA Desktop.
3. Extrae este ZIP sobre la raíz de `mia-desktop`, conservando las rutas `src/...` y sobrescribiendo los archivos incluidos.
4. Inicia con `npm start`. No necesitas reinstalar Electron ni los modelos Vosk/Whisper o GLB.
5. Con mIA visible, deja el puntero un instante sobre su cuerpo hasta que aparezca la mano de arrastre y arrastra con el botón izquierdo. Comprueba también el desplazamiento del chat arrastrando su encabezado.

## Pruebas y límites

105 pruebas automáticas (`npm test`) superadas, incluidas comprobaciones de hit-test, cambios de transparencia durante el arrastre y geometría multimonitor. `node -c` de los módulos principales: correcto. No se ha ejecutado Electron con una pantalla Windows real. La compilación gráfica local no se pudo ejecutar aquí por falta de `esbuild` en este entorno; `npm start` la realizará en el equipo del usuario, donde ya está instalado el proyecto.

No se ha modificado el backend SBC, el motor de informes, la voz, las credenciales ni los mundos web.
