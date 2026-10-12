# V5.2.7 - Nota de alcance

Este parche corrige una falla de integridad de respuestas en el frontend,
no una consulta incorrecta de SQL, turnos, fichajes o Conectia en el backend.
La ruta LLM no es una fuente suficiente para datos actuales de personal.
El resultado real de trabajadores en servicio debe calcularse por criterios
operativos iguales que el 2D: fecha y hora, estado del turno, departamento,
cobertura de datos, ausencias y registro efectivo. Esta informacion aun no
se ha verificado contra el backend del usuario.
