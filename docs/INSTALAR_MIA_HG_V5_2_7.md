# mIA Holograma V5.2.7 - Respuestas correctas por turno y datos verificables

## Por que se ha preparado

En la V5.2.5 la consulta "quien trabaja ahora" se enviaba primero al
endpoint `/api/mia/v4/chat` (ruta `llm`). El primer JSON 200 podia aceptarse
como respuesta aunque el numero no proviniese de fichajes/turnos. Por otra
parte, la sesion no aislaba completamente turnos de pregunta, y una pregunta
como "gracias" podia provocar una nueva consulta sobre un contexto anterior.

**No sabemos si 127 es un total de plantilla, un dato de otro periodo u otra
respuesta errada. No se puede afirmar su origen sin ver el payload real.**

## Solucion de contencion implementada

1. "Gracias", "hola" y despedidas sencillas se resuelven localmente SIN
   llamar al LLM ni al sistema de personal; no se recuperan KPIs anteriores.
2. Las preguntas sobre personal trabajando actualmente utilizan las rutas
   de backend `/api/mia/chat/stream` y `/api/mia/chat`, nunca el gateway
   generico `/api/mia/v4/chat`.
3. Los recuentos actuales no se aceptan solo por aparecer en texto, como KPI
   o bajo la clave `working_now`. Se requiere una evidencia estructurada de
   cobertura completa, fuente operativa identificada y marca temporal reciente.
4. Si el backend no entrega esa evidencia, **no se muestra ni se pronuncia un
   total**. MIA dice que no puede verificarlo y termina la espera.
5. Se heredan las protecciones de V5.2.6: una pregunta nueva cancela la vieja,
   los resultados tardios no pueden reemplazar la pregunta actual y los
   diagnosticos incluyen `turn` y `validation`.
6. La consulta de personal no transmite contexto de preguntas anteriores
   sobre correos u otros dominios al servicio operativo.
7. Se conserva la voz, el mic de tres estados, el loading y todas las
   animaciones exclusivas del holograma.

**Importante:** esta entrega garantiza que el flujo simulado no muestre un
recuento sin verificar, pero NO garantiza que el backend actual incluya la
procedencia requerida. No fabrica el total correcto. Para mostrar una cifra
veraz, necesitamos inspeccionar el esquema real de la respuesta del backend
que usa el mundo 2D o instrumentar su procedencia en el backend.

## Alcance e instalacion

Parche incremental sobre V5.2.5, que incluye las protecciones de V5.2.6.
Si ya tienes V5.2.6, tambien puedes aplicarlo encima.

1. Copia de seguridad de `frontend/src/worlds/hologram/`.
2. Extrae el ZIP en la raiz de `frontend/`, conservando carpetas.
3. Sobrescribe SOLO los archivos de `src/worlds/hologram/` incluidos.
4. Reinicia Vite/IIS y haz Ctrl+F5.
5. Abre holograma con `?diag=1`; comprueba `HG v5.2.7`.

No modifica `src/worlds/3d`, `src/worlds/2d`, `src/core`, backend ni GLB.

## Pruebas recomendadas

A. Pregunta `Quien esta trabajando ahora mismo`:
   - No debe responder "127" sin evidencia operativa.
   - Si falta procedencia, debe reconocer que no puede confirmarlo.
   - El diagnostico debe registrar `route: workforce-guard` y
     `validation: workforce-unverified` o ruta operativa validada.
B. Escribe `Gracias` tras la respuesta: respuesta de cortesia inmediata,
   `route: local-social`, sin nuevo acceso a turnos o LLM.
C. Haz otra pregunta mientras se reproduce voz: el turno anterior no debe
   reaparecer.
D. Prueba un informe no operativo: sigue usando el gateway general.

## Contrato de procedencia (propuesta, NO confirmado en backend actual)

Para mostrar automaticamente un total verificable sin depender de texto LLM,
se admite este objeto **suministrado por una fuente operativa confiable** en
la respuesta `/api/mia/chat/stream` o `/api/mia/chat`:

```json
{
  "data": {
    "provenance": {
      "source": "turnos",
      "scope": "working_now",
      "coverage": "complete",
      "as_of": "2026-10-12T02:00:00+02:00",
      "working_count": 12
    }
  }
}
```

*Los valores del ejemplo son ficticios y solo describen el formato.*
`as_of` debe ser real, fechado dentro de los ultimos 10 minutos, con zona
horaria; `coverage` debe ser completa; el total debe ser entero. Para
consultas sobre un departamento, `department` debe corresponder con el
filtro solicitado. La respuesta debe provenir del servicio de datos real:
**no permitir que el LLM fabrique el bloque `provenance`**.

Si tu API ya dispone de otra estructura de procedencia, envia su esquema
anonimizado y la adaptaremos, sin cambiar el resto de mIA.

## Diagnostico real para terminar la correccion

1. Abre F12 > Red > Fetch/XHR, con filtro `/api/mia/chat/stream`.
2. Lanza en el 2D la consulta exacta de trabajadores trabajando ahora.
3. Selecciona el evento final `result` en Response, sin nombres de empleados,
   sin tokens, sesiones ni datos personales.
4. Comparte solo la estructura de `data`, `source`, `provenance`, `context`
   (si existen), numero de registros/total e indicador de periodo.
5. Compararemos el resultado del 2D con el holograma y adaptaremos el filtro
   hasta que ambos devuelvan la misma cifra desde la misma fuente.

## Validacion realizada

- `node --check` en los JS modificados.
- 19/19 pruebas unitarias V5.2.7 aprobadas.
- Chromium simulado: respuesta falsa "127" rechazada; "gracias" genera
  una cortesia sin nuevas peticiones, no se mezcla con la respuesta previa.
- Sin test real de backend ni build Vite completo (no tenemos el proyecto
  desplegado y sus dependencias aqui).

## Reversion

Restaura los archivos del mundo holograma de tu copia de seguridad V5.2.5
(o V5.2.6). El GLB y los mundos 2D/3D no requieren reversion.
