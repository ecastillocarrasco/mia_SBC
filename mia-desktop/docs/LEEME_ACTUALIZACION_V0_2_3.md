# mIA Desktop SBC V0.2.3 — Diagnóstico de voz y marcas

Esta actualización se aplica **encima de V0.2.2**, manteniendo el backend SBC y los mundos web intactos.

## Cambios

- Corregida la construcción de UTF-8 en el script de Windows PowerShell 5.1 y la captura del resultado cuando el proceso se cierra antes de responder. El problema de reconocimiento puede persistir si Windows no dispone de un reconocedor SAPI español es-ES; el diagnóstico permite distinguirlo.
- Añadido **Configuración > Diagnosticar voz**, con los motores de reconocimiento SAPI disponibles. No activa el micrófono en este chequeo.
- Registro técnico local JSONL: errores de voz, inicialización, UI, carga de avatar y estado de llamadas backend. **No se guardan** grabaciones, frases, transcripciones, prompts, respuestas, tokens ni valores de nóminas.
- **Configuración > Abrir carpeta de diagnósticos**: carpeta `%APPDATA%/mia-desktop-sbc/logs` o la que devuelva `app.getPath('userData')` en la instalación concreta.
- Sustituida la marca provisional «m» por la firma tipográfica **mIA**. Se puede elegir **Seleccionar logotipo mIA (PNG)** para instalar el recurso corporativo original, que no venía incluido en la base.
- Logotipo de Sunset Beach Club con dimensiones más pequeñas, menor intensidad y `object-fit: contain` en las cabeceras de conversación, configuración y resultados. No se modifican recursos originales SBC.
- Actualizado el icono por defecto de la aplicación/bandeja para que muestre «mIA».

## Instalar

1. Cierra mIA Desktop desde su icono de bandeja > **Salir de mIA Desktop**.
2. Haz una copia de seguridad de la carpeta actual.
3. Extrae el ZIP sobre la raíz de `mia-desktop`, aceptando los archivos incluidos.
4. No borres `node_modules`, el GLB original ni tu configuración.
5. Ejecuta `npm start`.
6. En **Configuración > Diagnosticar voz**, comprueba si aparece un motor `es-ES`.
7. Pulsa **Hablar**; si falla, abre la carpeta de diagnósticos. Comparte el mensaje de error y, si lo deseas, el último `.jsonl` después de revisarlo.

**Nota:** el icono de la aplicación en la barra de tareas puede permanecer en caché de Windows mientras se ejecuta desde el proyecto. El cambio al EXE del instalador requiere volver a generar el ejecutable firmado.

**Privacidad:** los registros sólo contienen eventos, códigos técnicos, estado HTTP y duración. No contienen texto de consultas ni contenidos empresariales. Aun así, revisa los archivos antes de compartirlos.

## Limitaciones y siguiente paso

No es posible verificar aquí la presencia real de reconocedores SAPI ni el acceso a micrófono en Windows. Si no hay motor compatible, la solución no consiste en reinstalar Electron: habrá que instalar uno o integrar otra tecnología de reconocimiento local, bajo configuración explícita. La voz ElevenLabs de salida ya es independiente del reconocimiento de voz de entrada.
