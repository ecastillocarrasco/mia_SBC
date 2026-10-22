# mIA Desktop SBC V0.3.5 — Entrega de informes del motor único

**Instalación:** Cierra Desktop totalmente desde la bandeja, haz copia de seguridad y extrae el parche sobre la carpeta V0.3.4. Ejecuta `npm start` (recompila `dist` de manera automática). No se alteran Python, Whisper, Vosk, ElevenLabs ni el backend.

## Incidencia reproducida por captura

La consulta «informe comparativo gastos agosto 2026 entre todos los departamentos» devolvía una narración indicando «PDF listo», pero Electron no conservaba ni descargaba artefactos. La vista «Resultados» mostraba «Secciones: 6» y «Caduca en horas: 24» como KPIs incorrectos.

## Cambios

- `src/report.cjs`: adaptador de **entrega y descarga**, no motor de generación. Reconoce descriptores PDF/XLSX/PPTX/HTML en `report`, `informe`, `artifact`, `document`, `files`, `attachments` y respuestas anidadas. No inventa rutas ni archivos.
- `src/backend.cjs`: conserva el descriptor de descarga cuando exista, valida su origen y distingue solicitud de informe sin enlace.
- `src/main.cjs`: canal `mia:download-report` limitado a la ventana Resultados y al documento devuelto por la respuesta real del backend. GET solo al origen corporativo configurado, sin redirecciones; verifica la firma y limita tamaño antes de pedir guardar archivo. No genera PDF alternativo ni transfiere datos a terceros.
- `src/ui/results.*`: tarjeta «Documento generado», botón de descargar si hay URL válida, aviso inequívoco cuando no la hay. Los metadatos del artefacto se excluyen de indicadores financieros.
- `src/ui/bubble.js`: avisa explícitamente si el backend dice «listo» pero no ha enviado URL verificable.
- 12 pruebas nuevas de clasificación, seguridad, HTTP de descarga y regresión, con datos sintéticos; 92 en total.

## Comprobaciones para el usuario

1. Repite exactamente la consulta del informe PDF de agosto de 2026.
2. Si aparece «Documento disponible», pulsa **Descargar documento** y comprueba que Windows guarde el PDF real.
3. Si aparece «Descarga no disponible», Desktop aún no ha recibido un enlace utilizable. Hay que inspeccionar el contrato de respuesta de `/api/mia/v4/chat` en el backend SBC, en particular el descriptor `report`/`artifacts` y la ruta autorizada. **Esto no implica necesariamente que el archivo no exista en el backend.**
4. Verifica que «Secciones» y «Caduca en horas» ya no figuran como KPIs de gastos.

No se ha ejecutado contra la instancia real de SBC ni se han descargado informes empresariales. La prueba automatizada de descarga usa únicamente un servidor local y un PDF sintético mínimo.
