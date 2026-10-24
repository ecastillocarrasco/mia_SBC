"""Advanced Intelligence & Reporting Engine (Bloque II) — motor de planificación e informes.

Capas, de más genérica a más específica:

  mia.query/           infraestructura reutilizable ya existente: resolución de periodos
                        (``period_engine``), catálogo semántico de campos (``field_registry``), y un
                        DSL de consulta en memoria (``UniversalQueryEngine``) — nada de esto es nuevo
                        del Bloque II, se adopta en vez de reconstruirlo (ver ADVANCED_REPORTING_PROGRESS.md).
  mia.reporting/        núcleo compartido: planificación, composición narrativa, modelo documental,
                        gráficos y renderizadores PDF/XLSX/PPTX/HTML/DOCX. No pertenece a un dominio.
  mia.modules.<dominio>/ herramientas conversacionales y datos de cada dominio; RRHH es el primero
                        con generación de informes conectada a este motor.

Ninguna pieza de este paquete ejecuta SQL ni llama al LLM directamente: ``ReportPlanner`` es
determinista (resuelve texto contra el catálogo, nunca "adivina" un campo que no esté registrado), y
cualquier dato sensible (nóminas) solo puede resolverse a través de las herramientas de dominio ya
auditadas — ver ``PlannedMetric.requires_protected_route`` en ``planner.py``.
"""

from __future__ import annotations
