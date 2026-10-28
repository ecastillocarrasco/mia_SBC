from __future__ import annotations

import random

from mia.voice.greeting import (
    WELCOME_TEMPLATES_NO_NAME,
    WELCOME_TEMPLATES_WITH_NAME,
    first_name_from_display_name,
    welcome_text,
)


def test_first_name_from_simple_display_name() -> None:
    assert first_name_from_display_name("Enrique Castillo Carrasco") == "Enrique"


def test_first_name_capitalizes_like_spanish_locale() -> None:
    assert first_name_from_display_name("maría JOSÉ lópez") == "María"


def test_first_name_from_email_like_display_name_uses_local_part() -> None:
    # EasyAuth puede entregar un UPN/correo como display_name cuando no hay claim "name".
    assert first_name_from_display_name("enrique.castillo@sunsetbeachclub.com") == "Enrique"
    assert first_name_from_display_name("ana_garcia@empresa.com") == "Ana"


def test_first_name_rejects_opaque_identifiers() -> None:
    # Último recurso de EasyAuth/Entra cuando no hay ningún nombre: un id opaco, nunca
    # interpolado tal cual en el saludo hablado.
    assert first_name_from_display_name("8f14e45f-ceea-467e-b7f1-0000000") == ""


def test_first_name_from_empty_or_missing_display_name() -> None:
    assert first_name_from_display_name("") == ""
    assert first_name_from_display_name(None) == ""


def test_welcome_text_with_name_uses_one_of_the_named_templates() -> None:
    text = welcome_text("Enrique", choice=random.Random(0))
    assert any(template.format(name="Enrique") == text for template in WELCOME_TEMPLATES_WITH_NAME)
    assert "Enrique" in text


def test_welcome_text_without_name_uses_the_no_name_templates() -> None:
    text = welcome_text("", choice=random.Random(0))
    assert text in WELCOME_TEMPLATES_NO_NAME
