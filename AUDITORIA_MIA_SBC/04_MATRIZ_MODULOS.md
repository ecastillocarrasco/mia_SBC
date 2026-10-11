# 04 - Matriz de Módulos

## Leyenda de Estado

| Emoji | Significado |
|---|---|
| 🟢 | Completo y funcional E2E |
| 🟡 | Parcial o condicional a configuración |
| 🟠 | Implementado pero con gaps significativos |
| 🔴 | No implementado / vacío |
| ⚪ | Reservado / placeholder |
| 🔵 | Funcional pero no accesible desde el chat |

---

## Tabla Principal

| Módulo / Dominio | Implementada | Funciona E2E | Datos reales | UI disponible | IA integrada | Estado |
|---|---|---|---|---|---|---|
| **Sistema (capacidades, resultados, cruce)** | Sí | Sí | N/A (BD local) | Sí | Sí | 🟢 |
| **Empleados** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Turnos (publicados)** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Turnos (histórico/Calendario)** | Sí | Sí (con SP) | Necesita SP:Calendarios | Sí | Sí | 🟡 |
| **Vacaciones** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Nóminas (metadatos)** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Nóminas (importes/estadísticas)** | Sí | Sí (con SP+perm) | Necesita SP+content_enabled | Sí (payslip card) | Sí | 🟡 |
| **Documentos firmados** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Documentos (lectura PDF)** | Sí | Sí (con SP+perm) | Necesita SP+content_enabled | Sí | Sí | 🟡 |
| **Correo (Graph)** | Sí | Sí (con Graph) | Necesita Graph API | Sí | Sí | 🟡 |
| **Curriculums (metadatos)** | Sí | Sí (con SP) | Necesita SP:Candidaturas | Sí | Sí | 🟡 |
| **Curriculums (búsqueda vectorial)** | Sí | Sí (con SP+idx) | Necesita índice precargado | Sí | Sí | 🟡 |
| **Trabajo Temporal** | Sí | Sí (con SP) | Necesita SP:ETT | Sí | Sí | 🟡 |
| **Analítica / Panel RRHH** | Sí | Sí (con SP) | Necesita SP | Sí (dashboard) | Sí | 🟡 |
| **Consulta Cruzada** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Informes (PDF/Excel/PPTX)** | Sí | Sí (local) | No (genera de resultados) | Sí (descarga) | Sí | 🟢 |
| **Informes ejecutivos** | Sí | Sí (con SP) | Necesita SP | Sí | Sí | 🟡 |
| **Finanzas** | Solo skeleton | No | Sin fuente | No | No | 🔴 |
| **Módulo predictivo (analytics/)** | Infraestructura básica | No conectado al chat | No | No | No | ⚪ |
| **Voz (ElevenLabs)** | Sí | Sí (con API key) | N/A | Sí | N/A | 🟡 |
| **Avatar 2D** | Sí | Sí | N/A | Sí | Sí | 🟢 |
| **Avatar 3D** | Sí | Sí | N/A | Sí | Sí | 🟢 |
| **Avatar Hologram** | Placeholder | Parcial (skeleton) | N/A | Sí (stub) | No | ⚪ |
| **Auth (Entra ID)** | Sí | Sí (requiere config) | N/A | N/A | N/A | 🟡 |
| **Auditoría de accesos** | Sí | Sí | BD local | No (solo logs) | No | 🟢 |
| **Observabilidad (AppInsights)** | Sí | Sí (con connstr) | N/A | No (telemetría) | No | 🟡 |
| **Sincronización SharePoint** | Sí | Sí (con SP) | Necesita SP | No (background) | No | 🟡 |

---

## Notas

- "Funciona E2E con SP" significa que la lógica de negocio está completa y probada; solo falta la conectividad con el SharePoint real de Sunset Beach Club.
- El frontend renderiza correctamente todos los tipos de presentation (table, dashboard, payslip, employee360, chart, reincorporation…) a través del Presentation Director.
- El módulo `analytics/` tiene directorios creados pero ningún código Python de dominio conectado al conversacional.
