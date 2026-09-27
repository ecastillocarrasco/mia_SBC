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
        "Turno de mañana = empieza entre 05:00 y 11:59; de tarde = entre 12:00 y 17:59; de noche = "
        "desde las 18:00 hasta las 04:59. Un 07:00-15:00 es de mañana aunque termine por la tarde.",
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
        "Sin importes de nómina",
        "mIA no lee el contenido de las nóminas: informa de su existencia, periodo y lectura. Para "
        "importes hay que abrir la nómina.",
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
