# mIA SBC V4.5 — bienvenida por voz, resultados 2D/3D, gestos frontales

**Parche incremental sobre V4.4**, no reemplaza la base de 84 clips ni los mundos existentes.

## Instalación segura

1. Haz una copia de seguridad de `frontend` y del `dist` actualmente publicado.
2. Descomprime el ZIP en **la raíz del frontend**, respetando las rutas relativas.
   Se reemplazan exclusivamente los archivos incluidos en el manifiesto.
3. No apliques después parches antiguos V4.2/V4.3/V4.4 sobre este.
4. Ejecuta `npm ci`, después `npm run dev` y prueba con Ctrl+F5.
5. Solo tras validación con datos reales, ejecuta `npm run build` y publica `dist`.
6. Para revertir, restaura únicamente los archivos del manifiesto desde el backup V4.4.

No se incluyen `dist`, GLB, FBX, proyectos Blender, `node_modules` ni archivos secretos.

## A. Saludo personalizado y TTS inmediato

- **Desarrollo (`npm run dev`)**: «¡Hola Enrique! Soy Mía...».
- Para un nombre de desarrollo diferente, configura `VITE_MIA_DEV_FIRST_NAME`
  en el entorno Vite (dato público, nunca secretos ni credenciales).
- **Producción sin autenticación**: «¡Hola! Soy Mía...» sin inventar identidad.
- **Cuando se integre MSAL/Entra ID**: el adaptador lee `idTokenClaims.given_name`
  de `window.miaAuth.getActiveAccount()` o `window.msalInstance.getActiveAccount()`;
  como segundo criterio usa el primer token de `account.name`.
- La futura integración MSAL debe exponer la cuenta ACTIVA al iniciar la escena.
  Este parche **no implementa** todavía el login MSAL.
- Después de completar el loading de Mía, se intenta llamar inmediatamente al
  endpoint de voz `/api/voice/stream`; **no espera una pregunta**.
- Si la política de reproducción automática del navegador bloquea el audio,
  aparece «Escuchar saludo» para permitir la reproducción con un clic.
- Si el visitante consulta mientras se descarga la voz, se cancela el TTS
  pendiente para evitar saludos tardíos sobre la respuesta.
- El reconocimiento por micrófono V4.4 permanece inalterado: apagado al inicio,
  una consulta, continuo, apagado. **El saludo TTS NO activa el micrófono**.

## B. Personal trabajando ahora: paridad de renderizado

Se confirma en el código: 2D y 3D utilizan el mismo `MiaClient`, el endpoint
`/api/chat/stream` y el `session_id` del navegador. No hay ningún filtro
frontal explícito de `Mantenimiento` en el 3D. En cambio:

- El 2D muestra los campos de tabla `kpis`, `charts` y `stats`, además de `rows`;
  el 3D omitía esos extras al representar el mismo `presentation.type="table"`.
- El 2D renderiza tablas Markdown presentes solo en el texto `answer`; el 3D
  trataba ese texto como un caption enorme, sin tabla ni paginación.

En V4.5 el 3D incluye ambos caminos y mantiene la paginación de 20 filas.
Añade un contador «N registros recibidos» tomado SOLO de los datos reales.
En modo desarrollo se registra en consola la estructura: cantidad de tablas,
filas y presentaciones, **sin registrar empleados ni datos personales**.

**Límite de la corrección:** si el backend devuelve exclusivamente empleados de
Mantenimiento, el frontend no puede mostrar otros departamentos inexistentes en
la respuesta. Ante un caso persistente, comparar en DevTools los eventos SSE
`result` de 2D y 3D, con la misma pregunta, sesión nueva y periodo/hora,
SIN adjuntar nombres ni datos personales. Verificar origen del filtro en backend.

## C. Presentaciones y animaciones de señalar

Se inspeccionó el GLB original de 84 clips. `mIA_POINT` no presenta un giro
significativo en el hueso `smartrig:Hips`; el aspecto ladeado puede estar
asociado a los gestos superiores, el encadenado y el encuadre.

Para `data`, `list`, `person`, `employee360` y `shifts`, V4.5 usa:

1. `mIA_IDLE_SAFE` como base frontal de cadera/pies.
2. `mIA_POINT` en la capa superior `Spine/Shoulders/Arms` mediante `playGesture`.
3. Gesto de hablar alternado sobre esa misma base.

Así no se fuerza la rotación general del personaje ni se distorsionan los clips
para caminar. Las secuencias originales para KPIs, comparativas e informes
se conservan. Si un clip sigue ladeado en WebGL, hay que identificar su nombre
y tiempo exacto para crear una variante corregida en Blender o retocar su
postura superior de manera selectiva, sin modificar el modelo validado.

## Validación

- 12 pruebas automáticas (`node --test tests/mia-v45.test.mjs`).
- Sintaxis de módulos JS modificados (`node --check`), OK.
- CSS analizado sin errores de sintaxis.
- `mIA_POINT` y otras rotaciones de huesos inspeccionadas en el GLB REAL.
- Prueba browser con servidor de desarrollo: **pendiente** (el entorno de
  evaluación bloquea Chromium hacia localhost).
- `npm run build`: **pendiente**, porque la instalación de Vite/npm no terminó
  en el entorno de preparación.
- Autoplay real de audio, interfaz WebGL y consultas de personal: **pendiente en
  la máquina del usuario**. No marcar como superado hasta probarlo.

## Pruebas manuales sugeridas

1. `npm run dev`, entrar al 3D: «¡Hola Enrique!» con intento de voz automático.
2. Sin tocar micrófono: debe seguir apagado. Probar ciclo manual V4.4.
3. Terminar saludo y verificar paso a `IDLE_SAFE`.
4. Probar `POINT`/`SENALAR_PANTALLA` sobre tabla de empleados: pies de frente.
5. Preguntar «¿Quién está trabajando ahora mismo?» con sesión nueva.
   Verificar en consola conteos de la estructura recibida.
6. Comparar con el 2D en sesión equivalente, sin filtros heredados.
7. Simular respuesta Markdown con tabla de 43 filas; comprobar 20/20/3.
8. Probar persona/Employee360, KPI, comparativa e informe completos.
9. Probar holograma: saludo individual, voz y panel resumen, sin cambios al micrófono.

