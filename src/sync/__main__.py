"""Sincronización desde la línea de comandos.

    python -m mia.sync                       # auto: incremental o completa según toque
    python -m mia.sync --full                # completa de todas las fuentes
    python -m mia.sync --source turnos       # una fuente concreta
    python -m mia.sync --loop 300            # local: repetir cada 5 minutos
    python -m mia.sync --list                # ver fuentes y su estado
    python -m mia.sync --check               # probar la conexión con cada lista, sin escribir

En Azure lo ejecuta un Container Apps Job programado.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from mia.sources import all_sources
from mia.sources.sharepoint import SharePointClient
from mia.sync.factory import build_runner, build_sharepoint_client
from mia.sync.runner import SyncMode
from sqlalchemy import select

from mia.data import Database, SourceSyncState
from mia.observability import configure_logging
from mia.settings import get_settings


async def _list(db: Database) -> None:
    async with db.session() as session:
        states = {s.source: s for s in (await session.scalars(select(SourceSyncState))).all()}
    for source in all_sources():
        state = states.get(source.key)
        if state is None:
            print(f"{source.key:28} nunca sincronizada")
            continue
        when = state.last_success_at.strftime("%d/%m %H:%M") if state.last_success_at else "—"
        print(f"{source.key:28} {state.status:6} {state.item_count:>7} elementos  último ok {when}")
        if state.last_error:
            print(f"{'':28} error: {state.last_error[:150]}")


async def _check(client: SharePointClient) -> int:
    failures = 0
    for source in all_sources():
        try:
            await client.current_change_token(source.list_title)
            first: list[dict[str, object]] = await anext(client.iter_items(source.list_title, select="ID"), [])
            print(f"OK    {source.key:28} '{source.list_title}' accesible ({len(first)} en la primera página)")
        except Exception as exc:
            failures += 1
            print(f"FALLA {source.key:28} lista '{source.list_title}': {str(exc)[:200]}")
    return 1 if failures else 0


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.observability.log_level, settings.observability.log_json)
    db = Database(settings.database_url)
    try:
        if args.list:
            await _list(db)
            return 0
        sources = [s for s in all_sources() if not args.source or s.key in args.source]
        if not sources:
            print("No hay fuentes con ese nombre. Usa --list para verlas.", file=sys.stderr)
            return 2
        client = build_sharepoint_client(settings)
        if args.check:
            try:
                return await _check(client)
            finally:
                await client.aclose()
        runner = build_runner(settings, db, client)
        mode = SyncMode.FULL if args.full else SyncMode.AUTO
        try:
            while True:
                reports = await runner.run_all(sources, mode)
                for r in reports:
                    extra = f"  {r.error[:200]}" if r.error else ""
                    print(
                        f"{r.source:28} {r.mode.value:11} {r.status:5} leídos {r.fetched:>6}  "
                        f"borrados {r.deleted:>5}  filas {r.rows:>7}  {r.elapsed_ms:>6} ms{extra}"
                    )
                if not args.loop:
                    return 0 if all(r.status == "ok" for r in reports) else 1
                mode = SyncMode.AUTO
                await asyncio.sleep(args.loop)
        finally:
            await client.aclose()
    finally:
        await db.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza SharePoint con la base de datos de mIA")
    parser.add_argument("--full", action="store_true", help="sincronización completa")
    parser.add_argument("--source", action="append", help="solo esta fuente (repetible)")
    parser.add_argument("--loop", type=int, default=0, help="repetir cada N segundos")
    parser.add_argument("--list", action="store_true", help="mostrar fuentes y estado")
    parser.add_argument("--check", action="store_true", help="probar el acceso a SharePoint sin escribir")
    try:
        sys.exit(asyncio.run(_main(parser.parse_args())))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
