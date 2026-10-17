# mIA Desktop SBC — V0.2.6 · Fichas personales y comandos de voz

## Instalación

Base requerida: **V0.2.5 instalada**. Cierra por completo mIA Desktop desde el icono de la bandeja (Salir), realiza una copia de seguridad de la carpeta y extrae este ZIP sobre la raíz de `mia-desktop`, respetando rutas y sobrescribiendo únicamente los archivos incluidos. Reinicia con `npm start`. No borres `node_modules`, el GLB, las preferencias de usuario ni tus recursos gráficos; no hay nuevas dependencias.

## Corrección de fichas

Ante «ficha completa Sandra Asencio», el backend debe devolver información estructurada que identifique inequívocamente a la persona. El cliente ahora:

- Primero comprueba un registro principal con identidad explícita; si coincide, **solo presenta ese registro**, no otras tablas relacionadas.
- Si llega un listado, acepta una **única** coincidencia inequívoca por nombre y apellido, y presenta exclusivamente esa fila. No copia la narración libre del backend que puede mencionar otras personas.
- Si hay cero coincidencias, varias coincidencias posibles, o no hay identidad estructurada, **no presenta datos personales**.
- En el caso de una coincidencia extraída de un listado informa expresamente de que **no se ha obtenido una ficha completa**. No afirma disponer de datos que el backend no haya enviado.

El control es **defensa de presentación**, no reemplaza la identidad/autorización en el backend; NO corrige búsquedas imprecisas ni las relaciones entre las fuentes de SBC.

## Corrección de comandos

- Los comandos «Oculta mIA» y «Cierra mIA» ahora pueden escucharse **con el bocadillo abierto**, salvo mientras el reconocimiento de dictado o la reproducción de voz mantienen el micrófono reservado.
- «Hola mIA» puede volver a mostrar el bocadillo cuando el avatar ya está visible pero el chat está oculto.
- Se admiten variantes exactas de pronunciación «mIA / Mía», además de «Oye Mía» cuando el comando principal sea «Hola mIA».
- Ajustados los silencios de detección y añadida la codificación UTF-8 con BOM del script PowerShell para Windows PowerShell 5.1.
- El cierre completo mantiene un umbral de confianza alto (0,90), evitando ejecutar un cierre por una detección dudosa.

El motor sigue siendo SAPI Windows. No se promete transcripción o respuesta inmediata: dependen del motor local y del micrófono; no sustituye un reconocedor moderno. Ninguna transcripción se envía a un proveedor externo para activar comandos.

## Diagnóstico

En «Configuración → Abrir carpeta de diagnósticos» se registrarán solamente códigos de bloqueo/selección de identidad (`MATCHED_LIST_ROW`, `PRIMARY_RECORD`, `AMBIGUOUS_EMPLOYEE`, `IDENTITY_MISMATCH`, etc.), y tiempos de arranque del reconocedor. **No se registran** nombres, preguntas, respuestas, transcripciones ni información empresarial.

Para comprobar la corrección, repite la consulta de ficha y prueba por separado las tres órdenes después de activar el reconocimiento de comandos. Si sigue fallando, comparte solo las líneas técnicas `speech_wake_ready`, `speech_process_closed`, `voice_command`, `backend_chat` y `speech_wake_failed` del log. No compartas datos de empleados.

## Pruebas realizadas

53 pruebas de Node.js superadas con **datos sintéticos**, incluida la selección única de ficha y la no divulgación de nombres ajenos en los resultados. No se ha validado sobre el Windows del usuario, la instalación real de SAPI, el backend real ni los datos de SBC. No se modifica el backend ni los mundos 2D/3D/HG.
