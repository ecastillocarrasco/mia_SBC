# mIA Desktop SBC — V0.2.4 · Conversación Glass Premium

**Instalar encima de V0.2.3**. Paquete incremental de archivos modificados o nuevos, en sus rutas originales.

## Cambios

- Superficie de conversación **glass claro** translúcida, con capa de desenfoque cuando lo soporte el compositor de Windows/Electron, marco sutil y sombras suaves. No se modifica la transparencia del avatar 3D.
- Zona de escritura **blanca sólida**: textarea, controles Enviar, Hablar y Resultados.
- Cabecera ligera, arrastrable para desplazar la ventana; botones excluidos del área de arrastre.
- Ventana sin marco con **8 zonas de redimensionamiento**: cuatro bordes, cuatro esquinas. Se conservan los límites mínimos (390 × 385), máximos (1000 × 850) y el área visible del monitor.
- **Persistencia** de anchura y altura entre sesiones mediante evento `resize` de Electron y configuración local ya existente.
- Adaptación visual desde el tamaño mínimo 390×385 hasta ventanas amplias; el historial crece según el espacio disponible.
- Sin cambios en reconocedor Windows, ElevenLabs, autenticación, backend, datos, exportaciones, logo personalizado, mundos 2D/3D/HG ni motor de informes.

## Instalación

1. Cierra mIA Desktop completamente desde el menú de la bandeja: **Salir de mIA Desktop**.
2. Haz una copia de seguridad de la carpeta `mia-desktop`.
3. Descomprime este ZIP sobre esa carpeta, respetando las rutas y sobrescribiendo únicamente los archivos presentes en el ZIP.
4. Conserva el modelo `mIA_SBC_V4_84_ANIMACIONES.glb`, `node_modules`, preferencias y logos corporativos.
5. Arranca normalmente con `npm start` (realiza el build del renderer automáticamente). **No requiere `npm install`**.

## Pruebas manuales recomendadas

1. Pulsa el atajo del teclado para abrir el chat. Confirma fondo translúcido y caja blanca.
2. Arrastra la cabecera a otra posición y confirma que no desplaza el avatar.
3. Redimensiona desde el tirador inferior derecho y después desde los otros bordes y esquinas.
4. Reduce hasta 390×385 y verifica que el historial puede desplazarse sin ocultar Enviar / Hablar.
5. Cierra y reinicia mIA Desktop: el tamaño elegido debe mantenerse.
6. Envía un prompt y abre Resultados para verificar que la integración se conserva.

## Limitación

El grado de **desenfoque real del escritorio** depende del compositor de Windows, la versión de Electron y la GPU. Si no se aplica `backdrop-filter` sobre las ventanas de otras aplicaciones, el degradado translúcido seguirá funcionando. La transparencia, resize y persistencia están validadas estática/funcionalmente; no se han ejecutado dentro de la sesión Windows del usuario.
