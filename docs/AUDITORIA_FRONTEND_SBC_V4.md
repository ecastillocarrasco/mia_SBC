# mIA Sunset Beach Club — Auditoría de rutas y duplicados (11/10/2026)

## Alcance y nivel de certeza

Fuentes revisadas: `mIA_FRONTEND_CODIGO.zip`, `inventario_public.csv` (192 rutas) e `inventario_dist.csv` (213 rutas).
Se analizaron las importaciones del código de `src`, los HTML de entrada y la configuración `vite.config.js`.
Los CSV contienen rutas, tamaños y fechas, pero **no hashes de los binarios**. Dos archivos con la misma longitud no están certificados como idénticos.
El paquete de código excluye gran parte de los binarios, por lo que no es posible auditar su contenido ni determinar si existen referencias desde HTML externos, IIS o servicios ajenos a este frontend.

## Inventario medido

| Lugar | Inventariado | Tamaño |
| --- | ---: | ---: |
| `public` | 192 archivos | ~2.41 GiB |
| `public/assets/blender` | 117 archivos | ~2,228 MiB |
| `public/assets/rigs` | 28 archivos | ~126 MiB |
| `public/assets/meshy` | 3 archivos | ~85 MiB |
| `public/models` | 2 archivos | ~21.7 MiB (GLB antiguos) |
| `public/assets/avatar` | 18 archivos | ~4.3 MiB |
| `public/mia-assets/avatar` | 16 archivos | ~4.3 MiB |
| `dist` | 213 archivos | ~2.16 GiB |
| `dist/assets/blender` | 121 archivos | ~1,933 MiB |
| `dist/assets/rigs` | 28 archivos | ~126 MiB |
| `dist/assets/meshy` | 3 archivos | ~85 MiB |
| `dist/models` | 3 archivos | ~59.4 MiB |

Los inventarios tienen 181 rutas relativas presentes en ambos árboles, todas con **igual longitud**, coherente con la copia habitual de `public` a `dist` realizada por Vite. No se afirma identidad binaria sin SHA-256.

## Uso del código

- `vite.config.js` construye: `index.html`, `mia-2d.html`, `src/worlds/3d/index.html`, `mia-3d.html` (legacy), `src/worlds/hologram/index.html`.
- El mundo 3D real se inicia desde `src/worlds/3d/main.js` e importa `src/core/scene.js`, `src/core/present.js`, `src/core/employee360-presentation.js` y más.
- El holograma arranca desde `src/worlds/hologram/main.js` y comparte el motor `MiaScene`.
- La pantalla 2D consume rutas `/mia-assets/avatar/*`; `src/core/avatar.js` referencia `/assets/avatar/*`. **Mantener ambas rutas por ahora**, aunque sus nombres/tamaños sugieren redundancia.
- `src/main.js` y `src/style.css` pertenecen a la entrada heredada de `mia-3d.html`, que antes era una plantilla genérica. **La nueva versión cambia ese HTML a una redirección segura hacia el mundo 3D actual**. Mantener el código viejo fuera de producción en lugar de borrarlo sin tests externos.
- `src/counter.js` contiene únicamente un contador de ejemplo Vite. No aparece importado por las entradas actuales: candidato a eliminación tras revisión final.
- `src/worlds/hologram/main - copia.js` no aparece importado: candidato a mover a respaldo privado.
- `dist` es un PRODUCTO DE COMPILACIÓN. No se deben editar archivos con hashes ni eliminar `dist` en caliente en IIS.
- `public/models/mIA_WEB.glb` (11 MiB) es el modelo antiguo cargado por `src/core/scene.js` y por el legacy `src/main.js`. En este parche `scene.js` apunta a `public/models/mIA_SBC_V4_84_ANIMACIONES.glb`; conservar temporalmente el anterior durante el rollback.
- `public/models/mIA_WEB_old.glb` (10.7 MiB) está como copia antigua; candidato a archivar tras validar el nuevo despliegue.
- `dist/models/mIA_SBC_V4_84_ANIMACIONES.glb` ya figura en el inventario, pero **no** consta en `public/models` del mismo inventario. Este paquete entrega el GLB canonizado en `public/models` para impedir que un nuevo `npm run build` lo pierda.

