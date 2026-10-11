# mIA V4 — Parche 3D + holograma (84 animaciones)

## Contenido

El ZIP incluye **solo archivos nuevos o modificados**, preservando los directorios actuales, más el GLB nuevo dentro de `public/models`. No contiene `dist`, dependencias npm ni archivos del mundo 2D.

## Instalación segura

1. Respaldar `frontend` y `dist` actuales; probar primero en una copia de trabajo.
2. Extraer este ZIP sobre la raíz `frontend` de la copia, manteniendo exactamente la estructura `src`, `public`, etc. Aceptar sobrescritura de estos archivos únicamente en la copia.
3. Verificar la existencia de `public/models/mIA_SBC_V4_84_ANIMACIONES.glb` (39,562,116 bytes).
4. En PowerShell desde la raíz: `npm ci` y `npm run dev`.
5. Abrir `http://127.0.0.1:5173/` (portada), mundo 3D y holograma.
6. Verificar Console del navegador: no deben verse errores de GLTFLoader o de shaders.
7. Tras pruebas, `npm run build` en la copia de desarrollo. La compilación debe copiar el GLB al `dist/models/` y respetar `base: /mia/`.
8. Desplegar en IIS con respaldo de la versión previa y comprobar desde la URL publicada `/mia/`.

## Contratos protegidos

- No cambia JS ni CSS del mundo 2D.
- No reemplaza `employee360-presentation.js`, `statistical-visuals.js`, `client.js` ni los endpoints del backend.
- Solo toca la infraestructura compartida necesaria para cambiar el GLB (`scene.js`), el renderer genérico (`present.js`, antes truncaba filas) y añade controladores V4.
- No genera informes ficticios ni botones simulados. Los documentos y enlaces proceden únicamente del backend.
- Los informes Excel/PDF sólo se muestran si el backend proporciona URL real. La capacidad de crear un nuevo informe sigue dependiendo del backend.
- Si una respuesta trae datos estructurados: panel grande y visualización. Si no: la voz/subtítulo sin ventana de resultados.
- Paginación: 20 filas máximo por tabla visible; filtro en cliente, CSV de todas las filas filtradas.
- HG prioriza cuatro métricas, cinco filas de resumen y hasta dos documentos. El resto está accesible en 3D.

## Pruebas funcionales mínimas (datos reales/autorizados o sintéticos)

1. **Conversación simple**: «Hola Mía» → ningún panel ni ficha, solo voz/subtítulo.
2. **Consulta sin resultados** → no abrir una tabla vacía.
3. **Tabla con 43 filas** → página 1: 20; página 2: 20; página 3: 3; búsqueda; CSV 43 registros.
4. **Employee360** → tarjeta ancha, KPIs, secciones y acciones rápidas navegables.
5. **Comparativas** → presentación analítica sin recortar todas las filas.
6. **Consulta larga** → Mía alterna pensar/consultar/trabajar mientras recibe progresos.
7. **Informe PDF/Excel** → mostrar enlace real, cambio contextual de animación.
8. **3D** → `mIA_SEQ_BIENVENIDA`, `mIA_SEQ_PRESENTAR_KPI`, `mIA_SEQ_CAMINAR_Y_GIRAR` y `mIA_TALK`, sin deformación.
9. **Holograma** → avatar cian visible, KPIs y breve análisis; no volcar detalles Employee360 completos.
10. **IIS** → rutas `/mia/models/...`, navegación y voz/backend correctos bajo subdirectorio.
11. **Móvil** → sin desbordamiento horizontal de página, ventana de resultados adaptable.
12. **Voz fallida** → fallback existente del navegador, sin pérdida de consulta.

## Límites conocidos antes de producción

- El tamaño GLB de ~39.6 MB puede afectar dispositivos de baja memoria. Evaluar optimización y caché HTTP tras pruebas de fidelidad.
- `inPlace()` deja en su lugar los movimientos de cadera horizontales para evitar que Mía salga de escena; es una decisión de puesta en escena, no navegación física por colisiones.
- El shader de HG se mantiene deliberadamente compatible con la versión anterior y tiene fallback básico; debe validarse con la GPU y la pantalla/ventilador reales.
- Las 84 animaciones están auditadas estructuralmente pero los gestos deben probarse en navegador con los resultados backend reales.
- La capa de conversación no promete sincronización labial facial: el GLB incorpora shape keys de ajustes, no una biblioteca de visemas validada.

## Volver a la versión anterior

Restaurar backup de frontend/dist; no eliminar todavía `public/models/mIA_WEB.glb`. Los archivos Blender originales se mantienen en carpeta privada y pueden volver a copiarse si fuera necesario.

## IIS: GLB grande bajo /mia/

Si IIS devuelve `404.3` para `/mia/models/mIA_SBC_V4_84_ANIMACIONES.glb`, habilitar el tipo MIME `.glb` -> `model/gltf-binary` (o `application/octet-stream`) en la configuración de ese sitio, y comprobar el acceso HTTP. No es necesario añadir `.blend`, `.fbx` ni `.zip` al sitio web. Validar que el fichero se sirve correctamente y que se cachea mediante HTTP para evitar descargar ~40 MB en cada visita.
