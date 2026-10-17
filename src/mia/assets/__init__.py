"""Recursos corporativos incluidos en el paquete (logo para informes y documentos)."""

from __future__ import annotations

from pathlib import Path

LOGO = Path(__file__).with_name("sunset_beach_club_logo.png")


def resolve_logo(configured: Path | None) -> Path:
    """El logo configurado (MIA_REPORTS__LOGO_PATH) o, por defecto, el de Sunset Beach Club incluido."""
    if configured and configured.is_file():
        return configured
    if not LOGO.is_file():
        raise FileNotFoundError(
            "Falta el logotipo corporativo obligatorio de Sunset Beach Club: "
            f"{LOGO}. Informe cancelado; no se permite exportar sin marca."
        )
    return LOGO