## Clasificación de limpieza

### Trasladar fuera de la web (NO borrar el material original)

| Carpeta | Motivo |
| --- | --- |
| `public/assets/blender` | Proyectos `.blend`, backups `.blend1`, scripts, ZIP de animaciones y GLB de desarrollo. No los importa el runtime 3D/HG/2D según `src` revisado. |
| `public/assets/rigs` | FBX de Blender/Mixamo, no recursos web de producción. |
| `public/assets/meshy` | Versiones intermedias de generación de modelo, no recursos web de producción. |

Mover a `frontend/_MIA_ASSETS_FUENTE_ARCHIVO` (fuera de `public`) tras verificar respaldo, usando el script reversible adjunto. Conservar de manera independiente los maestros críticos `.blend`, `.fbx`, ZIP y los informes.

### Mantener

`src`, `public/mia-assets`, `public/assets/avatar`, `public/favicon.svg`, `public/icons.svg`, `public/models/mIA_SBC_V4_84_ANIMACIONES.glb`, `package.json`, `package-lock.json`, `vite.config.js` y todos los HTML activos. Dejar `dist` intacto hasta hacer build y publicar la siguiente versión.

### Archivar después de pruebas de regresión

`src/counter.js`, `src/worlds/hologram/main - copia.js`, `src/main.js` y `src/style.css` legado (si no existen referencias externas), `public/models/mIA_WEB_old.glb` y `public/models/mIA_WEB.glb` (cuando no se necesite rollback).

## Riesgos detectados y corregidos en la rama nueva

1. Modelo de 24 clips en `scene.js` sustituido por GLB con 84 clips; corrección del prefijo `import.meta.env.BASE_URL` para IIS bajo `/mia/`.
2. El controlador V2 contiene nombres que no existen en el nuevo GLB (`mIA_YES`, `mIA_HAPPY`, `mIA_IDLE_STANDING`). El nuevo director `behavior-v4.js` sólo utiliza clips reales y permite variar esperas.
3. El renderer genérico limitaba tablas a 100 filas; se elimina el recorte. `premium-tables.js` permite acceder a todas con **20 filas máximo visibles** y búsqueda/paginación/exportación CSV.
4. HTML `mia-3d.html` legado redirige al mundo 3D principal; no se borra la ruta.
5. Los resultados conversacionales sin información estructurada ya no deben abrir un panel 3D/HG; la voz/subtítulo permanece.
6. Employee360 y estadísticas siguen utilizando los renderizadores validados, con nueva superficie amplia. Acciones rápidas Employee360 conectadas a consulta de backend.
7. El mundo 3D representa resultados completos; HG utiliza `hologram-brief.js` para **máximo cuatro KPI, cinco filas resumidas y dos enlaces a informes**.
8. Se ignora la vigilancia en carpetas grandes de trabajo dentro del servidor Vite durante la transición, hasta sacar los binarios de `public`.

## Limitaciones de esta auditoría

- No se han leído ajustes de IIS, reglas rewrite, CDNs ni plantillas servidas fuera del repositorio.
- No se ha ejecutado `npm run build` con `three` y `vite` reales en este entorno: la instalación offline no tenía paquetes en caché y la instalación en línea no se completó.
- No hay ensayo de web real con backend privado ni comprobación WebGL en Chrome Windows.
- No se han borrado ni modificado los binarios originales de tu equipo.

## Orden de validación

1. Guardar copia del frontend actual y del `dist` desplegado.
2. Superponer únicamente los archivos modificados de este paquete en una copia del proyecto.
3. `npm ci`, `npm run dev`, validar rutas 2D/3D/HG y 84 clips.
4. Probar consultas: solo conversación, tabla de 43 filas, ficha Employee360 con botones, informe descargable, KPIs y consulta prolongada.
5. `npm run build` en un directorio de pruebas; verificar `dist/models/mIA_SBC_V4_84_ANIMACIONES.glb` y las rutas bajo `/mia/`.
6. Publicar con rollback disponible.
7. Solo entonces trasladar activos de Blender/rigs/Meshy fuera de `public` mediante script (sin borrarlos).
8. Reconstruir/publicar un `dist` limpio, comprobando que no vuelva a incluir GB de archivos fuente.
