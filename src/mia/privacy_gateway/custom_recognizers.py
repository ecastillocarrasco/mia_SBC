"""Reconocedores españoles que Presidio no cubre con precisión suficiente de fábrica.

Cada uno combina un patrón (forma) con un validador de dígito/letra de control real — nunca solo
expresión regular — para minimizar falsos positivos (p. ej. un número de pedido de 8 cifras no es
un DNI aunque tenga la forma correcta).
"""

from __future__ import annotations

import re
from typing import ClassVar

from presidio_analyzer import Pattern, PatternRecognizer

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}


def _dni_checksum_ok(number: str, letter: str) -> bool:
    try:
        return _DNI_LETTERS[int(number) % 23] == letter.upper()
    except (ValueError, IndexError):
        return False


class SpanishDniNieRecognizer(PatternRecognizer):
    """DNI (8 dígitos + letra) y NIE (X/Y/Z + 7 dígitos + letra), con verificación real del dígito/letra
    de control — no solo la forma. Evita falsos positivos de códigos internos de 8 cifras."""

    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern("DNI", r"\b\d{8}[A-Za-z]\b", 0.4),
        Pattern("NIE", r"\b[XYZxyz]\d{7}[A-Za-z]\b", 0.4),
    ]
    CONTEXT: ClassVar[list[str]] = ["dni", "nie", "documento de identidad", "identificador fiscal"]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="ES_DNI_NIE",
            supported_language="es",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="SpanishDniNieRecognizer",
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        raw = pattern_text.strip().upper()
        letter = raw[-1]
        body = raw[:-1]
        if body and body[0] in _NIE_PREFIX:
            body = _NIE_PREFIX[body[0]] + body[1:]
        if not body.isdigit():
            return False
        return _dni_checksum_ok(body, letter)


class SpanishIbanRecognizer(PatternRecognizer):
    """IBAN español (ES + 22 dígitos) validado con el algoritmo mod-97 real (ISO 7064), no solo la forma."""

    PATTERNS: ClassVar[list[Pattern]] = [Pattern("IBAN_ES", r"\bES\d{2}[ -]?(?:\d[ -]?){20}\b", 0.3)]
    CONTEXT: ClassVar[list[str]] = ["iban", "cuenta", "transferencia", "bancario", "banco"]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="ES_IBAN",
            supported_language="es",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="SpanishIbanRecognizer",
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        compact = re.sub(r"[ -]", "", pattern_text).upper()
        if len(compact) != 24 or not compact.startswith("ES"):
            return False
        rearranged = compact[4:] + compact[:4]
        numeric = "".join(str(int(ch, 36)) if ch.isalpha() else ch for ch in rearranged)
        try:
            return int(numeric) % 97 == 1
        except ValueError:
            return False


class SpanishSocialSecurityRecognizer(PatternRecognizer):
    """Número de afiliación a la Seguridad Social español (12 dígitos, 2 provincia + 8 número + 2 control)."""

    PATTERNS: ClassVar[list[Pattern]] = [Pattern("SS_NUMBER", r"\b\d{2}[ /]?\d{8}[ /]?\d{2}\b", 0.3)]
    CONTEXT: ClassVar[list[str]] = ["seguridad social", "afiliación", "número de afiliación", "ss"]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="ES_SOCIAL_SECURITY",
            supported_language="es",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            name="SpanishSocialSecurityRecognizer",
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        digits = re.sub(r"[ /]", "", pattern_text)
        if len(digits) != 12 or not digits.isdigit():
            return False
        base, control = int(digits[:10]), int(digits[10:])
        return base % 97 == control or (base % 97 == 0 and control == 97)


def build_spanish_recognizers() -> list[PatternRecognizer]:
    """Todos los reconocedores propios en español, listos para registrar en el AnalyzerEngine."""
    return [
        SpanishDniNieRecognizer(),
        SpanishIbanRecognizer(),
        SpanishSocialSecurityRecognizer(),
    ]
