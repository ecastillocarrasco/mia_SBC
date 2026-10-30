# Orquestación inteligente y verificación

## Alcance

Se mantienen los dominios existentes, sus permisos y el enrutador determinista de
`conversation/orchestrator.py`. No se añaden dominios ni conexiones. El motor puede
ampliar las herramientas ofrecidas a partir de un plan, siempre dentro del catálogo
real autorizado para el usuario.

## Plan explícito

En consultas clasificadas como comparación, análisis o informe se exige
`planificar_tarea` antes de ejecutar herramientas. El modelo puede declarar hasta ocho pasos, con objetivos,
herramientas, dependencias y argumentos esenciales por herramienta. La planificación
no consulta fuentes ni ejecuta acciones. Se declara en una ronda separada.
La herramienta de planificación se ofrece también en consultas no clasificadas como
complejas: si el modelo la utiliza, el turno pasa por la misma verificación. Su
descripción incluye el catálogo compacto de nombres autorizados, para poder elegir
fuentes fuera del enrutamiento inicial; los esquemas se incorporan tras aceptar el plan.

Ejemplo de estructura (los nombres y argumentos deben existir en el registro real):

```json
{
  "pasos": [
    {
      "objetivo": "Consultar la plantilla de Cocina",
      "herramientas": ["plantilla"],
      "argumentos": {"plantilla": {"departamento": "Cocina"}},
      "depende_de": []
    },
    {
      "objetivo": "Exportar el resultado a Excel",
      "herramientas": ["generar_informe"],
      "argumentos": {"generar_informe": {"formato": ["xlsx"]}},
      "depende_de": [0]
    }
  ]
}
```

Las consultas simples mantienen su recorrido directo. En las complejas, omitir el
plan provoca una solicitud de corrección y, si persiste, una respuesta incompleta;
no se ejecutan herramientas antes del plan. La cobertura semántica de todos los
objetivos de una petición libre sigue necesitando la evaluación de aceptación.
Los contratos deterministas de datos, permisos y entrega se mantienen en ambos recorridos.

## Ejecución y replanteamiento

- El registro rechaza herramientas que no se hayan ofrecido en la ronda.
- El planificador agrupa pasos independientes y espera a sus dependencias antes de
  ejecutar los siguientes; las respuestas conservan los identificadores originales.
- La verificación usa ejecuciones reales con estado correcto y argumentos coincidentes,
  no las afirmaciones del modelo. Conserva el orden real de inicio de las herramientas.
- Un plan admite una revisión. No se pueden eliminar objetivos ni filtros declarados.
- Si el modelo intenta terminar con pasos pendientes, se permite una recuperación
  acotada dentro del presupuesto del turno. Solo se ofrecen consultas revisadas y
  exportación local: no envíos de correo ni cambios de agenda.
- Los pasos que no se puedan verificar se comunican como incompletos. La voz de las
  consultas planificadas se retiene hasta comprobar el resultado.
- El estado de sesión guarda `plan_ejecucion`; no se reutiliza como autorización ni
  se arrastran sus pendientes a una tarea nueva.

## Poblaciones y periodos

Una referencia a un grupo anterior inexistente no cae en el grupo más reciente. Una
población cuyo total no coincide con los identificadores conservados no se utiliza
como si fuera completa. Se reconocen referencias como «esas tres personas» sin
depender de que el modelo envíe el indicador de seguimiento.

Las preguntas generales reconocidas sobre quién trabaja ahora eliminan filtros de
departamento, franja, fecha y población que el modelo pudiera arrastrar de otra
consulta. El reconocimiento está anclado a la pregunta completa para conservar
peticiones que sí especifican un departamento.

Las comparaciones económicas de varios meses verifican el conjunto exacto de meses
contra el motor de periodos. Un mes aislado no puede presentarse como un año completo.

## Archivos y narrativa

Antes de persistir un informe se leen los bytes generados y se verifican:

- estructura de tablas y cardinalidad de series/categorías de gráficos;
- legibilidad del archivo y contenido textual de las tablas;
- asociación de las celdas de cada fila en XLSX, DOCX y PPTX, incluidos importes
  numéricos de Excel con su conversión compartida con el renderizador;
- bloqueo de hechos narrativos que citan métricas inexistentes en el resumen.

Los permisos, las guardas de narrativa y los controles de confidencialidad existentes
siguen aplicándose. Los errores de verificación no incluyen datos de las celdas.
Los archivos locales se guardan con ruta absoluta y su caducidad se calcula desde
la creación efectiva del artefacto, separada del periodo empresarial analizado.

## Límites

La ejecución correcta de una herramienta no demuestra por sí sola que se haya
interpretado toda la intención del usuario. Los filtros del plan son declarados por
el modelo; las reglas de dominio siguen siendo la autoridad sobre sus datos.

En PDF y HTML la verificación es textual: no acredita geometría visual ni la asociación
completa de filas. Las imágenes de gráficos no se vuelven a interpretar para comprobar
sus píxeles. Tampoco se certifican relaciones causales o recomendaciones de negocio.
Estas garantías requieren validación adicional, incluyendo conversaciones con el modelo
real y los datos autorizados del entorno de destino.
