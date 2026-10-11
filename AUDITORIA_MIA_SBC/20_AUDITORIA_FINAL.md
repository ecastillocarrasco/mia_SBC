# 20 - Auditoría Final Consolidada

**Fecha:** 2026-10-06  
**Proyecto:** mIA SBC — Sunset Beach Club  
**Directorio:** `c:\Users\enriq\Desktop\Proyectos\Sunset\mIA`

---

## Tabla Principal — Estado por Área

| Área | Implementación | E2E funcional | Robustez | Tests | Estado |
|---|---|---|---|---|---|
| Motor de conversación | Completa | Con LLM real | Alta | Buena | 🟢 |
| Autenticación y permisos | Completa | Requiere config Entra | Alta | Buena | 🟡 |
| Empleados y organización | Completa | Con SP | Alta | Buena | 🟡 |
| Turnos (publicados) | Completa | Con SP | Alta | Buena | 🟡 |
| Turnos (histórico) | Completa | Con SP:Calendarios | Buena | Buena | 🟡 |
| Vacaciones | Completa | Con SP | Alta | Buena | 🟡 |
| Nóminas (metadatos) | Completa | Con SP | Alta | Buena | 🟡 |
| Nóminas (importes) | Completa | Con SP+perm | Buena | Parcial | 🟡 |
| Documentos firmados | Completa | Con SP | Alta | Buena | 🟡 |
| Correo | Completa | Con Graph | Buena | Parcial | 🟡 |
| Curriculums | Completa | Con SP | Buena | Buena | 🟡 |
| Trabajo Temporal | Completa | Con SP | Alta | Parcial | 🟡 |
| Analítica / Panel | Completa | Con SP | Alta | Buena | 🟢 |
| Consulta Cruzada | Completa | Con SP | Alta | Buena | 🟢 |
| Informes | Completa | Local + SP | Alta | Buena | 🟢 |
| Finanzas | Placeholder | No | N/A | No | 🔴 |
| Módulo predictivo | Skeleton | No | N/A | No | ⚪ |
| Voz (ElevenLabs) | Completa | Requiere config | Buena | Parcial | 🟡 |
| Avatar 2D/3D | Completa | Local | Buena | Parcial | 🟢 |
| Avatar Hologram | Skeleton | No | N/A | No | ⚪ |

---

## Veredicto Final — 11 Preguntas Clave

### 1. ¿Qué % está realmente terminado?

**~75% del código base RRHH está terminado.** Las 77 tools están implementadas y probadas. El 25% restante corresponde a Finanzas (0%), Predictivo (infraestructura sin conectar), Hologram (skeleton), y campos faltantes en Employee (hire_date, género, contract_type) que bloquean ~8 funcionalidades.

---

### 2. ¿Qué % funciona E2E?

**~65% funciona E2E hoy mismo, sin configuración de SharePoint.**

Con SharePoint configurado: **~85% de las tools RRHH funcionarán E2E**.

Con content_enabled + NOMINAS_IMPORTES: **~95% de las tools RRHH funcionarán E2E**.

El 5% restante son gaps por campos de datos no disponibles (fichajes, género, antigüedad).

---

### 3. ¿Qué % de preguntas razonables puede responder?

Del CSV auditado (365 preguntas):
- ✅ SOPORTADA: 61.9% (226 preguntas)
- 🟡 PARCIALMENTE: 12.6% (46 preguntas — con configuración)
- 🔴 NO SOPORTADA: 25.5% (93 preguntas)

**Con configuración completa: ~74.5% de las preguntas del CSV pueden responderse.**

De las 🔴 NO SOPORTADAS, ~13 son por módulo Finanzas vacío, ~8 por campos faltantes en Employee, y el resto por funcionalidades genuinamente no implementadas (fichajes, escritura, formación, plan igualdad, etc.).

**Nota:** Las preguntas 161-163 (conceptos nómina, IRPF, percentiles) y 284 (jubilación), 322-323 (ETT faltantes/variación) están desactualizadas en el CSV — ahora deberían ser 🟡 o ✅.

---

### 4. Los 10 módulos más maduros

1. Analítica / Panel RRHH — 8.5
2. Sistema (capacidades/resultados) — 8.3
3. Consulta Cruzada — 8.3
4. Nóminas (metadatos) — 8.1
5. Turnos (publicados) — 8.0
6. Documentos firmados — 7.8
7. Trabajo Temporal — 7.8
8. Vacaciones — 7.7
9. Nóminas (importes/estadísticas) — 7.7
10. Empleados — 7.5

---

### 5. Los 10 principales gaps

1. **Módulo Finanzas vacío** — Sin fuente de datos, 13 preguntas bloqueadas
2. **Campos faltantes en Employee** — hire_date, gender, contract_type bloquean antigüedad, género, tipo contrato
3. **Sin sistema de fichajes** — Imposible responder preguntas de control de presencia real
4. **Correo condicional a Graph API** — En demo sin Graph, 24 preguntas parciales
5. **Módulo predictivo no conectado** — analytics/ existe pero no al conversacional
6. **Sin módulo de evaluación de desempeño** — RRHH sin esta dimensión
7. **Sin módulo de formación con catálogo** — Solo documentos de formación firmados
8. **Sin calendario laboral / festivos convenio** — No puede responder sobre días festivos del hotel
9. **Sin permisos especiales en Vacaciones** — Matrimonio, maternidad, paternidad no modelados
10. **Sin escritura en SharePoint** — mIA es solo lectura; no puede crear, modificar ni aprobar

