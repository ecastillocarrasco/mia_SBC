# 12 - Deuda Técnica

## Artefactos de Desarrollo

| Fichero | Problema | Riesgo |
|---|---|---|
| `frontend/src/worlds/hologram/main - copia.js` | Fichero de copia no eliminado | Bajo — no afecta funcionalidad, confusión en mantenimiento |
| `mia_local.db` en raíz | BD SQLite de desarrollo expuesta | Medio — no debe versionarse ni estar en raíz en producción |
| `frontend.zip` en raíz | Archivo zip del frontend | Bajo — debería estar fuera del repo |

---

## TODOs / FIXMEs detectados en código

No se detectaron `TODO`, `FIXME`, `HACK` o `XXX` en el código fuente de `src/mia/`. La búsqueda grep no arrojó resultados para estos patrones en Python. El código está relativamente limpio de marcadores de deuda técnica explícitos.

---

## Módulos Placeholder / Vacíos

| Módulo | Estado | Deuda |
|---|---|---|
| `modules/finanzas/__init__.py` | register() vacío | Intencional y documentado — no es deuda técnica, es roadmap |
| `src/mia/analytics/` | Directorios creados sin código conectado al conversacional | Deuda media — infraestructura sin conectar |
| `src/mia/learning/` | Sin contenido funcional visto | Deuda media — reservado para futuro |
| `src/mia/knowledge/` | Sin contenido funcional visto | Deuda media — reservado para RAG futuro |
| `src/mia/rules/` | Mínimo (rules_for_prompt) | Bajo — funcional pero sin expansión |

---

## Campos Faltantes en Modelo Employee

Estos campos no existen en el modelo `Employee` y bloquean múltiples preguntas de RRHH:

| Campo | Preguntas bloqueadas | Riesgo funcional |
|---|---|---|
| `gender` / `sexo` | Plan igualdad, estadísticas género | Alto |
| `hire_date` | Antigüedad, correlaciones, jubilación precisa | Alto |
| `contract_type` | Tipo de contrato (indefinido, temporal) | Alto |
| `work_schedule` / `jornada` | Jornada parcial, reducción | Medio |
| `disability` | Certificado discapacidad | Bajo (datos sensibles) |
| `contract_end_date` | Vencimiento de contrato | Medio |
| `special_leave_type` | Excedencias, reducción | Medio |

Estos campos dependen de que SharePoint los contenga. Si la lista SP no los tiene, no se pueden sincronizar. Requiere coordinación con la configuración del SharePoint de SBC.

---

## Dependencias Implícitas / Acoplamiento

| Patrón | Fichero | Riesgo |
|---|---|---|
| Import circular prevenido con lazy import (PLC0415) | analitica/tools.py, turnos/__init__.py | Bajo — es la solución correcta pero señala dependencias entre dominios |
| `LAST_TABLE` compartido en sesión | conversation/tools.py, informes/tools.py | Medio — si una tool escribe mal la última tabla, los informes fallan |
| `MAX_ROWS_FOR_MODEL` hardcoded | common.py | Bajo — configurable en código pero no en settings |
| `_EDAD_JUBILACION = 67` hardcoded | analitica/tools.py | Bajo — puede cambiar legislativamente |

---

## Código de Compatibilidad

- `api/routes/compat.py` existe (visto en main.py). Sugiere rutas de compatibilidad con el sistema anterior.
- `test_compat.py` y `test_legacy_view.py` testean esta compatibilidad.
- Mientras estas rutas de compatibilidad existan, hay un acoplamiento implícito con el sistema anterior que añade deuda de mantenimiento.

---

## Duplicaciones Detectadas

| Patrón | Descripción | Riesgo |
|---|---|---|
| `document_entry()` en common.py | Usada en varios dominios para botones de descarga | Bajo — bien abstraído |
| `table()` helper | Usado en todas las tools para formato de presentación | Bien — es la abstracción correcta |
| Parámetros CohortParams/PersonaParams/ActivosParams | Jerarquía de parámetros bien definida | Bien — sin duplicación |

No se detectaron duplicaciones significativas. La arquitectura modular ha evitado la mayoría de los duplicados.

---

## Legacy

- Existe carpeta `legacy/` (referenciada en CLAUDE.md como READ-ONLY)
- `test_legacy_view.py` sugiere que hay vistas del sistema anterior siendo testeadas
- `api/routes/compat.py` sugiere rutas de compatibilidad activas
- Ningún import desde `legacy/` en el código nuevo (CLAUDE.md lo prohíbe)
- La deuda es tener rutas de compatibilidad activas que mantendrán un acoplamiento con el sistema anterior hasta su eliminación definitiva

---

## Clasificación de Deuda por Riesgo

| Prioridad | Elemento | Acción |
|---|---|---|
| P0 | mia_local.db en raíz | Añadir a .gitignore y mover a directorio de datos |
| P0 | Rutas compat activas | Planificar eliminación coordinada con frontend |
| P1 | Campos faltantes en Employee (gender, hire_date) | Coordinar con SP de SBC |
| P1 | `main - copia.js` en hologram | Eliminar |
| P1 | `frontend.zip` en raíz | Eliminar del repo |
| P2 | analytics/ no conectado | Planificar integración conversacional |
| P2 | Módulos learning/ y knowledge/ vacíos | Documentar roadmap o eliminar directorios |
| P3 | _EDAD_JUBILACION hardcoded | Externalizar a settings o constante documentada |
| P3 | Tests para nuevas functions (parse_concepts, conflictos, proximos_jubilacion, etc.) | Añadir cobertura |
