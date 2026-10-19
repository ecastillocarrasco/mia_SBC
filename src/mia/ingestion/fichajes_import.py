"""Importación manual del Excel de fichajes de Conectia — solo entornos de prueba.

    python -m mia.ingestion.fichajes_import                        # data/fichajes_conectia/
    python -m mia.ingestion.fichajes_import --path otra/ruta/

Cuando exista la API real de Conectia, este importador deja de hacer falta — ver
``mia.connectors.a3.TimeClockConnector`` y el docstring de ``mia.modules.rrhh.fichajes.importer``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from mia.data import Database
from mia.modules.rrhh.fichajes.importer import import_directory
from mia.observability import configure_logging
from mia.settings import get_settings

DEFAULT_PATH = Path("data/fichajes_conectia")


async def _main(path: Path) -> int:
    settings = get_settings()
    configure_logging(settings.observability.log_level, settings.observability.log_json)
    if not path.is_dir():
        print(f"No existe el directorio {path}", file=sys.stderr)
        return 2
    files = sorted(path.glob("*.xlsx"))
    if not files:
        print(f"No hay ningún .xlsx en {path}", file=sys.stderr)
        return 2
    db = Database(settings.database_url)
    try:
        report = await import_directory(db, path, timezone=settings.timezone, now=datetime.now(UTC))
    finally:
        await db.dispose()

    print(f"Ficheros procesados:  {report.files}")
    print(f"Filas leídas:         {report.rows_read}")
    print(f"Marcas importadas:    {report.imported}")
    if report.period:
        lo, hi = report.period
        print(f"Periodo:              {lo.isoformat()} – {hi.isoformat()}")
    if report.unmatched:
        print(f"\nSin persona reconocida ({report.unmatched_rows} filas):")
        for name, count in sorted(report.unmatched.items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {name}")
    if report.ambiguous:
        print(f"\nMás de una persona coincide ({report.ambiguous_rows} filas):")
        for name, count in sorted(report.ambiguous.items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {name}")
    return 1 if (report.unmatched or report.ambiguous) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa los Excel de fichajes de Conectia")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH, help="directorio con los .xlsx")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.path)))


if __name__ == "__main__":
    main()
