"""Sincronización SharePoint → PostgreSQL.

* ``full``: lee la lista entera, reconstruye la tabla canónica y detecta borrados.
  Toma el change token ANTES de leer, para no perder cambios hechos durante la lectura.
* ``incremental``: aplica solo los cambios del registro de SharePoint desde el último token.
* ``auto``: incremental, salvo que no haya token, haya caducado o toque la completa diaria.

Un error en un elemento no detiene la sincronización: se registra y se continúa.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from mia.data import Database, SourceItem, SourceSyncState
from mia.observability import get_logger
from mia.sources.definitions import SourceDefinition
from mia.sources.mappers.common import MapContext
from mia.sources.pseudonym import Pseudonymizer, mask_ids, pseudonymize_path
from mia.sources.sharepoint import ChangeTokenExpiredError, SharePointClient

log = get_logger(__name__)

_BATCH = 1000


class SyncMode(StrEnum):
    AUTO = "auto"
    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass(slots=True)
class SyncReport:
    source: str
    mode: SyncMode
    status: str = "ok"
    fetched: int = 0
    deleted: int = 0
    rows: int = 0
    item_errors: int = 0
    elapsed_ms: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def _chunks[T](values: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class SyncRunner:
    def __init__(
        self,
        *,
        db: Database,
        client: SharePointClient,
        pseudonymize: Pseudonymizer,
        site_clients: dict[str, SharePointClient] | None = None,
        timezone: str = "Europe/Madrid",
        full_sync_hour: int = 3,
    ) -> None:
        self._db = db
        self._base_client = client
        self._site_clients = {"rrhh": client, **(site_clients or {})}
        self._client = client
        self._pseudonymize = pseudonymize
        self._tz = ZoneInfo(timezone)
        self._full_sync_hour = full_sync_hour
        self._fields: dict[str, set[str]] = {}

    # ------------------------------------------------------------ API
    async def run_all(
        self, sources: list[SourceDefinition], mode: SyncMode = SyncMode.AUTO
    ) -> list[SyncReport]:
        return [await self.run(source, mode) for source in sources]

    async def _with_optional_fields(self, source: SourceDefinition) -> SourceDefinition:
        if not source.optional_fields:
            return source
        if source.list_title not in self._fields:  # una consulta por lista y proceso
            self._fields[source.list_title] = await self._client.field_names(source.list_title)
        existing = self._fields[source.list_title]
        present = [f for f in source.optional_fields if f in existing]
        return replace(source, select=",".join([source.select, *present])) if present else source

    async def run(self, source: SourceDefinition, mode: SyncMode = SyncMode.AUTO) -> SyncReport:
        started = time.perf_counter()
        self._client = self._site_clients.get(source.site, self._base_client)
        state = await self._load_state(source.key)
        effective = self._decide(state, mode)
        report = SyncReport(source=source.key, mode=effective)
        try:
            source = await self._with_optional_fields(source)
            if effective is SyncMode.INCREMENTAL:
                try:
                    await self._incremental(source, state, report)
                except ChangeTokenExpiredError:
                    report.notes.append("token caducado: sincronización completa")
                    report.mode = SyncMode.FULL
                    await self._full(source, report)
            else:
                await self._full(source, report)
        except Exception as exc:
            report.status = "error"
            report.error = str(exc)[:1000]
            log.exception("sync.failed", source=source.key)
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        await self._save_state(source, report)
        log.info(
            "sync.finished",
            source=source.key,
            mode=report.mode.value,
            status=report.status,
            fetched=report.fetched,
            deleted=report.deleted,
            rows=report.rows,
            item_errors=report.item_errors,
            elapsed_ms=report.elapsed_ms,
        )
        return report

    # ------------------------------------------------------------ decisión
    def _decide(self, state: SourceSyncState | None, mode: SyncMode) -> SyncMode:
        if mode is not SyncMode.AUTO:
            if mode is SyncMode.INCREMENTAL and (state is None or not state.change_token):
                return SyncMode.FULL
            return mode
        if state is None or not state.change_token or state.last_full_at is None:
            return SyncMode.FULL
        now_local = datetime.now(self._tz)
        last_full_local = state.last_full_at.astimezone(self._tz)
        due_today = now_local.hour >= self._full_sync_hour and last_full_local.date() < now_local.date()
        if due_today or now_local - last_full_local > timedelta(hours=26):
            return SyncMode.FULL
        return SyncMode.INCREMENTAL

    # ------------------------------------------------------------ modos
    async def _full(self, source: SourceDefinition, report: SyncReport) -> None:
        token = await self._client.current_change_token(source.list_title)
        items: dict[int, dict[str, Any]] = {}
        async for page in self._client.iter_items(
            source.list_title, select=source.select, expand=source.expand
        ):
            for item in page:
                if item.get("ID") is not None:
                    items[int(item["ID"])] = self._sanitize(source, item)
        report.fetched = len(items)
        async with self._db.session() as db:
            await self._upsert_raw(db, source, list(items.items()))
            report.deleted = await self._mark_missing_deleted(db, source, set(items))
            await db.execute(delete(source.model).where(*self._scope(source)))
            report.rows = await self._insert_canonical(db, source, list(items.values()), report)
            await self._set_token(db, source, token, full=True)

    async def _incremental(
        self, source: SourceDefinition, state: SourceSyncState | None, report: SyncReport
    ) -> None:
        assert state is not None and state.change_token  # noqa: S101  (garantizado por _decide)
        changes, token = await self._client.changes_since(source.list_title, state.change_token)
        wanted = sorted(c.item_id for c in changes if not c.deleted)
        fetched = await self._client.items_by_id(
            source.list_title, wanted, select=source.select, expand=source.expand
        )
        items = {int(i["ID"]): self._sanitize(source, i) for i in fetched if i.get("ID") is not None}
        # Cambiado y luego borrado: el registro dice "modificado" pero ya no existe.
        deleted = sorted({c.item_id for c in changes if c.deleted} | (set(wanted) - set(items)))
        touched = sorted(set(items) | set(deleted))
        report.fetched, report.deleted = len(items), len(deleted)
        async with self._db.session() as db:
            await self._upsert_raw(db, source, list(items.items()))
            for chunk in _chunks(deleted, 500):
                await db.execute(
                    update(SourceItem)
                    .where(SourceItem.source == source.key, SourceItem.item_id.in_(chunk))
                    .values(deleted=True, synced_at=datetime.now(UTC))
                )
            owner = getattr(source.model, source.owner_column)
            for chunk in _chunks(touched, 500):
                await db.execute(delete(source.model).where(*self._scope(source), owner.in_(chunk)))
            report.rows = await self._insert_canonical(db, source, list(items.values()), report)
            await self._set_token(db, source, token, full=False)

    # ------------------------------------------------------------ auxiliares
    def _sanitize(self, source: SourceDefinition, item: dict[str, Any]) -> dict[str, Any]:
        clean = dict(item)
        for name in source.sensitive_fields:
            if name in clean:
                clean[name] = self._pseudonymize(clean[name])
        if source.identity_folders:
            person_key = None
            for name in ("FileRef", "FileDirRef"):
                if isinstance(clean.get(name), str):
                    clean[name], key = pseudonymize_path(clean[name], self._pseudonymize)
                    person_key = person_key or key
            for name in ("FileLeafRef", "Title"):
                if isinstance(clean.get(name), str):
                    clean[name] = mask_ids(clean[name])
            clean["_person_key"] = person_key
        return clean

    def _scope(self, source: SourceDefinition) -> list[Any]:
        return [getattr(source.model, column) == value for column, value in source.scope.items()]

    async def _insert_canonical(
        self, db: AsyncSession, source: SourceDefinition, items: list[dict[str, Any]], report: SyncReport
    ) -> int:
        ctx = MapContext(tz=self._tz, pseudonymize=self._pseudonymize, year=source.year)
        rows: list[dict[str, Any]] = []
        for item in items:
            try:
                rows.extend(source.mapper(item, ctx))
            except Exception as exc:
                report.item_errors += 1
                log.warning("sync.item_failed", source=source.key, item_id=item.get("ID"), error=str(exc))
        for chunk in _chunks(rows, _BATCH):
            await db.execute(insert(source.model), list(chunk))
        return len(rows)

    async def _upsert_raw(
        self, db: AsyncSession, source: SourceDefinition, items: list[tuple[int, dict[str, Any]]]
    ) -> None:
        if not items:
            return
        dialect = db.get_bind().dialect.name
        builder: Any = postgresql.insert if dialect == "postgresql" else sqlite.insert
        now = datetime.now(UTC)
        for chunk in _chunks(items, _BATCH):
            stmt = builder(SourceItem).values(
                [
                    {"source": source.key, "item_id": i, "payload": p, "deleted": False, "synced_at": now}
                    for i, p in chunk
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "item_id"],
                set_={
                    "payload": stmt.excluded.payload,
                    "deleted": False,
                    "synced_at": stmt.excluded.synced_at,
                },
            )
            await db.execute(stmt)

    async def _mark_missing_deleted(
        self, db: AsyncSession, source: SourceDefinition, present: set[int]
    ) -> int:
        existing = set(
            (
                await db.scalars(
                    select(SourceItem.item_id).where(
                        SourceItem.source == source.key, SourceItem.deleted.is_(False)
                    )
                )
            ).all()
        )
        missing = sorted(existing - present)
        for chunk in _chunks(missing, 500):
            await db.execute(
                update(SourceItem)
                .where(SourceItem.source == source.key, SourceItem.item_id.in_(chunk))
                .values(deleted=True, synced_at=datetime.now(UTC))
            )
        return len(missing)

    async def _set_token(self, db: AsyncSession, source: SourceDefinition, token: str, *, full: bool) -> None:
        state = await db.get(SourceSyncState, source.key) or SourceSyncState(source=source.key)
        state.change_token = token
        now = datetime.now(UTC)
        if full:
            state.last_full_at = now
        else:
            state.last_incremental_at = now
        db.add(state)

    async def _load_state(self, key: str) -> SourceSyncState | None:
        async with self._db.session() as db:
            return await db.get(SourceSyncState, key)

    async def _save_state(self, source: SourceDefinition, report: SyncReport) -> None:
        async with self._db.session() as db:
            state = await db.get(SourceSyncState, source.key) or SourceSyncState(source=source.key)
            now = datetime.now(UTC)
            state.last_duration_ms = report.elapsed_ms
            state.last_changes = report.fetched + report.deleted
            if report.status == "ok":
                state.status = "ok"
                state.last_success_at = now
                state.last_error = None
            else:
                state.status = "error"
                state.last_error = report.error
                state.last_error_at = now
            state.item_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(SourceItem)
                    .where(SourceItem.source == source.key, SourceItem.deleted.is_(False))
                )
                or 0
            )
            db.add(state)
