# Orquestación inteligente y verificación

## Alcance

La arquitectura es híbrida. El modelo propone el plan y redacta la explicación;
el motor local autoriza las herramientas, ejecuta los cálculos y comprueba la
evidencia y los archivos. Un plan del modelo nunca concede permisos. Se conserva
el proveedor inyectado y el Privacy Gateway existente; no se introduce otro camino
de salida ni un segundo proveedor para las verificaciones.

### Frontera de privacidad

La fábrica rechaza proveedores externos sin protección explícita, fallo cerrado y
clave de vault. El proveedor corporativo no ofrece búsqueda web implícita: una
búsqueda pública requeriría un recorrido separado con contexto minimizado. Los
diagnósticos enmascaran por defecto también en dev: omiten consultas, respuestas,
argumentos, excepciones de negocio, metadatos libres y etiquetas del grafo; conservan
solo contadores operativos y símbolos del backend. El cambio se aplica al reiniciar;
no modifica retrospectivamente trazas o archivos de diagnóstico existentes.

Los identificadores declarados en JSON se seudonimizan por contrato aunque el detector
estadístico no reconozca el nombre. Los valores individuales reconocidos, incluidos
importes anidados de nóminas, se reservan localmente en todas las políticas. Los cuerpos,
extractos, asuntos, evidencias y contenido documental de los campos conocidos no se
remiten al modelo; los registros médicos reconocidos se reservan completos. Las tablas
y archivos autorizados conservan los datos originales. Los informes individuales no
solicitan narrativa externa; los agregados minimizan antes de aplanar las métricas.

Los embeddings requieren una finalidad declarada por el código: consulta o proyección
minimizada. Un documento privado o un envío sin clasificación se bloquea antes del
proveedor. Nóminas usa la proyección de vocabulario cerrado existente. La NUEVA indexación
externa de CVs y documentos firmados queda bloqueada hasta disponer de una proyección
aprobada o embeddings locales. No se borran ni recalculan índices previos. Su calidad
de recuperación y tratamiento histórico no quedan certificados por estos cambios.

Seudonimizar texto mediante detección no demuestra anonimización completa ni impide
inferencias por contexto. El texto libre del usuario y los campos no tipados necesitan
la revisión restante de la frontera de salida: las pruebas de campos conocidos no
demuestran ausencia universal de datos sensibles. Tampoco un proveedor ejecutado por
una API externa se convierte en local por estar detrás del gateway. La ubicación,
retención y condiciones del despliegue requieren comprobación independiente.

### Aceptación

La suite comprueba el perfil contra los permisos efectivos devueltos por `/api/auth/me`
antes de consultar fuentes. No usa nombres de cuentas ni claims decodificados sin
verificar. Un perfil incorrecto impide empezar. Los casos sin identidad siguen pendientes;
los casos con revisión empresarial pendiente no pasan por superar comprobaciones técnicas.
La espera SSE admite hasta 660 segundos de inactividad para las herramientas existentes
de hasta 600 segundos. El presupuesto de razonamiento incluye la latencia del modelo;
el tiempo de un lote compuesto exclusivamente por lecturas revisadas o exportación local
se mide una sola vez y se descuenta de ese presupuesto. Cada herramienta conserva su
timeout y las rondas mantienen su límite. Escrituras, herramientas nuevas y lotes mixtos
no reciben ese descuento. Esto permite consultar el segundo año después de una lectura
larga; no demuestra por sí solo que los datos de ambos años sean completos o correctos.

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

Los filtros declarados se validan y normalizan contra los modelos de parámetros del
catálogo autorizado. Se rechazan campos o valores ajenos al contrato. La comprobación
de ejecuciones considera las conversiones y valores predeterminados reales de la
herramienta, evitando falsos incumplimientos por representaciones equivalentes.

Un replanteamiento puede sustituir una herramienta conservando los objetivos y los
filtros. Los filtros de origen deben seguir declarados en una consulta compatible.
Para los dos exportadores locales revisados, las opciones omitidas en una llamada
se vinculan a un único paso compatible del plan validado, incluyendo la narrativa
pedida. No se elige entre poblaciones ambiguas y no se aplica esta vinculación a
envíos de correo u otras escrituras. El historial refleja los argumentos ejecutados.

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

Las consultas generales reconocidas sobre quién trabaja ahora y los resúmenes simples
de uno a diez correos recientes disponen de lectura directa autorizada. No exigen un
plan generado: ejecutan una herramienta de lectura revisada, comprueban su resultado
y muestran su conclusión local. Conservan permisos, auditoría y límites de ejecución.
Las peticiones compuestas o con filtros distintos continúan por el planificador.
Las referencias a personas de un resultado anterior se fijan al entrar en el turno;
una lectura auxiliar no puede sustituir esa selección durante el mismo análisis.
Al filtrar o tomar las primeras filas de una tabla de personas, la población interna
se reduce a las mismas identidades. Una asociación incompleta o con nombres ambiguos
se rechaza y exige repetir la consulta de origen. La comparativa salarial conserva
las personas sin nómina legible como filas sin importe, con cobertura explícita.
Tras un intento de recuperación del modelo, el motor puede completar las lecturas
tipadas que el plan aceptado aún no haya ejecutado. Conserva dependencias y filtros,
solo utiliza el catálogo autorizado de lectura, no genera archivos ni ejecuta
escrituras, y no reintenta fuentes que devolvieron errores o denegaron acceso.
En el resumen directo, cada mensaje se presenta como un extracto acotado de su fuente;
ni remitentes, asuntos ni cuerpos se envían al modelo. La voz recibe solo un aviso neutro.

Un análisis salarial con un solo mes explica localmente la falta de periodos
comparables. No genera una hipótesis causal ni interpreta la ausencia de serie
temporal como insuficiencia de presupuesto o de recursos económicos.

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

El cruce de vacaciones y turnos dispone de una herramienta de lectura que compara la misma
persona y el mismo día a lo largo de todo el periodo solicitado (hasta 93 días, sin recortar).
Exige conjuntamente permisos de empleados, vacaciones y turnos, y solo se registra si están
activos los tres dominios. Las identidades duplicadas bloquean el cruce; la falta de turnos
publicados se declara como limitación y no permite certificar ausencia de conflictos.

El análisis económico reutiliza texto local de nóminas únicamente con la indexación sensible
habilitada, mismo propietario y misma fecha de modificación de la fuente. Exige además que
cuadren devengado, deducciones y líquido. El resto se lee desde el PDF original; no se reduce
la población ni se amplía el límite de tiempo. Los importes se calculan transitoriamente.

Los embeddings permitidos eliminan secretos técnicos mediante el filtro determinista antes
de analizar entidades personales con Presidio. Un fallo de protección bloquea el envío con
la configuración de producción. Ninguno de estos filtros certifica detección absoluta de
información sensible arbitraria.

La ejecución correcta de una herramienta no demuestra por sí sola que se haya
interpretado toda la intención del usuario. Los filtros del plan son declarados por
el modelo; las reglas de dominio siguen siendo la autoridad sobre sus datos.

En PDF y HTML la verificación es textual: no acredita geometría visual ni la asociación
completa de filas. Las imágenes de gráficos no se vuelven a interpretar para comprobar
sus píxeles. Tampoco se certifican relaciones causales o recomendaciones de negocio.
Estas garantías requieren validación adicional, incluyendo conversaciones con el modelo
real y los datos autorizados del entorno de destino.
