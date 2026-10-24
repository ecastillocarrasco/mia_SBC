# mIA — Roadmap e hitos

Índice de alto nivel de hacia dónde va mIA. El backlog técnico detallado vive en otros
documentos (no se duplica aquí):

- `AUDITORIA_MIA_SBC/15_ROADMAP_RECOMENDADO.md` — backlog priorizado (P0-P3) con cronograma.
- `FUNCTIONAL_EXPANSION/13_ROADMAP_NEXT.md` — próximos pasos técnicos concretos (motor de periodos, datasets normalizados...).
- `docs/pendientes.md` — tareas sueltas por fase, informal.

Este fichero es solo el mapa: qué está hecho, qué está en marcha, qué está aparcado y por qué.

---

## Hitos recientes

**2026-10-19/20 — Autenticación Entra ID (login real)**
- Backend: proveedores de identidad (`dev`/`easyauth`/`entra`), validación de JWT contra Entra ID,
  App Roles reales mapeados a permisos (`Global`, `RRHH`, `RRHH.NoNominas`, `Administracion`, `Legal`),
  endpoint público `GET /api/auth/config`.
- Permiso `DOCUMENTOS_CONTENIDO_MEDICO`: Legal ve documentos/contratos pero nunca el contenido de
  reconocimientos médicos; RRHH conserva el acceso completo.
- Frontend: MSAL.js cableado en los 4 puntos de entrada reales (portal, 2D, 3D, holograma), con
  `Authorization: Bearer` adjunto en todas las llamadas reales (incluido el mundo 2D clásico,
  `mia-2d.js`/`mia-enhance.js`, que no pasa por `MiaClient`).
- Limpieza: eliminado `mia-2d_old.js` (copia de respaldo sin referencias). Corregidas 3 pruebas de
  OCR que habían quedado desactualizadas tras migrar a Tesseract local.

## En marcha

- **Página de acceso no autorizado / error de acceso**: un usuario autenticado correctamente en
  Entra ID pero sin ningún rol reconocido se queda hoy con permisos vacíos y ningún aviso (el chat
  carga igual, simplemente ninguna herramienta funciona nunca). Se añade una pantalla con el
  lenguaje visual premium de mIA para este caso y para errores reales de acceso.

## Aparcado

- **Incidencia P1 — continuidad de población y filtros en consultas de empleados/salarios** —
  retomarla después de cerrar la incidencia actual del correo. Casos reproducidos por el usuario en
  mIA web privada:
  1. «¿Quiénes están trabajando ahora mismo?» devuelve correctamente el listado general. En el
     seguimiento, pide comparar el salario de agosto de 2026 de las seis personas que trabajan en
     Recepción, pero la comparativa devuelve otras seis personas ajenas a la selección.
  2. Tras cerrar y reiniciar el backend, la misma pregunta general «¿qué empleados están trabajando
     ahora mismo?» devuelve solo empleados de Recepción, en vez de incluir todos los departamentos.
  - Comportamiento esperado: una comparación de salarios debe conservar exactamente la población
    seleccionada y validar que la respuesta pertenece a esas personas; una pregunta nueva y general
    debe calcularse sin filtros residuales de una consulta anterior, incluso después de reiniciar.
  - Al retomarlo, trazar el contexto/filtros entre turnos, las claves de sesión y el estado
    recordado por las herramientas de fichajes y nóminas; revisar además qué estado persiste o se
    reconstruye al reiniciar el backend. Prioridad alta por riesgo de atribuir importes salariales a
    empleados equivocados. No dar por válida una comparativa si la población resultante no coincide
    con la solicitada.

- **Listado de buzones compartidos accesibles por usuario** — pospuesto hasta después de preparar
  preproducción y realizar la demo con el cliente. Actualmente, si la persona conoce la dirección
  del buzón compartido y Exchange le ha concedido acceso, puede indicársela a mIA; Graph valida el
  acceso delegado al operar con ese buzón. Lo pendiente es descubrir y listar esos buzones sin que
  el usuario tenga que conocer previamente sus direcciones.
  - Alcance inicial recomendado: buzones con permiso **Full Access**, concedido directamente o a
    través de grupos; no incluir permisos **Send As** por sí solos, ya que no habilitan la lectura.
  - Requiere una fuente de permisos de Exchange y un catálogo sincronizado por usuario/grupo. Como
    el proyecto no dispone actualmente de Azure Automation, evaluar tras la demo una tarea
    programada en el servidor Windows de PRE u otra opción operativa disponible. Guardar solo
    metadatos de buzones y permisos, nunca contenido de correo.
  - La consulta y las operaciones sobre el correo seguirán usando el token delegado del usuario;
    Graph/Exchange debe continuar siendo la comprobación efectiva de acceso. Añadir trazabilidad,
    control de antigüedad/errores de sincronización y pruebas para permisos directos y por grupo.
  - No es requisito para la demo ni bloquea el uso actual: el usuario puede indicar el buzón
    compartido que ya conoce.

- **mia-mobile** (app para iOS y Android) — decisión del 2026-10-20: aparcado temporalmente.
  Alcance acordado para cuando se retome: mundos 2D y 3D desde el principio. Enfoque recomendado:
  envolver la web ya existente (Vite, Three.js) en un shell nativo con WebView/Capacitor y puente
  de login MSAL móvil nativo (SSO real vía broker, más maduro en iOS/Android que en Electron
  desktop) — mucho más barato que reconstruir el mundo 3D nativo en React Native/Flutter desde
  cero, con la opción de migrar solo el renderizado 3D a nativo más adelante si el rendimiento en
  WebView no es suficiente.
