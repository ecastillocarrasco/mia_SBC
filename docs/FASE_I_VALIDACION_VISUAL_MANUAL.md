# Fase I — Protocolo de validación visual manual (Advanced Reporting Engine, mundo 2D real)

Este protocolo existe porque el entorno donde se ha desarrollado el Advanced Reporting Engine **no
tiene navegador gráfico ni arnés de pruebas visuales** (sin jsdom, sin Playwright/Cypress). Todas las
pruebas automatizadas de este proyecto verifican el **contrato de datos** que llega al 2D
(`/api/mia/chat` → `data.table/.cards/.charts/.alertas_calidad/.job`) y el **contenido** de los
documentos generados (texto extraído de PDF/XLSX/PPTX/HTML) — nunca su **aspecto real en pantalla**
(disposición, legibilidad, solapamientos, paginación visual). Ese es exactamente el hueco que cubre
este protocolo, pensado para que el usuario lo ejecute en su propio equipo, con resultados esperados
explícitos para cada paso — nunca una validación visual declarada superada sin evidencia real.

**Antes de empezar**: arranca el backend (`python -m mia`, o el procedimiento habitual) y el frontend
(`cd frontend && npm run dev`), con `MIA_JOBS__ENABLED=true` si quieres probar también el Job Manager
en pantalla (si no, esa sección se marca como "no probada" y punto, nunca como superada).

## A. Conversación simple (sin tarjetas)

1. Abre `http://127.0.0.1:5173/mia-2d.html` (o el puerto que indique `npm run dev`).
2. Escribe: `Hola, ¿qué tal?`
3. **Esperado**: respuesta conversacional normal, sin tabla, sin tarjetas KPI, sin gráficos. El avatar
   cambia de expresión con naturalidad.
4. ✅/❌ + captura si falla.

## B. Respuesta analítica completa (nóminas, caso de la incidencia)

1. Escribe exactamente: `Genera un informe completo de comparativa de costes en nóminas por
   departamento en agosto de 2026`
2. **Esperado**:
   - Tarjetas KPI (coste total del periodo, al menos una).
   - Al menos un gráfico (donut, barras o línea) con las etiquetas de los departamentos reales.
   - Tabla completa con todas las filas (sin paginar menos de lo que haya, con buscador si hay más de
     8 filas).
   - Si hay algún departamento con menos de 3 personas en tus datos reales: una advertencia visible de
     NOM-005, no solo en el documento.
   - Ningún solapamiento entre tarjetas/gráfico/tabla en ningún ancho de ventana (prueba también con la
     ventana del navegador estrecha, simulando móvil — sin scroll horizontal en ningún caso).
3. ✅/❌ por cada punto.

## C. Tablas extensas

1. Pide un listado con muchas filas (p. ej. `Muéstrame la plantilla completa` si tu entorno real tiene
   muchos empleados, o cualquier consulta que sepas que te devuelve un volumen grande).
2. **Esperado**: todas las filas accesibles (buscador de filtro, nunca un `...` que oculte el resto),
   scroll vertical dentro de la tabla sin romper el resto de la página, rendimiento fluido al escribir
   en el buscador (sin bloqueos perceptibles).
3. ✅/❌.

## D. Narrativa (si tu entorno la tiene activada)

1. Pide un análisis que incluya conclusiones (p. ej. añade "con tus conclusiones" a la petición de B).
2. **Esperado**: el texto narrativo se lee con naturalidad, sin HTML visible ni crudo, sin desbordar su
   contenedor.
3. ✅/❌.

## E. Job Manager — tarjeta, progreso real, cancelación, historial

*Solo si tu backend tiene `MIA_JOBS__ENABLED=true`.*

1. Escribe: `Genera en segundo plano el informe económico de nóminas de agosto de 2026`.
2. **Esperado inmediato**: aparece una tarjeta de trabajo en el propio chat con estado "En cola", una
   barra de progreso en 0%, y un botón "Cancelar trabajo".
3. Espera unos segundos sin recargar la página. **Esperado**: el estado cambia a "En curso" y luego a
   "Completado" (o "Error"/"Cancelado" si procede) SOLO, cuando el servidor lo reporte — nunca un
   avance de la barra sin que el estado real haya cambiado (abre las herramientas de desarrollador →
   pestaña Red, y confirma que hay peticiones periódicas reales a `/api/jobs/{id}`, no un simple
   `setInterval` visual sin red).
4. Cuando el estado sea "Completado": debe aparecer un enlace "↓ Descargar informe". Haz clic y
   confirma que descarga un PDF real, legible, con el logotipo de Sunset Beach Club.
5. **Recuperación tras refrescar la página**: con un trabajo en curso (lánzalo de nuevo si ya terminó
   el anterior), refresca la página (F5) ANTES de que termine. **Esperado**: al cargar, el icono de
   trabajos (📋, arriba a la derecha) muestra un contador de trabajos activos; al abrir el panel,
   el mismo trabajo aparece y su sondeo continúa (la barra sigue avanzando) sin que tuvieras que
   volver a pedirlo.
6. **Cancelación**: lanza otro trabajo y pulsa "Cancelar trabajo" mientras esté "En cola" o "En curso".
   **Esperado**: el estado cambia a "Cancelado" en pocos segundos, sin botón de descarga.
7. **Historial**: abre el panel de trabajos (📋). **Esperado**: lista de tus trabajos anteriores, cada
   uno con su propio estado y, si procede, su propio enlace de descarga — nunca los trabajos de otro
   usuario (si puedes probarlo con dos usuarios/sesiones distintas, mucho mejor).
8. ✅/❌ por cada punto (2-7).

## F. Documentos descargados — inspección visual

Descarga el informe de la petición B en los 4 formatos (puedes pedir "ahora en Excel"/"en
PowerPoint"/"en HTML" sobre el mismo resultado, o repetir la petición B añadiendo "en formato X").

Para cada uno de PDF, XLSX, PPTX, HTML, comprueba:

| Punto | Qué mirar |
|---|---|
| Logotipo | El logotipo oficial de Sunset Beach Club aparece, nítido, no distorsionado |
| Legibilidad | Texto y cifras legibles, sin solapar con el logotipo ni con tablas/gráficos |
| Espaciado | Márgenes consistentes, sin texto pegado al borde |
| Paginación (PDF/PPTX) | Sin páginas/diapositivas vacías innecesarias; los saltos de página no cortan una fila de tabla a la mitad de forma extraña |
| Gráficos | Si el informe incluye gráfico, se ve completo, con leyenda legible |
| Tablas | Columnas alineadas, cabeceras visibles, sin columnas cortadas |
| Coherencia entre formatos | Las MISMAS cifras (ya verificado por pruebas automáticas) se VEN igual de claras en los 4 — ninguno "peor" que los demás |

✅/❌ por cada fila, por cada formato (16 celdas en total si haces los 4 formatos completos).

## G. Responsive

1. Con las herramientas de desarrollador del navegador, simula un móvil (p. ej. 375×812).
2. Repite B. **Esperado**: sin scroll horizontal, tarjetas y tabla se adaptan, el panel de trabajos
   (si lo probaste en E) ocupa un ancho razonable sin desbordar la pantalla.
3. ✅/❌.

## Registro de resultados

Al terminar, pega el resultado (✅/❌ por sección, con capturas de cualquier ❌) en
`ADVANCED_REPORTING_PROGRESS.md`, sección "Fase I — validación visual", sustituyendo la nota de
"pendiente de ejecución manual" por el resultado real. Si no ejecutas alguna sección, déjala
explícitamente como "no ejecutada" — nunca como superada.
