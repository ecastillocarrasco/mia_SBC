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

from sqlalchemy import select

from mia.api.services import build_graph_client
from mia.data import Database, SourceSyncState
from mia.data.schema import schema_problem
from mia.domains.curriculums.indexer import CvIndexer
from mia.llm import build_llm_provider
from mia.observability import configure_logging
from mia.settings import Settings, get_settings
from mia.sources import SourceDefinition, all_sources
from mia.sources.discovery import discover_calendar_sources
from mia.sources.sharepoint import SharePointClient
from mia.sync.factory import build_portal_client, build_runner, build_sharepoint_client
from mia.sync.runner import SyncMode


async def _list(db: Database, settings: Settings) -> None:
    async with db.session() as session:
        states = {s.source: s for s in (await session.scalars(select(SourceSyncState))).all()}
    for source in all_sources(domains=settings.domains.enabled, portal=bool(settings.sharepoint.portal_site_url)):
        state = states.get(source.key)
        if state is None:
            print(f"{source.key:28} nunca sincronizada")
            continue
        when = state.last_success_at.strftime("%d/%m %H:%M") if state.last_success_at else "—"
        print(f"{source.key:28} {state.status:6} {state.item_count:>7} elementos  último ok {when}")
        if state.last_error:
            print(f"{'':28} error: {state.last_error[:150]}")


async def _check_mailbox(settings: Settings) -> int:
    graph = build_graph_client(settings)
    if graph is None:
        print("—     correo                       buzón sin configurar (MIA_MAIL__MAILBOX) o desactivado")
        return 0
    if settings.mail.mailbox_source == "user":
        print(
            "OK    correo                       cada usuario usa el buzón de su cuenta (MSAL); nada que comprobar aquí"
        )
        return 0
    try:
        await graph.request(
            "GET",
            f"{graph.user_path(settings.mail.mailbox)}/mailFolders/inbox",
            params={"$select": "id,unreadItemCount"},
        )
        print(f"OK    correo                       buzón {settings.mail.mailbox} accesible")
        return 0
    except Exception as exc:
        print(f"FALLA correo                       {str(exc)[:200]}")
        return 1
    finally:
        await graph.aclose()


async def _check(client: SharePointClient, settings: Settings, sources: list[SourceDefinition]) -> int:
    failures = await _check_mailbox(settings)
    portal = build_portal_client(settings)
    for source in sources:
        site_client = portal if source.site == "portal" and portal else client
        try:
            await site_client.current_change_token(source.list_title)
            first: list[dict[str, object]] = await anext(site_client.iter_items(source.list_title, select="ID"), [])
            print(f"OK    {source.key:28} '{source.list_title}' accesible ({len(first)} en la primera página)")
        except Exception as exc:
            failures += 1
            print(f"FALLA {source.key:28} lista '{source.list_title}': {str(exc)[:200]}")
    if portal:
        await portal.aclose()
    return 1 if failures else 0


async def _index_cvs(settings: Settings, db: Database, client: SharePointClient) -> None:
    llm = build_llm_provider(settings.llm)
    indexer = CvIndexer(
        db=db,
        client=client,
        llm=llm,
        embedding_model=settings.curriculums.embedding_model,
        batch=settings.curriculums.index_batch,
        max_bytes=settings.curriculums.max_file_mb * 1024 * 1024,
    )
    try:
        r = await indexer.run(progress=lambda done, total: print(f"  indexando CVs… {done}/{total}", flush=True))
    finally:
        await llm.aclose()
    print(
        f"{'indexación de CVs':28} procesados {r.processed:>5}  indexados {r.indexed:>5}  "
        f"errores {r.failed:>4}  pendientes {r.pending:>5}  {r.statuses}"
    )


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.observability.log_level, settings.observability.log_json)
    db = Database(settings.database_url)
    try:
        if args.list:
            await _list(db, settings)
            return 0
        if problem := await schema_problem(db):
            print(f"\n⚠ {problem}\n", file=sys.stderr)
            return 2
        available = all_sources(domains=settings.domains.enabled, portal=bool(settings.sharepoint.portal_site_url))
        client = build_sharepoint_client(settings)
        if "turnos" in settings.domains.enabled and not args.no_calendars:
            print("Buscando calendarios de departamento (Calendario<Departamento>_AAAA)…", flush=True)
            available = available + await discover_calendar_sources(client)
        sources = [s for s in available if not args.source or s.key in args.source]
        if not sources:
            print("No hay fuentes con ese nombre. Usa --list para verlas.", file=sys.stderr)
            return 2
        if args.check:
            try:
                return await _check(client, settings, sources)
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
                if "curriculums" in settings.domains.enabled and not args.no_index:
                    await _index_cvs(settings, db, client)
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
    parser.add_argument("--check", action="store_true", help="probar el acceso a SharePoint y al correo")
    parser.add_argument("--no-index", action="store_true", help="no indexar CVs tras sincronizar")
    parser.add_argument(
        "--no-calendars", action="store_true", help="no buscar los calendarios de departamento (más rápido)"
    )
    try:
        sys.exit(asyncio.run(_main(parser.parse_args())))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
