# 15 - Roadmap Recomendado

## P0 — Bloqueantes para Demo/Preproducción

Estos elementos deben resolverse antes de mostrar mIA con datos reales:

| # | Tarea | Tipo | Estimación |
|---|---|---|---|
| P0.1 | Configurar SharePoint real de SBC (tenant, cert, rrhh_site_url) | Infraestructura | 1-2 días |
| P0.2 | Configurar LLM con API key real (OpenAI o Azure OpenAI) | Infraestructura | Horas |
| P0.3 | Configurar base de datos PostgreSQL (no SQLite) | Infraestructura | 1 día |
| P0.4 | Ejecutar sincronización inicial de SharePoint | Operaciones | Horas (depende del volumen) |
| P0.5 | Configurar CORS origins con dominio real del frontend | Configuración | Minutos |
| P0.6 | Verificar content_enabled=True y sincronización de nóminas/documentos | Configuración | Horas |
| P0.7 | Eliminar artefactos (main - copia.js, frontend.zip) | Limpieza | Minutos |
| P0.8 | Añadir mia_local.db a .gitignore | Limpieza | Minutos |

---

## P1 — Necesarias para Producción

| # | Tarea | Tipo | Estimación |
|---|---|---|---|
| P1.1 | Registrar app en Entra ID del tenant de SBC (auth.mode=entra) | Seguridad | 1-2 días |
| P1.2 | Configurar MIA_DATA__PSEUDONYM_KEY desde Key Vault (no el default) | Seguridad | Horas |
| P1.3 | Configurar Graph API para correo del buzón de RRHH | Infraestructura | 1 día |
| P1.4 | Revisar roles de Entra ID y asignar permisos a usuarios reales | Seguridad/Ops | 1-2 días |
| P1.5 | Configurar Azure Application Insights (observabilidad) | Ops | Horas |
| P1.6 | Hardening CORS para producción | Seguridad | Horas |
| P1.7 | Verificar que las migraciones de BD están al día en producción | Ops | Horas |
| P1.8 | Tests de humo E2E con datos reales antes del go-live | QA | 1-2 días |
| P1.9 | Añadir tests para nuevas tools (proximos_jubilacion, conflictos_vacaciones, anomalias_nominas, etc.) | Desarrollo | 1-2 días |

---

## P2 — Alto Valor Funcional

| # | Tarea | Tipo | Estimación |
|---|---|---|---|
| P2.1 | Añadir campos hire_date y contract_type a Employee (si disponibles en SP) | Desarrollo | 1-2 días |
| P2.2 | Añadir campo gender a Employee (si disponible en SP) | Desarrollo | 1 día |
| P2.3 | Conectar módulo analytics/ al conversacional (inicio del módulo predictivo) | Desarrollo | 1-2 sprints |
| P2.4 | Módulo de formación básico (historial de cursos firmados + catálogo) | Desarrollo | 1 sprint |
| P2.5 | Tipos de permiso especial en Vacaciones (matrimonio, maternidad, paternidad) | Desarrollo | 1 día |
| P2.6 | Fecha de expiración en SignedDocument | Desarrollo | 1 día |
| P2.7 | Configurar ElevenLabs voice para avatar parlante | Infraestructura | Horas |
| P2.8 | Tipo `chart` de serie temporal en el frontend (para tendencia_ausencias) | Frontend | 1-2 días |
| P2.9 | Tipo `calendar` semanal en el frontend (para turnos de semana) | Frontend | 2-3 días |
| P2.10 | Personalización de logo e identidad corporativa en informes | Desarrollo | Horas |

---

## P3 — Avanzadas / Mediano Plazo

| # | Tarea | Tipo | Estimación |
|---|---|---|---|
| P3.1 | Módulo Finanzas con fuente de datos real (SharePoint/ERP) | Desarrollo | 2-4 sprints |
| P3.2 | Integración con sistema de fichajes (control de presencia) | Integración | 2-3 sprints |
| P3.3 | Módulo de evaluación de desempeño | Desarrollo | 2-3 sprints |
| P3.4 | Calendario laboral y gestión de convenio colectivo | Desarrollo | 1-2 sprints |
| P3.5 | Escritura en SharePoint (aprobaciones, publicación de turnos) | Desarrollo | 3-5 sprints |
| P3.6 | Sistema de notificaciones proactivas (no promesas) | Desarrollo | 2-3 sprints |
| P3.7 | Plan de igualdad y módulo de diversidad | Desarrollo | 1-2 sprints |
| P3.8 | Frontend hologram world completo | Frontend | 3+ sprints |
| P3.9 | Módulo de salud laboral (con datos anonimizados) | Desarrollo | 2-3 sprints |
| P3.10 | Pipeline de selección (fases de candidatura) | Desarrollo | 1-2 sprints |

---

## Cronograma Sugerido

```
Mes 1: P0 completo → Demo funcional con datos reales
Mes 2: P1 completo → Producción segura
Mes 3-4: P2 priorizados por valor negocio → Funcionalidad ampliada
Mes 5+: P3 por orden de valor → Plataforma completa
```
