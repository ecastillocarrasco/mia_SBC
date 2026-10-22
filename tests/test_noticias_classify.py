"""Clasificación temática determinista de noticias."""

from __future__ import annotations

from mia.modules.community.noticias.classify import (
    CATEGORY_GENERAL,
    CATEGORY_HOTELERA,
    CATEGORY_INVERSION,
    CATEGORY_NOMBRAMIENTOS,
    CATEGORY_PREMIOS,
    classify_category,
    match_category_query,
)


def test_classifies_investment_news() -> None:
    assert classify_category("Publication of Chairman's Statement for 2025") == CATEGORY_INVERSION
    assert classify_category("Resultado financiero del grupo", "beneficio récord este año") == CATEGORY_INVERSION


def test_classifies_hotel_news() -> None:
    assert classify_category("FBD Hotels adquiere el Grand Hotel Malahide") == CATEGORY_HOTELERA
    assert classify_category("Obras de renovación en el hotel de Benalmádena") == CATEGORY_HOTELERA


def test_classifies_appointments_before_hotel_keywords() -> None:
    """Un nombramiento de un directivo DE HOTEL debe quedar en nombramientos, no en hotelera (el
    orden de las reglas en classify.py es deliberado: nombramientos se evalúa antes)."""
    assert classify_category("Nuevo director general del hotel Sunset Beach Club") == CATEGORY_NOMBRAMIENTOS


def test_classifies_awards() -> None:
    assert classify_category("Sunset Beach Club wins Best Hotel Award 2026") == CATEGORY_PREMIOS


def test_falls_back_to_general_category() -> None:
    assert classify_category("Comunicado corporativo sin palabras clave reconocidas") == CATEGORY_GENERAL


def test_match_category_query_recognises_natural_language() -> None:
    assert match_category_query("financiera") == CATEGORY_INVERSION
    assert match_category_query("hotelera") == CATEGORY_HOTELERA
    assert match_category_query("premios") == CATEGORY_PREMIOS
    assert match_category_query("algo que no existe") is None
    assert match_category_query("") is None
