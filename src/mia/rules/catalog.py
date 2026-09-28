"""Catálogo explícito de reglas de negocio.

Estas reglas estaban repartidas entre regex y hotfixes del sistema anterior.
Aquí cada una tiene identificador, enunciado y dominios; los tests de cada
dominio referencian su identificador para demostrar que se cumple.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BusinessRule:
    id: str
    title: str
    statement: str
    domains: tuple[str, ...]
    in_prompt: bool = True
    """Si el LLM debe conocerla; las puramente técnicas se aplican solo en código."""


RULES: tuple[BusinessRule, ...] = (
    BusinessRule(
        "POB-001",
        "Población activa por defecto",
        "Toda consulta sobre la plantilla usa empleados activos por defecto. Los inactivos solo "
        "se incluyen si el usuario lo pide expresamente, y el ámbito se mantiene igual en chat, "
        "cruces, analítica e informes.",
        ("empleados", "transversal"),
    ),
    BusinessRule(
        "CTX-001",
        "Una consulta autocontenida no hereda contexto",
        "Una pregunta completa por sí misma no hereda filtros ni dominio de las anteriores, salvo "
        "referencia inequívoca (ella, esos, de ellos).",
        ("conversacion",),
    ),
    BusinessRule(
        "CTX-002",
        "Las referencias usan el resultado anterior",
        "'De esos', 'de ellas' o 'entre ellos' se resuelven sobre el último resultado compatible, "
        "sin reconstruir la población.",
        ("conversacion",),
    ),
    BusinessRule(
        "REI-001",
        "Reincorporación: siempre con su motivo",
        "Una reincorporación es la vuelta al trabajo tras una baja, un permiso, unas vacaciones o unos asuntos "
        "propios. Se cuentan las cuatro salvo que se pida una en concreto, y cada reincorporación indica siempre "
        "después de cuál de estos hechos se produce (y el total, desglosado por motivo).",
        ("turnos", "vacaciones"),
    ),
    BusinessRule(
        "VAC-001",
        "Reincorporación efectiva",
        "La reincorporación tras unas vacaciones es el primer turno de tipo Trabajo posterior a la "
        "fecha de fin; nunca se supone el día siguiente.",
        ("vacaciones", "turnos"),
    ),
    BusinessRule(
        "VAC-002",
        "Saldo negativo",
        "Un saldo de vacaciones negativo se comunica como tal (días disfrutados de más); nunca se "
        "presenta como cero ni se omite.",
        ("vacaciones",),
    ),
    BusinessRule(
        "VAC-003",
        "Saldo oficial",
        "SaldoActual es el saldo oficial disponible: no se recalcula a partir de las solicitudes. Lo consumido "
        "es SaldoTotal − SaldoActual. Para «¿cuánto le quedará tras estas vacaciones?» se explica que el saldo "
        "oficial se actualiza en la fuente, sin inventar el cálculo.",
        ("vacaciones",),
    ),
    BusinessRule(
        "DAT-001",
        "Un fallo técnico no es un cero",
        "Si una fuente falla o no cubre el periodo, se informa del problema; nunca se presenta como "
        "ausencia del dato de negocio.",
        ("transversal",),
    ),
    BusinessRule(
        "DAT-002",
        "Consultas compuestas completas",
        "Una consulta con varias partes no se da por respondida hasta completar todas.",
        ("transversal",),
    ),
    BusinessRule(
        "DAT-003",
        "Las fuentes corporativas mandan",
        "Los datos corporativos los gobiernan sus fuentes. Las correcciones del usuario ajustan "
        "interpretación y alias, no los datos de negocio.",
        ("transversal",),
    ),
    BusinessRule(
        "TUR-001",
        "Franjas por hora de inicio",
        "Turno de mañana = empieza entre 06:00 y 13:59; de tarde = entre 14:00 y 21:59; de noche = desde las "
        "22:00 hasta las 05:59 (criterio del ejecutor v12 del sistema anterior). Solo cuentan turnos de Trabajo.",
        ("turnos",),
    ),
    BusinessRule(
        "TUR-002",
        "Presencia por solape",
        "Quién está trabajando a una hora se decide por solape del horario (un 22:00-06:00 cubre las "
        "02:00), no por la hora de inicio.",
        ("turnos",),
    ),
    BusinessRule(
        "AUS-001",
        "Periodo real de las ausencias",
        "Desde cuándo y cuántos días lleva alguien ausente se calcula sobre el periodo completo, no sobre "
        "las fechas consultadas: quien está de baja hoy no empezó hoy.",
        ("turnos", "vacaciones"),
    ),
    BusinessRule(
        "NOM-001",
        "Periodo de la nómina",
        "El mes de una nómina sale de MesNomina y, si no, del nombre del fichero (2026-08_Agosto.pdf). Un "
        "código no mensual (2025-71_Extra Julio) es una paga especial, no el mes 71 ni el 7 ordinario.",
        ("nominas",),
    ),
    BusinessRule(
        "NOM-002",
        "Importes de nómina con salvaguardas",
        "Los importes se leen del PDF en el momento, solo con el permiso nominas:importes, quedan "
        "auditados, no se guardan y nunca se dicen en voz alta.",
        ("nominas",),
    ),
    BusinessRule(
        "COR-001",
        "Correo: enviar solo con confirmación",
        "mIA puede leer, buscar y preparar borradores. Solo envía un borrador que el usuario ya ha visto "
        "y cuando lo confirma expresamente en su último mensaje.",
        ("correo",),
    ),
    BusinessRule(
        "PLA-001",
        "Calendario es el histórico real",
        "Calendario<Departamento>_AAAA es la fuente histórica y de planificación autoritativa, con horas "
        "reales; Turnos es la proyección semanal publicada actualmente visible para el empleado. No se "
        "reconstruye planificación a partir de Turnos.",
        ("turnos",),
    ),
    BusinessRule(
        "PLA-002",
        "Plantillas y comentarios no son histórico",
        "TurnosPlantillas son reglas/patrones de generación, no lo que de verdad ocurrió. "
        "ComentariosTurnosSemanas es contexto de departamento/semana: nunca se atribuye a una persona ni se "
        "confunde con el comentario individual de un turno del Calendario.",
        ("turnos",),
    ),
    BusinessRule(
        "PLA-003",
        "Personas por nombre en los calendarios",
        "Calendario, TurnosPlantillas y las métricas identifican a la persona por nombre (no por DNI): con "
        "nombres repetidos hay que preguntar cuál, igual que en una búsqueda de empleados.",
        ("turnos",),
    ),
    BusinessRule(
        "SEL-001",
        "Sin ranking automático de candidatos",
        "En selección se busca y se explica la evidencia de cada CV; no se ordena ni descarta "
        "automáticamente a candidatos.",
        ("curriculums",),
    ),
    BusinessRule(
        "FIR-001",
        "Firmas: solo existencia",
        "Sobre firmas solo se responde si existe o no; nunca se lee, muestra ni analiza su contenido.",
        ("documentos",),
    ),
)

_BY_ID = {r.id: r for r in RULES}


def rule(rule_id: str) -> BusinessRule:
    return _BY_ID[rule_id]


def rules_for_prompt() -> list[str]:
    return [f"[{r.id}] {r.statement}" for r in RULES if r.in_prompt]
