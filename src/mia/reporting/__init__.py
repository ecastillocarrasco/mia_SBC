"""Advanced Intelligence & Reporting Engine (Bloque II) — motor de planificación e informes.

Capas, de más genérica a más específica:

  mia.query/           infraestructura reutilizable ya existente: resolución de periodos
                        (``period_engine``), catálogo semántico de campos (``field_registry``), y un
                        DSL de consulta en memoria (``UniversalQueryEngine``) — nada de esto es nuevo
                        del Bloque II, se adopta en vez de reconstruirlo (ver ADVANCED_REPORTING_PROGRESS.md).
  mia.reporting/        (este paquete) — las piezas nuevas del Bloque II: ``ReportPlanner`` traduce una
                        petición en lenguaje natural en un ``ReportPlan`` validado contra el catálogo
                        semántico y los permisos del usuario, antes de que nada se ejecute.
  mia.modules.rrhh.informes/  capa de herramientas conversacionales y renderizado (PDF/XLSX/PPTX) ya
                        existente — sigue siendo la responsable de producir el documento final; este
                        paquete no la sustituye, la antecede.

Ninguna pieza de este paquete ejecuta SQL ni llama al LLM directamente: ``ReportPlanner`` es
determinista (resuelve texto contra el catálogo, nunca "adivina" un campo que no esté registrado), y
cualquier dato sensible (nóminas) solo puede resolverse a través de las herramientas de dominio ya
auditadas — ver ``PlannedMetric.requires_protected_route`` en ``planner.py``.
"""

from __future__ import annotations
