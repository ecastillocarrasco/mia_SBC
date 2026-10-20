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

- **mia-mobile** (app para iOS y Android) — decisión del 2026-10-20: aparcado temporalmente.
  Alcance acordado para cuando se retome: mundos 2D y 3D desde el principio. Enfoque recomendado:
  envolver la web ya existente (Vite, Three.js) en un shell nativo con WebView/Capacitor y puente
  de login MSAL móvil nativo (SSO real vía broker, más maduro en iOS/Android que en Electron
  desktop) — mucho más barato que reconstruir el mundo 3D nativo en React Native/Flutter desde
  cero, con la opción de migrar solo el renderizado 3D a nativo más adelante si el rendimiento en
  WebView no es suficiente.
