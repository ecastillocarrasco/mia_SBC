# mIA Desktop SBC — Prototipo funcional V0.1

**Objetivo:** validar la cuarta interfaz de mIA en un PC con Windows sin tocar ninguno de los mundos web, la configuracion del backend ni el motor unico de informes. Incluye codigo fuente nuevo, independiente.

## Funciones implementadas

- Proceso residente en la bandeja del sistema, con menu `Mostrar mIA`, `Escribir a mIA`, `Ocultar`, `Configuracion` y `Salir`.
- Ventana de avatar **transparente, sin bordes y sin fondo**, posicionada inicialmente encima de la barra de tareas; configurable como siempre visible.
- Movimiento del personaje con el raton, clic para abrir un **bocadillo flotante**, y clic a traves de partes de la ventana sin personaje (prueba por hit-testing del modelo 3D).
- Atajo global por defecto `Ctrl+Alt+M` en Windows; configurable en la pantalla de opciones. Un primer uso muestra mIA si esta oculta; el siguiente abre el bocadillo.
- Animaciones del GLB original si existen clips compatibles (`mIA_IDLE`, `mIA_GREET`; en caso contrario toma el primer clip).
- Selector para importar una copia local del GLB original, hasta 200 MB, verificando su cabecera. Busca automaticamente `assets/mIA_SBC_V4_84_ANIMACIONES.glb` si se coloca en la carpeta del proyecto.
- Ajustes de tamaño, visibilidad e inicio automatico al acceder a Windows.
- Ventana de demostracion de resultados preparada con tarjetas y espacio de grafico, **sin cifras empresariales inventadas**.
- Ventanas protegidas con aislamiento de contextos, sin Node.js en los renderizadores y sin permisos de microfono.

## Limites de esta entrega: fase 1

- **El GLB original no esta incluido**: el archivo no se ha podido recuperar en esta sesion. Hasta importarlo se muestra una **figura vectorial provisional**, expresamente etiquetada como tal. No es la mIA original.
- **La conversacion todavia no consulta el backend SBC**. Las respuestas del bocadillo se identifican claramente como prueba local; no se envian datos reales ni credenciales fuera del equipo.
- **La frase de activacion por voz no esta implementada**; se reserva para fase 2, con deteccion local y permiso explicito de microfono. ElevenLabs no se ha conectado en este prototipo.
- El motor de informes y los paneles reales tampoco estan integrados: la ventana de resultados es una maqueta funcional vacia.
- No se ha generado un instalador `.exe` en este entorno, porque aqui no existe acceso de npm al registro de paquetes. Se entregan los fuentes y los scripts de instalacion/paquetizacion para compilar en Windows.
- **No se ha ejecutado en un escritorio Windows real**; el comportamiento de transparencia, alpha/hit testing y bandeja debe comprobarse alli.

## Instalar y probar en Windows 10/11

1. Extrae el ZIP en una carpeta local independiente, p. ej. `C:\mIA\mia-desktop\`.
2. Instala **Node.js LTS** (si no esta instalado).
3. Ejecuta `INICIAR_MIA_DESKTOP.cmd` (primera ejecucion: descarga dependencias de npm y compila el renderizador local con esbuild). Otra opcion es abrir PowerShell en esa carpeta y ejecutar:

   ```powershell
   npm install
   npm start
   ```

4. Aparecera la figura provisional sobre la barra de tareas y el icono `m` en la bandeja.
5. Haz clic derecho en el icono de bandeja y abre **Configuracion**; en «Personaje 3D» selecciona el **GLB real `mIA_SBC_V4_84_ANIMACIONES.glb`** desde el frontend existente o tu carpeta de modelos. Este proceso **copia** el archivo, no altera el original.
6. Haz clic sobre mIA para abrir el bocadillo, escribe un mensaje y confirma que la respuesta indica «prueba local».
7. Manten pulsado y arrastra el personaje por la pantalla.
8. Prueba el atajo `Ctrl+Alt+M`, el menu de bandeja y `Vista de resultados`.
9. Cambia tamaño, atajo y autoarranque desde Configuracion; luego reinicia para comprobar persistencia.
10. Cierra mIA desde el menu **Salir de mIA Desktop**.

## Compilar instalador Windows (opcional)

Despues de `npm install`:

```powershell
npm run package:win
```

El instalador NSIS quedara en `release/`, separada de `dist/` (archivos del renderizador). Este script sirve para desarrollo; antes de distribuir a empleados debe firmarse el ejecutable, revisar politica de autoactualizaciones y pasar pruebas de antivirus/ciberseguridad.

## Estructura

```
mia-desktop/
  INICIAR_MIA_DESKTOP.cmd
  package.json
  src/
    main.cjs            # proceso Windows, bandeja, atajos y ventanas
    preload.cjs         # IPC restringida por ventana
    config.cjs          # validaciones y preferencias
    ui/                 # avatar, bocadillo, ajustes, resultados
  assets/
    tray.png            # icono provisional de bandeja
  scripts/
    build.mjs           # compila JavaScript del renderizador
  tests/
    config.test.cjs
```

## Integracion real con el backend SBC (siguiente fase)

La aplicacion actualmente **no dispone de las rutas autenticadas ni el contrato de datos del frontend en esta sesion**. Cuando se integre el codigo real se adaptara el bocadillo para utilizar el cliente/API ya existente, recuperar sesiones de forma segura y respetar privacidad y permisos. **No se deben incorporar tokens o claves a archivos JS ni al instalador.**

El proyecto esta separado y no sobrescribe `frontend/src/worlds/2d`, `frontend/src/worlds/3d`, `frontend/src/worlds/hologram` ni `src/mia`.
