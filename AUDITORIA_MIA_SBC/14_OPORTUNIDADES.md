# 14 - Oportunidades de Mejora

## Clasificación Esfuerzo × Impacto

### Alto impacto, bajo esfuerzo (Quick wins)

| # | Oportunidad | Esfuerzo | Impacto | Detalle |
|---|---|---|---|---|
| 1 | Añadir campos hire_date y contract_type a Employee | Bajo | Alto | Desbloquea antigüedad, tipo de contrato. Depende de que SP los tenga. |
| 2 | Añadir campo gender a Employee | Bajo | Alto | Desbloquea estadísticas de género, plan de igualdad básico. |
| 3 | Activar content_enabled=True en demo/producción | Trivial | Alto | Ya está activado por defecto. Solo necesita configurar SP real. |
| 4 | Configurar SharePoint real | Configuración | Alto | Activa el 80% de las funcionalidades con trabajo mínimo de código. |
| 5 | Tests para parse_concepts() y parse_employer_ss() | Bajo | Medio | Cobertura de regresión para parsers críticos de nóminas. |
| 6 | Ampliar historial conversacional de 12 a 24 turnos | Trivial (1 config) | Medio | Mejora la memoria en sesiones largas. |
| 7 | Añadir tipo `chart` dedicado para tendencias | Bajo | Medio | tendencia_ausencias ya devuelve datos temporales; falta visual de serie temporal. |
| 8 | Tipo de calendario semanal en frontend | Medio | Medio | Para visualizar turnos de la semana más intuitivamente. |
| 9 | Tests unitarios para nuevas tools (proximos_jubilacion, conflictos_vacaciones, etc.) | Bajo | Medio | Previene regresiones en funciones nuevas. |
| 10 | Eliminar artefactos (main - copia.js, frontend.zip) | Trivial | Bajo | Limpieza del repositorio. |

---

### Alto impacto, alto esfuerzo (Inversiones estratégicas)

| # | Oportunidad | Esfuerzo | Impacto | Detalle |
|---|---|---|---|---|
| 11 | Conectar módulo analytics/ al conversacional | Alto | Alto | Forecasting de plantilla, predicción de bajas, análisis predictivo de RRHH. |
| 12 | Módulo Finanzas con fuente de datos real | Alto | Alto | Desbloquea preguntas de negocio más allá de RRHH. |
| 13 | Integración con sistema de fichajes | Alto | Alto | Horas de entrada/salida, control de presencia real. |
| 14 | Módulo de evaluación de desempeño | Alto | Alto | Valoraciones, objetivos, revisiones anuales. |
| 15 | Módulo de formación con catálogo de cursos | Medio-Alto | Medio-Alto | Historial de formación, cursos disponibles, asignaciones. |
| 16 | Calendario laboral y convenio colectivo | Medio | Medio | Festivos por convenio, días especiales, reducción de jornada. |
| 17 | Tipos de permiso especial (matrimonio, maternidad) | Medio | Medio | Ampliar el modelo de Vacation con tipos adicionales. |
| 18 | Sistema de notificaciones (sin promesas imposibles) | Alto | Alto | Avisos proactivos de vencimientos, incorporaciones, jubilaciones próximas — requiere diseño cuidadoso para no romper el guard. |
| 19 | Escritura en SharePoint (aprobaciones, turnos) | Muy alto | Muy alto | Transformaría mIA de consulta a acción. Requiere nuevo modelo de autorización. |
| 20 | Plan de igualdad y diversidad | Medio | Alto | Si se añaden campos género y discapacidad, el módulo sería directo. |

---

### Bajo impacto, bajo esfuerzo (Backlog)

| # | Oportunidad | Detalle |
|---|---|---|
| 21 | Personalización de colores en informes | Parámetro branding en el renderer |
| 22 | Parámetro `periodo` en informe ejecutivo | Para informes históricos comparativos |
| 23 | Tipo `gantt` para solapamiento de vacaciones | Visualización de periodos |
| 24 | Marcar correo como leído | Tool simple en Graph API |
| 25 | Fecha de expiración en documentos firmados | Campo fecha_expiración en SignedDocument |

---

## Capacidades Casi Listas

Estas funcionalidades están implementadas pero necesitan solo configuración o una dependencia menor:

### 1. Nóminas con importes completos
- **Estado actual:** Implementado pero requiere content_enabled + SharePoint + permiso NOMINAS_IMPORTES
- **Qué falta:** Solo configuración
- **Valor desbloqueado:** Estadísticas salariales con percentiles, ranking, comparativas interanuales, coste empresa

### 2. Voz con ElevenLabs
- **Estado actual:** Implementado pero VoiceProviderName.NONE en dev
- **Qué falta:** API key y voice_id de ElevenLabs
- **Valor desbloqueado:** Interacción completamente vocal con el avatar

### 3. Búsqueda semántica de candidatos optimizada
- **Estado actual:** Indexador implementado, embeddings generados en sincronización
- **Qué falta:** Verificar que el índice esté precargado correctamente con SP real
- **Valor desbloqueado:** Búsquedas de CVs mucho más precisas que keywords

### 4. Correo completo
- **Estado actual:** 8 tools implementadas
- **Qué falta:** Configurar Graph API + mailbox
- **Valor desbloqueado:** Gestión del buzón de RRHH desde el chat

### 5. Auth Entra ID en producción
- **Estado actual:** Implementado y validado
- **Qué falta:** Registrar la app en Entra ID del tenant de SBC y configurar env vars
- **Valor desbloqueado:** Seguridad real por usuario/rol en producción
