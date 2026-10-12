# mIA Sunset Beach Club V4.9 — Comenzar experiencia con saludo hablado

## Base y alcance

Parche incremental sobre **V4.8**. Copiar los archivos sobre la raiz del proyecto `frontend`, conservando las carpetas. Hacer copia de seguridad de los archivos originales antes de sobrescribirlos. No se cambia el GLB, el mundo 2D, el holograma, la portada ni el backend.

## Comportamiento

- El loading V4.3 conserva ilustracion original, logo SBC y porcentaje dinamico (progreso real).
- Cuando carga `scene.load()` y se prepara el audio de bienvenida, alcanza 100% y **no desaparece por si solo**.
- Aparece **Comenzar experiencia**. El click real inicia directamente la reproduccion del audio precargado con `welcomeVoice.replay(greeting)` *antes* de cualquier `await` en el controlador del click. A la vez comienza `mIA_SEQ_BIENVENIDA_SAFE` y se muestra el saludo personalizado.
- Al comenzar el sonido, el loading desaparece con transicion corta. Si `audio.play()` devuelve `NotAllowedError` u otro error, permite **Intentar de nuevo con sonido** o **Continuar sin sonido**. No queda bloqueado.
- El audio de ElevenLabs ya se solicita durante la carga del GLB (peticion ya existente). Para evitar la espera indefinida del servicio TTS, tras 8 segundos se habilita fallback a `speechSynthesis`, desde el propio click.
- No hay `element.click()` sintetico, ni microfono automatico. Se conservan los tres estados del microfono (apagado, una consulta, continuo).
- Se aplica solo al mundo **3D**. El holograma mantiene su arranque habitual, usando el mismo componente de loading pero sin exigir boton.

## Instalacion

1. Guardar copia de la version V4.8 ya instalada.
2. Descomprimir `mIA_SBC_V4_9_CONTINUAR_SALUDO_VOZ.zip` en la raiz de `frontend`, sobrescribiendo sus archivos indicados.
3. Reiniciar Vite/IIS si se requiere y recargar con `Ctrl + F5`.
4. Abrir 3D desde la portada o mediante URL directa. Esperar al 100%; debe aparecer el boton **Comenzar experiencia**.
5. Pulsar el boton: la imagen de carga se oculta y Mía hace y pronuncia su bienvenida. Comprobar que el microfono sigue apagado.
6. Comprobar el 2D, holograma, la entrada de consultas y una consulta con tabla de mas de 20 filas.

## Diagnostico y limitaciones

- `80/82` pruebas en el conjunto V4.9; **los dos fallos son preexistentes en V4.8**: `Wait milestones are honest and grow over time` y `Data and no-data paths remain distinct in 3D controller`. Las **4 pruebas nuevas V4.9** pasan.
- Sintaxis JavaScript comprobada. Build completo Vite **no comprobable aqui**: la copia disponible de `node_modules/vite` no contiene el ejecutable y no hay dependencias completas. Probar con `npm install` y `npm run build` en tu entorno habitual.
- La activacion de audio requiere un evento valido del usuario. La arquitectura es mas robusta para Chrome, pero se debe validar la salida real en el navegador del usuario. Si no puede reproducir, el boton sigue disponible para reintentar o entrar sin sonido.

## Reversion

Restaurar `src/core/boot-loader-v43.js`, `src/core/boot-loader-v43.css` y `src/worlds/3d/main.js` de la copia V4.8. No hacen falta cambios en otros archivos ni revertir el GLB.