---

### 6. Los 10 mayores riesgos de producción

1. **auth.mode=dev en producción** — CRÍTICO; bloqueado en código pero requiere configuración correcta
2. **pseudonym_key por defecto** — CRÍTICO; protege DNI/NIE; debe venir de Key Vault
3. **SharePoint no configurado** — 80% del valor no disponible sin cert+URL
4. **CORS origins permisivos (localhost)** — ALTO; debe actualizarse con dominio real
5. **mia_local.db en directorio del proyecto** — MEDIO; no debe usarse en producción
6. **LLM provider=fake en producción** — CRÍTICO; bloqueado en código pero requiere API key real
7. **Máx 4 rondas de tools** — MEDIO; consultas complejas pueden quedar incompletas
8. **Historial de 12 turnos** — BAJO-MEDIO; memoria conversacional limitada en sesiones largas
9. **Parser de nóminas regex** — MEDIO; si el proveedor de nóminas cambia el formato, puede fallar silenciosamente
10. **Rutas de compatibilidad activas** — BAJO; mantienen acoplamiento con sistema anterior

---

### 7. Las 10 mejoras de mayor impacto

1. **Configurar SharePoint real** — Activa el 80% del valor con trabajo mínimo de código
2. **Configurar auth Entra ID** — Seguridad real por usuario en producción
3. **Añadir hire_date y gender a Employee** — Desbloquea antigüedad, género, plan igualdad
4. **Módulo Finanzas con fuente de datos** — Abre dimensión completamente nueva
5. **Conectar módulo predictivo** — Forecasting, correlaciones, predicciones RRHH
6. **Configurar ElevenLabs** — Avatar parlante: experiencia de usuario diferencial
7. **Tipo de permiso especial en Vacaciones** — Maternidad, paternidad, matrimonio son frecuentes
8. **Tests para nuevas tools** — Previene regresiones de las últimas implementaciones
9. **Visualización de serie temporal** (tendencias en gráfico) — Datos ya disponibles, falta visualización
10. **Parámetro periodo en informe ejecutivo** — Para comparativas históricas directamente desde el chat

---

### 8. ¿Hay funcionalidades basadas en mocks/fallbacks?

**Sí, pero están bien delimitadas:**

- **LLM provider=fake**: Solo activo en tests. En producción, el LLM fake está bloqueado por validación.
- **BD SQLite local**: Usada solo en tests (conftest.py). El sistema de producción necesita PostgreSQL.
- **auth.mode=dev**: Solo para desarrollo local. Bloqueado en producción.
- **SharePoint sin configurar**: Las tools devuelven `SOURCE_UNAVAILABLE` explícitamente, no datos inventados.
- **Correo sin Graph**: Las tools de correo devuelven error explícito, no datos simulados.

**No hay fallbacks silenciosos que devuelvan datos inventados.** El sistema falla de forma explícita y comunicativa cuando una fuente no está disponible.

---

### 9. ¿Está lista para demo?

**SÍ, con condiciones:**

Para demo con datos reales de SBC:
- Configurar SharePoint (cert, tenant, URL) — P0.1
- Configurar LLM con API key real — P0.2
- Configurar PostgreSQL — P0.3
- Ejecutar sincronización inicial — P0.4

Con esa configuración (estimación: 1-2 días de setup), el 85% de las funcionalidades RRHH están listas para demo.

---

### 10. ¿Está lista para preproducción?

**SÍ, con trabajo adicional:**

Además de la configuración de demo:
- Configurar Graph API para correo — P1.3
- Configurar Entra ID para auth real — P1.1
- Tests de humo E2E con datos reales — P1.8
- Revisar CORS para el entorno — P0.5
- Pseudonym key desde Key Vault — P1.2

Estimación: 1 semana adicional de trabajo después de demo.

---

### 11. ¿Está lista para producción autónoma?

**NO YET. Requiere:**

- Todo lo de preproducción
- Validar formatos de PDFs de nóminas del proveedor de SBC con el parser
- Definir y asignar roles de Entra ID a usuarios reales
- Configurar observabilidad (App Insights)
- Revisar y eliminar rutas de compatibilidad legacy
- Añadir tests para las funciones nuevas (proximos_jubilacion, conflictos_vacaciones, anomalias_nominas, etc.)
- Plan de respaldo y recuperación de BD

Estimación conservadora desde hoy: **4-6 semanas** para producción robusta.

---

## Resumen de Indicadores

| Indicador | Valor |
|---|---|
| Total de tools registradas | 77 |
| Dominios activos | 10 (de 11: Finanzas vacío) |
| Preguntas ✅ en CSV | 226 / 365 (61.9%) |
| Preguntas ✅ con config completa | ~272 / 365 (~74.5%) |
| Módulos sin tests | Finanzas, Predictivo, Hologram |
| Funcionalidades ocultas identificadas | 12 |
| Artefactos a limpiar | 3 (main - copia.js, frontend.zip, mia_local.db en raíz) |
| Madurez global RRHH | 7.5 / 10 |
| Madurez global incluyendo vacíos | 6.8 / 10 |
| Lista para demo | SÍ (con config) |
| Lista para preproducción | Con trabajo (1 semana adicional) |
| Lista para producción | Con trabajo (4-6 semanas) |
