# mIA Desktop SBC V0.2.2 — Avatar, voz, resultados premium y exportación

**Instalación incremental sobre V0.2.1.** El ZIP contiene exclusivamente archivos nuevos o cambiados; no es un instalador autónomo. Mantiene los mundos web 2D/3D/HG y el backend intactos. No reexporta ni modifica el GLB.

## Instalación

1. Cierra **por completo** mIA desde la bandeja > «Salir de mIA Desktop».
2. Haz una copia de seguridad de la carpeta `mia-desktop`.
3. Extrae el contenido del ZIP **directamente en la raíz de esa carpeta**, permitiendo sobrescribir los archivos del parche. No crees una subcarpeta adicional.
4. Conserva `node_modules`, `package-lock.json`, tu GLB (`assets/mIA_SBC_V4_84_ANIMACIONES.glb` o copia importada desde Configuración) y la configuración personal de la aplicación. No es necesario ejecutar `npm install`.
5. Arranca con `npm start`; el comando reconstruye `dist/` con `esbuild` previamente instalado en la V0.2.1.

## Cambios

- **Saludo en el inicio:** al terminar de cargar el GLB se dispara mIA_GREET, se intenta sintetizar el saludo con el endpoint existente de ElevenLabs y, si está activado, se utiliza la voz local como respaldo. Al terminar regresa al reposo. Permite incluir nombre, configurable, y desactivar el saludo.
- **Animaciones de reposo:** mIA_WALK_CIRCLE y mIA_SEQ_ESPERA (espera/aburrimiento) se pueden activar o desactivar por separado. Se alternan con otros gestos solo cuando mIA está ociosa, con esperas para evitar distracciones. Se usa el contenido del GLB original.
- **Avatar más fácil de desplazar:** arrastre gestionado por el proceso Electron y posición de escritorio; recorte dentro del área de trabajo del monitor. Su experiencia exacta necesita prueba real con el GLB y varios monitores.
- **Tamaño de personaje:** al cambiar tamaño se actualiza el ancho y alto real de la ventana transparente. El renderer recalcula su cámara y canvas.
- **Micrófono:** el reconocimiento local de Windows conserva el dictado para que se revise antes de enviarlo; ofrece alternativas cuando Windows las suministra y admite pausas mayores. Es necesario tener el motor SAPI es-ES instalado. Si el sistema no lo tiene, no puede garantizarse reconocimiento preciso. El envío automático por defecto está desactivado.
- **Bocadillo redimensionable:** arrastra su esquina inferior derecha. El tamaño se guarda entre sesiones y respeta límites.
- **Ventanas de resultados premium:** nueva cabecera corporativa granate/champán, estadísticas técnicas del contenido recibido, tarjetas KPI provenientes exclusivamente del backend, secciones editoriales, avisos claros de datos parciales, tablas con ordenación, búsqueda, paginación y vista ampliada; gráficos opcionales sobre columnas numéricas y categorías realmente presentes en los datos. Los gráficos representan filas existentes, sin agregaciones nuevas.
- **Exportaciones obligatorias en tablas:** cada tabla tiene CSV y Excel (.xlsx); se exportan las filas realmente disponibles y filtradas/ordenadas. Los textos se escapan para evitar fórmulas de Excel maliciosas. Un conjunto truncado nunca se etiquetará como completo.
- **Branding:** icono de mIA en la app y encabezados. El logo corporativo oficial de Sunset Beach Club se lee de `assets/branding/sunset-logo.png` si se facilita el PNG original. Como opción, la aplicación intenta descargar una única vez el PNG de `https://www.sunsetbeachclub.com/img/logo.png` y guarda una copia en la carpeta de datos de mIA; si no está disponible, aparece el nombre corporativo tipográfico (no un logo inventado).

## Pruebas de validación propuestas (Windows)

1. Cierra mIA y ábrela: comprueba que saluda por voz al terminar de cargar el avatar y vuelve a la animación idle; no debe aparecer el personaje provisional.
2. Abre Configuración > Personaje: cambia entre Pequeña / Mediana / Grande; arrástrala y verifica los límites del escritorio.
3. Activa caminar en círculo y espera aburrida y deja mIA quieta más de 30-60 segundos; realiza también una interacción para comprobar que no interrumpe una conversación. El movimiento depende de las 84 animaciones del GLB.
4. Redimensiona el bocadillo por la esquina inferior derecha, ciérralo y vuelve a abrirlo.
5. Usa «Hablar» con un mensaje en español: corrige el texto reconocido antes de pulsar Enviar. Si la precisión sigue siendo deficiente, necesitamos el motor de reconocimiento instalado y el diagnóstico de SAPI (no basta con la configuración de ElevenLabs, que sirve para emitir voz).
6. Solicita una tabla y comprueba búsqueda, ordenación, gráfico si hay categorías numéricas, vista ampliada, CSV y Excel, incluyendo la exportación de los registros filtrados.
7. Comprueba que los PDF/XLSX/CSV de los informes preexistentes del backend no han cambiado: mIA Desktop usa su propia exportación de tablas, no un segundo motor de informes documentales.

## Validación ejecutada en el entorno de desarrollo

- **32 tests Node superados**, comprobaciones de sintaxis JS y análisis CSS sin errores.
- Comprobación DOM real en Chromium headless usando datos sintéticos: se renderizaron 5 filas, 4 KPI y 5 barras; búsqueda, ordenación, vista ampliada y diseño adaptable sin desbordamiento horizontal (1240 y 670 px).
- Un archivo .xlsx generado por el exportador fue comprobado previamente con lector Excel compatible (`openpyxl`).
- **No fue posible ejecutar `npm run build` en el contenedor** por ausencia de la dependencia local `esbuild` en ese entorno; en tu equipo el comando funcionará si se conservan las dependencias instaladas. Tampoco se ha ejecutado este parche dentro de tu Windows ni con voz, GLB y backend reales.

## Notas de seguridad y limitaciones

No se incluyen tokens, contraseñas ni datos reales en el parche o las pruebas. Se emplea el backend ya existente; su respuesta determina permisos y datos. La aplicación todavía no integra todos los esquemas de presentaciones complejas del mundo 2D; solo se dibujan gráficos cuando hay columnas compatibles. La versión de voz usa reconocimiento SAPI local, independiente de ElevenLabs; para mejorar mucho la precisión será necesario evaluar un motor STT distinto posteriormente, con revisión de privacidad antes de transmitir audio a terceros.

**Reversión:** restaura los archivos originales desde tu copia de seguridad; no es necesario cambiar el GLB ni el backend.
