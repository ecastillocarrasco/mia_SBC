"""Texto de bienvenida hablado por mIA al arrancar.

Única fuente de verdad para el saludo inicial: antes cada cliente (2D, 3D, holograma,
mIA Desktop) llevaba su propia copia de estas frases. mIA Desktop no puede importar el
módulo ESM del frontend (``frontend/src/core/identity-v45.js``), así que mantenía una
copia manual sincronizada a mano -- cómoda hasta que alguien tocara una lista sin tocar
la otra. Aquí vive la única versión; cualquier cliente que necesite el saludo lo pide
al backend en vez de llevar su propia copia.

Las frases son las mismas que ``identity-v45.js`` ya usa en 2D/3D/holograma.
"""

from __future__ import annotations

import random

WELCOME_TEMPLATES_WITH_NAME: tuple[str, ...] = (
    "¡Hola {name}! Soy mIA, tu asistente virtual. Estoy aquí para ayudarte con cualquier "
    "consulta. ¿Qué te gustaría saber?",
    "¡Hola {name}! Qué alegría verte por aquí. Soy mIA, ¿en qué puedo ayudarte hoy?",
    "Bienvenido de nuevo, {name}. Soy mIA, tu asistente virtual. Dime qué necesitas y te ayudo.",
    "¡Hola, {name}! Aquí estoy para lo que necesites. ¿Qué te gustaría consultar?",
    "{name}, un placer tenerte por aquí otra vez. Soy mIA. ¿Qué te gustaría saber?",
)

WELCOME_TEMPLATES_NO_NAME: tuple[str, ...] = (
    "¡Hola! Soy mIA, tu asistente virtual. Estoy aquí para ayudarte con cualquier consulta. "
    "¿Qué te gustaría saber?",
    "¡Hola! Soy mIA. ¿En qué puedo ayudarte hoy?",
    "Bienvenido. Soy mIA, tu asistente virtual. Dime qué necesitas y te ayudo.",
)

_MAX_NAME_LENGTH = 40
_NAME_EXTRA_CHARS = "'’-"


def _capitalized(candidate: str) -> str:
    return candidate[:1].upper() + candidate[1:].lower()


def _valid_first_name(candidate: str) -> str:
    """Replica ``textName()`` de identity-v45.js: un nombre de pila razonable, nunca un
    correo completo ni HTML/texto arbitrario. Cadena vacía si no es válido."""
    if not candidate or len(candidate) > _MAX_NAME_LENGTH or not candidate[0].isalpha():
        return ""
    if not all(ch.isalpha() or ch in _NAME_EXTRA_CHARS for ch in candidate[1:]):
        return ""
    return _capitalized(candidate)


def first_name_from_display_name(display_name: str | None) -> str:
    """Primer nombre a partir de lo que el proveedor de identidad entregó como nombre
    para mostrar. Igual que ``textName()``: si parece un correo, usa su parte local."""
    if not display_name:
        return ""
    cleaned = " ".join(display_name.strip().split())
    if not cleaned:
        return ""
    candidate = cleaned.split("@")[0].split("_")[0].split(".")[0].split("-")[0] \
        if "@" in cleaned else cleaned.split(" ")[0]
    return _valid_first_name(candidate)


def welcome_text(first_name: str = "", *, choice: random.Random | None = None) -> str:
    """Una frase de bienvenida elegida al azar, con el nombre si hay uno válido."""
    rng = choice or random
    if first_name:
        return rng.choice(WELCOME_TEMPLATES_WITH_NAME).format(name=first_name)
    return rng.choice(WELCOME_TEMPLATES_NO_NAME)
