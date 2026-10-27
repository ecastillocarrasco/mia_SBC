"""Perfiles de política de privacidad.

Diseño deliberado: las cuatro políticas NUNCA desactivan la protección de identificadores personales
ni de secretos — "PUBLIC" no debe poder filtrar un DNI que apareciera por error en un texto marcado
como público. Lo que distingue a los perfiles es:
  * STRICT añade cuasi-identificadores (fechas) a lo que se seudonimiza y sube la exigencia de detección
    (más falsos positivos, menos falsos negativos) — para nóminas, salud, datos bancarios.
  * STANDARD/AGGREGATED/PUBLIC comparten la misma red de seguridad base; la diferencia entre ellas es de
    USO (si el dominio debería preferir enviar agregados en vez de filas crudas), no de qué se detecta.
"""

from __future__ import annotations

from enum import StrEnum


class Policy(StrEnum):
    STRICT = "strict"
    STANDARD = "standard"
    AGGREGATED = "aggregated"
    PUBLIC = "public"


class Action(StrEnum):
    TOKENIZE = "tokenize"
    """Se sustituye por un pseudo-token reversible (p. ej. [PERSON_001]); se puede restaurar si se autoriza."""
    REDACT = "redact"
    """Se elimina sin dejar rastro recuperable (secretos, credenciales): nunca se restaura."""
    ALLOW = "allow"
    """Pasa sin modificar: no es un identificador por sí mismo (cifras analíticas, porcentajes…)."""


PERSONAL_ENTITIES = frozenset(
    {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "LOCATION",
        "IBAN_CODE",
        "CREDIT_CARD",
        "US_SSN",
        "MEDICAL_LICENSE",
        "ES_DNI_NIE",
        "ES_IBAN",
        "ES_SOCIAL_SECURITY",
        "ES_NIF",
        "ES_NIE",
    }
)
"""Entidades que SIEMPRE se tokenizan, en las cuatro políticas: es la red de seguridad base.
ES_NIF/ES_NIE son los reconocedores NATIVOS de Presidio para España (coexisten con los propios
ES_DNI_NIE/ES_IBAN/ES_SOCIAL_SECURITY, con verificación de dígito de control): doble cobertura
deliberada — si el reconocedor propio no detectara un caso límite, el nativo de Presidio sigue
protegiendo. No es lógica duplicada: son dos detectores independientes sobre la misma red de seguridad."""

_STRICT_EXTRA = frozenset({"DATE_TIME", "NRP"})
"""Solo en STRICT: cuasi-identificadores que, combinados con otros datos, pueden reidentificar a alguien
(p. ej. una fecha de nacimiento + un departamento). Fuera de STRICT se permiten porque las fechas son
necesarias para casi cualquier análisis temporal (turnos, nóminas por mes…) y no son identificativas solas."""

_SCORE_THRESHOLD = {
    Policy.STRICT: 0.3,
    Policy.STANDARD: 0.45,
    Policy.AGGREGATED: 0.45,
    Policy.PUBLIC: 0.45,
}


def entities_to_tokenize(policy: Policy) -> frozenset[str]:
    if policy is Policy.STRICT:
        return PERSONAL_ENTITIES | _STRICT_EXTRA
    return PERSONAL_ENTITIES


def all_tokenizable_entities() -> frozenset[str]:
    """Unión a través de las cuatro políticas: todo tipo de entidad que pueda llegar a convertirse en
    un pseudo-token ``[TIPO_NNN]``, se mire con la política que se mire. Única fuente de verdad para que
    el detector de tokens filtrados (``tokenizer._TOKEN_RE``) no tenga que repetir esta lista."""
    return PERSONAL_ENTITIES | _STRICT_EXTRA


def score_threshold(policy: Policy) -> float:
    return _SCORE_THRESHOLD[policy]


def action_for(entity_type: str, policy: Policy) -> Action:
    if entity_type in entities_to_tokenize(policy):
        return Action.TOKENIZE
    return Action.ALLOW


def resolve_policy(name: str | None, *, default: str) -> Policy:
    try:
        return Policy(name or default)
    except ValueError:
        return Policy(default)
