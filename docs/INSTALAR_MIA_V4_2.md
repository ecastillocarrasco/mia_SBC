# mIA SBC V4.2 — Editorial, texto y espera inteligente

Parche **incremental sobre V4.1 White Studio + Voice First**, compatible con el
parche V4 de 84 animaciones. Se mantiene el GLB original. No actualiza el mundo 2D.

## Instalación

1. Haz copia completa del frontend actual y conserva V4.1 para rollback.
2. Extrae el ZIP de V4.2 **en la raíz `frontend/`** con su misma estructura.
   Autoriza sobrescribir solamente los ficheros incluidos.
3. No vuelvas a aplicar un parche V4/V4.1 antiguo por encima de V4.2.
4. Ejecuta desde `frontend/`:
   ```
   npm ci
   npm run dev
   ```
5. Abre el selector de mundos; entra en **3D** y después **Holograma**.
6. Valida la funcionalidad y el render WebGL en tu navegador. Solo entonces
   ejecuta `npm run build` para generar `dist/`.
7. Publica `dist` en IIS mediante tu procedimiento habitual, conservando backup.

**No elimines ni sobreescribas** el GLB `public/models/mIA_SBC_V4_84_ANIMACIONES.glb`.
El parche NO lo incluye. Debe contener 84 clips.

## Cambios V4.2

### 3D
- El micrófono y cualquier dictado se DESACTIVAN. No se solicita permiso.
- Botón discreto de escritura: abre el compositor por clic o tecla imprimible.
- TTS de salida conservado, con control separado para silenciarlo.
- Bienvenida automática tras cargar la escena, una sola vez por carga:
  «¡Hola! Soy Mía, tu asistente virtual. ... ¿Qué te gustaría saber?».
  Reproduce `mIA_SEQ_BIENVENIDA` y, al terminar, pasa a reposo.
- Nueva animación runtime `mIA_IDLE_SAFE`: tramo inicial de `mIA_IDLE`,
  cortado antes de su gesto final. **No modifica el GLB**.
- Se retira `mIA_WEIGHT_SHIFT` del ciclo automático de reposo y se evitan
  clips excesivamente girados por rotación de cadera para ciclo automático;
  los clips originales siguen disponibles.
- Mensajes narrativos con entrada tipográfica editorial, sin tarjetas
  cuando NO hay datos estructurados.
- Para respuestas con datos, introducción narrativa y panel premium existente.
- Mantiene paginación de máximo 20 filas, fichas Employee360, KPIs e informes.
- Esperas: comentarios naturales visibles y transiciones de animación.
- Fondo blanco puro y sin doble plano de color. Sombra e iluminación de volumen.

### Holograma
- Dictado y botón micrófono retirados; TTS de salida conservado.
- Misma bienvenida, estado idle seguro y mensajes naturales de progreso.
- Transición suave de caption; mantiene su resumen de KPI/analítica,
  sin convertirlo en una ficha detallada del mundo 3D.
- Preserva presentación específica mientras se reproduce el audio
  (antes se sustituía indebidamente por `speaking` genérico).

### Estados internos ocultos
`analisis_financiero` -> «Estamos tramitando tu solicitud.»
`consultando_sql` -> «Estoy consultando la información que necesitas.»
`generando_informe` -> «Estoy preparando el informe solicitado.»
Las frases naturales del backend se conservan, pero los códigos,
rutas, trazas y nombres de herramientas no se muestran.

## Pruebas

- `node --test tests/mia-v42.test.mjs`
- 11 pruebas automáticas superadas en entorno aislado:
  texto natural, esperas, progresos del backend, XSS vía texto,
  bienvenida y animaciones, micrófono inactivo en ambos mundos,
  fondo blanco, TTS y paginación.
- `node --check` en todos los JS modificados y nuevo módulos: correcto.
- Analizador CSS: sin errores sintácticos.

**Pendientes en tu entorno**: build Vite completo, aspecto WebGL real,
crossfades y gestos sobre tu GPU, conexión al backend, permisos de TTS,
Employee360 con datos reales y navegación IIS bajo `/mia/`.

No se pudo ejecutar `npm ci` en el entorno de preparación por no disponer
de la descarga Vite en caché offline. No se declara `npm run build` validado.

## Lista rápida de pruebas manuales

1. Cargar 3D: saludo tipográfico y `mIA_SEQ_BIENVENIDA`.
2. Al acabar (~9,4 s): vuelve a `mIA_IDLE_SAFE`, sin tirón al final.
3. No debe verse micrófono, ni solicitar permiso para grabar.
4. Abrir el campo de consulta con tecla, clic, o botón de escribir.
5. Consultar «Hola»: respuesta tipográfica sin panel de datos.
6. Provocar progreso `analisis_financiero`: mostrar «Estamos tramitando...».
7. Simular 8, 19, 36 y 66 segundos: mensajes y gestos de espera.
8. Consultar ficha, KPI, comparativa, informe: panel amplio y animación contextual.
9. Tabla de 43 registros: 20 / 20 / 3, búsqueda y exportación.
10. Verificar holograma: resumen ejecutivo, sin micrófono y con TTS.
11. Probar orientación frontal y ciclos de reposo. Si otro clip gira demasiado,
    identificarlo para afinar la selección sin editar el esqueleto.

## Cómo volver atrás (rollback)

Si tienes control de versiones, revierte solo las rutas del manifiesto.
De lo contrario, restaura esas mismas rutas desde el backup V4.1.
NO borres el GLB ni restaures el mundo 2D.
Repite `npm run dev` y prueba antes de volver a compilar o publicar.
