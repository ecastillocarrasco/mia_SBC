# mIA Desktop SBC V0.3.6 - Enlaces de informes del backend

## Correccion

La V0.3.5 no reconocia el contrato real del motor unico de informes SBC: el backend entrega un artefacto como presentacion `{ "type": "download", "format": "pdf", "url": "/api/reports/<id>" }`. Estos objetos pueden aparecer en `presentations`, en `data.presentation.items` o en `actions` (API de compatibilidad). El cliente no inspeccionaba esas estructuras y descartaba el enlace.

La V0.3.6:

- Reconoce la presentacion `type=download` en `presentations`, `actions` y contenedores anidados, sin convertir tablas en archivos.
- Puede recuperar el enlace Markdown `[PDF](/api/reports/<id>)` cuando la API de compatibilidad no expone el descriptor estructurado. No acepta enlaces externos como descarga automatica.
- Da prioridad a un documento descargable frente a un bloque de metadatos sin URL.
- Sigue validando origen, ruta API, respuesta binaria y firma PDF antes de guardar el archivo. No crea un motor ni un PDF alternativo.
- Anota solamente `report_delivery: LINK_AVAILABLE` o `LINK_MISSING` en el log, sin URL, contenido del informe, texto del usuario ni datos de empleados.

## Instalacion sobre V0.3.5

1. Cerrar mIA Desktop completamente desde la bandeja.
2. Crear copia de seguridad de la carpeta del proyecto.
3. Descomprimir el ZIP sobre la carpeta `mia-desktop`, manteniendo las rutas `src/...`.
4. Arrancar como siempre: `npm start`.
5. Pedir: `Genera un informe en PDF de gastos de agosto de 2026 por departamento` y abrir **Resultados**. Si el backend devuelve el descriptor, aparecera **Descargar documento**.
6. Si sigue apareciendo **Descarga no disponible**, consultar en los logs el evento `report_delivery` con `LINK_MISSING` y revisar si `/api/mia/v4/chat` incluye `presentations`, `actions` o un enlace Markdown. El cliente no puede construir una URL que el backend no transmite.

No hace falta reinstalar Electron, Vosk, Whisper, el modelo 3D ni tocar el motor de informes.

## Validacion

100 pruebas automaticas superadas, incluidas pruebas sintéticas de presentaciones reales (`type=download`), acciones de la API, enlaces Markdown, validación de URL, descarga GET del PDF y regresiones de la aplicación. No se ha conectado con el backend corporativo del usuario ni accedido a datos reales, por lo que la descarga desde su instancia sigue pendiente de comprobar.
