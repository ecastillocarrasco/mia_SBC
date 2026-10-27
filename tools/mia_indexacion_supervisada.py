"""mIA SBC: supervisor de lotes de NOMINAS sobre el indexador CONTROLADO existente.

Nunca invoca SyncRunner, ejecuta migraciones ni limpia indices globales.
Predeterminado: simulacion de solo lectura. Requiere dos banderas para escrituras.
No usa, muestra ni registra identificadores de empleados ni contenido documental.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import inspect
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

POLICY = "nominas_min_v1"
ORIGINAL_SCRIPT_SHA256 = "158be654f8e7c6b7148764d5078a68e0b27db54a5bf180dfce459df47190c60c"
EXPECTED_HISTORICAL_OK = 8000  # Base confirmada por la auditoria de 2026-10-15.
PROGRESS_RE = re.compile(r"^\d+/\d+ procesado; estado=(ok|empty|unsupported|too_large|error|exception)$")
COUNT_RE = re.compile(r"Candidatos lote:\s*(\d+)")
SUMMARY_RE = re.compile(r"^RESUMEN:\s*(\{.*\})$")
STOP_STATUSES = {"error", "exception", "too_large", "empty", "unsupported"}


class SafetyStop(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    pending: int
    new_policy_ok: int
    new_policy_with_vectors: int
    historical_ok: int
    all_with_vectors: int


def parse_child_output(lines: list[str]) -> tuple[int | None, dict[str, int] | None]:
    """Only parse controlled status fields; never persist raw subprocess output."""
    candidates = None
    summary = None
    for line in lines:
        found = COUNT_RE.search(line)
        if found:
            candidates = int(found.group(1))
        found = SUMMARY_RE.fullmatch(line.strip())
        if found:
            try:
                raw = ast.literal_eval(found.group(1))
            except (SyntaxError, ValueError):
                continue
            if isinstance(raw, dict) and all(
                isinstance(k, str) and k in (STOP_STATUSES | {"ok"}) and type(v) is int and v >= 0
                for k, v in raw.items()
            ):
                summary = raw
    return candidates, summary


def check_batch_result(
    before: Snapshot,
    after: Snapshot,
    *,
    expected_candidates: int,
    reported_candidates: int | None,
    summary: dict[str, int] | None,
    return_code: int,
) -> None:
    """Strong stop conditions: only fresh records, no historical or cross-domain mutation."""
    if return_code != 0:
        raise SafetyStop("El indexador ha devuelto un error; se ha detenido la ejecucion.")
    if reported_candidates != expected_candidates:
        raise SafetyStop("Cambio de candidatos durante el lote: posible sincronizacion concurrente.")
    if summary is None or sum(summary.values()) != expected_candidates:
        raise SafetyStop("Resultado incompleto o no interpretable del indexador.")
    if any(summary.get(k, 0) for k in STOP_STATUSES):
        raise SafetyStop("Existe un documento no procesado como 'ok'; revisar antes de reanudar.")
    succeeded = summary.get("ok", 0)
    if succeeded <= 0:
        raise SafetyStop("No hubo progreso verificable en el lote.")
    if after.historical_ok != before.historical_ok:
        raise SafetyStop("Cambiaron los registros historicos: detener y auditar.")
    deltas = (
        after.new_policy_ok - before.new_policy_ok,
        after.new_policy_with_vectors - before.new_policy_with_vectors,
        after.all_with_vectors - before.all_with_vectors,
        before.pending - after.pending,
    )
    if any(delta != succeeded for delta in deltas):
        raise SafetyStop("Descuadre de contadores de privacidad, vectores o pendientes. No continuar hasta investigar.")


def validate_config(settings, script_path: Path) -> None:
    from sqlalchemy.engine import make_url

    from mia.modules.rrhh.document_indexing import DocumentIndexer
    from mia.modules.rrhh.payroll_embedding_privacy import (
        PAYROLL_EMBEDDING_POLICY_VERSION,
        project_payroll_embedding,
    )

    if not script_path.is_file():
        raise SafetyStop("Falta tools/mia_index_lote_controlado.py (script existente).")
    checksum = hashlib.sha256(script_path.read_bytes()).hexdigest()
    if checksum != ORIGINAL_SCRIPT_SHA256:
        raise SafetyStop("El script de lotes difiere de la version auditada. No ejecutar automaticamente.")
    url = make_url(settings.database_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.database != "mia"
        or (url.host or "").lower() not in {"localhost", "127.0.0.1", "::1"}
        or (url.port or 5432) != 5432
    ):
        raise SafetyStop("Solo se permite PostgreSQL local en la BD mia, puerto 5432.")
    if not (settings.privacy_gateway.enabled and not settings.privacy_gateway.fail_open):
        raise SafetyStop("Privacy Gateway debe estar activado y FAIL_OPEN=false.")
    if not settings.privacy_gateway.vault_key.get_secret_value():
        raise SafetyStop("Token Vault sin clave propia.")
    if not settings.data.index_sensitive_content:
        raise SafetyStop("Indexacion sensible no activada.")
    target = urlsplit(str(settings.llm.base_url))
    if target.scheme != "https" or target.hostname != "api.openai.com":
        raise SafetyStop("Endpoint de embeddings no coincide con el autorizado (api.openai.com).")
    if PAYROLL_EMBEDDING_POLICY_VERSION != POLICY:
        raise SafetyStop("La version de minimizacion ha cambiado.")
    source = inspect.getsource(DocumentIndexer._index_one)
    if "project_payroll_embedding(chunk)" not in source or 'self._domain == "nominas"' not in source:
        raise SafetyStop("El DocumentIndexer no parece aplicar la proyeccion privada de nominas.")
    test = "Maria Garcia Lopez DNI 12345678Z IBAN ES9121000418450200051332 Cocina 2500 euros"
    projected = project_payroll_embedding(test)
    if any(term in projected for term in ("Maria", "12345678", "ES9121", "Cocina", "2500")):
        raise SafetyStop("Fallo en la prueba de no filtracion de la proyeccion sintetica.")


async def snapshot(db, *, size: int) -> tuple[Snapshot, int, bool]:
    """SELECT only; verifies that next candidate set excludes previously indexed OK rows."""
    # Reuse original selector, rather than duplicating its candidate logic.
    from mia_index_lote_controlado import _candidate_query
    from sqlalchemy import and_, func, or_, select, text

    from mia.data import HrDocumentChunk, HrDocumentText

    async with db.session() as session:
        name = await session.scalar(text("SELECT current_database()"))
        if name != "mia":
            raise SafetyStop("Base de datos inesperada.")
        marker = "%embeddings=" + POLICY + "%"
        base_new = (
            (HrDocumentText.domain == "nominas") & (HrDocumentText.status == "ok") & HrDocumentText.detail.like(marker)
        )
        new_ok = await session.scalar(select(func.count()).select_from(HrDocumentText).where(base_new))
        new_with_vectors = await session.scalar(
            select(func.count(func.distinct(HrDocumentText.document_id)))
            .select_from(HrDocumentText)
            .join(
                HrDocumentChunk,
                and_(
                    HrDocumentChunk.domain == HrDocumentText.domain,
                    HrDocumentChunk.document_id == HrDocumentText.document_id,
                ),
            )
            .where(base_new)
        )
        old_ok = await session.scalar(
            select(func.count())
            .select_from(HrDocumentText)
            .where(
                HrDocumentText.domain == "nominas",
                HrDocumentText.status == "ok",
                or_(HrDocumentText.detail.is_(None), ~HrDocumentText.detail.like(marker)),
            )
        )
        with_vectors = await session.scalar(
            select(func.count(func.distinct(HrDocumentChunk.document_id))).where(HrDocumentChunk.domain == "nominas")
        )
        pending = await session.scalar(
            select(func.count()).select_from(_candidate_query("nominas").order_by(None).subquery())
        )
        candidates = (await session.scalars(_candidate_query("nominas").limit(size))).all()
        document_ids = [item.sp_id for item in candidates]
        historical_candidate = False
        if document_ids:
            exists = await session.scalar(
                select(func.count())
                .select_from(HrDocumentText)
                .where(
                    HrDocumentText.domain == "nominas",
                    HrDocumentText.document_id.in_(document_ids),
                    HrDocumentText.status == "ok",
                )
            )
            historical_candidate = bool(exists)
        return (
            Snapshot(
                int(pending or 0),
                int(new_ok or 0),
                int(new_with_vectors or 0),
                int(old_ok or 0),
                int(with_vectors or 0),
            ),
            len(candidates),
            historical_candidate,
        )


async def run_child(script: Path, *, size: int) -> tuple[int, int | None, dict[str, int] | None]:
    cmd = [sys.executable, str(script), "--domain", "nominas", "--limit", str(size), "--execute"]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    lines: list[str] = []

    async def read_and_filter():
        assert process.stdout is not None
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if COUNT_RE.search(line) or SUMMARY_RE.fullmatch(line):
                lines.append(line)
            if PROGRESS_RE.fullmatch(line):
                # Show only ordinal and fixed status; never employee name or document ID.
                print(line, flush=True)

    try:
        await asyncio.wait_for(read_and_filter(), timeout=1800)
        rc = await asyncio.wait_for(process.wait(), timeout=15)
    except (TimeoutError, asyncio.CancelledError, KeyboardInterrupt):
        process.kill()
        await process.wait()
        raise SafetyStop("Interrumpido/tiempo agotado; comprobar estado antes de reanudar.")
    return rc, *parse_child_output(lines)


def log_safe(
    root: Path, *, batch: int, before: Snapshot, after: Snapshot, summary: dict[str, int] | None, outcome: str
) -> None:
    folder = root / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / "mia_indexacion_nominas_supervisada.jsonl"
    record = {
        "at_utc": datetime.now(UTC).isoformat(),
        "domain": "nominas",
        "policy": POLICY,
        "batch": batch,
        "before": asdict(before),
        "after": asdict(after),
        "statuses": summary,
        "outcome": outcome,
    }
    with destination.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


async def main(args) -> int:
    from mia.data import Database
    from mia.settings import get_settings

    root = Path(__file__).resolve().parent.parent
    script = root / "tools" / "mia_index_lote_controlado.py"
    validate_config(get_settings(), script)
    db = Database(get_settings().database_url)
    try:
        before, available, historical_candidate = await snapshot(db, size=args.batch_size)
        print(f"PREFLIGHT OK | politica={POLICY} | lotes_max={args.max_batches} | documentos/lote={args.batch_size}")
        print(f"BD=mia | pendientes_elegibles={before.pending} | siguientes_candidatos={available}")
        print(
            f"Nuevos_politica={before.new_policy_ok} | nuevos_con_vectores={before.new_policy_with_vectors} "
            f"| historicos_no_migrados={before.historical_ok} | vectores_totales={before.all_with_vectors}"
        )
        if before.historical_ok != EXPECTED_HISTORICAL_OK:
            raise SafetyStop("El numero de indices historicos cambio respecto a la referencia aprobada.")
        if before.new_policy_ok != before.new_policy_with_vectors:
            raise SafetyStop("Hay indices con nueva politica sin vectores.")
        if historical_candidate:
            raise SafetyStop("El siguiente lote contiene documentos previamente OK; no migrar historicos.")
        if not args.execute:
            print("SIMULACION: sin descargas, embeddings ni escrituras PostgreSQL.")
            return 0
        if not args.authorize_real_documents:
            raise SafetyStop("Para ejecutar documentos reales falta --authorize-real-documents.")
        if args.max_batches > 1:
            print("AVISO: supervision secuencial; detener con Ctrl+C entre documentos si procede.")
        total_ok = 0
        for batch in range(1, args.max_batches + 1):
            before, available, historical_candidate = await snapshot(db, size=args.batch_size)
            if before.historical_ok != EXPECTED_HISTORICAL_OK or historical_candidate:
                raise SafetyStop("Cambio en indices historicos/candidatos: detenida la ejecucion.")
            if before.new_policy_ok != before.new_policy_with_vectors:
                raise SafetyStop("Inconsistencia de version y vectores antes del lote.")
            if available == 0:
                print("Sin documentos elegibles. Finalizado.")
                break
            print(f"LOTE {batch}/{args.max_batches}: ejecutando {available} documento(s)...", flush=True)
            rc, reported, summary = await run_child(script, size=args.batch_size)
            after, _, _ = await snapshot(db, size=args.batch_size)
            try:
                check_batch_result(
                    before,
                    after,
                    expected_candidates=available,
                    reported_candidates=reported,
                    summary=summary,
                    return_code=rc,
                )
            except SafetyStop:
                log_safe(root, batch=batch, before=before, after=after, summary=summary, outcome="STOP_NEEDS_REVIEW")
                raise
            log_safe(root, batch=batch, before=before, after=after, summary=summary, outcome="OK")
            total_ok += summary.get("ok", 0) if summary else 0
            print(
                f"LOTE {batch} OK | total nuevos={after.new_policy_ok} "
                f"| historicos={after.historical_ok} | pendientes={after.pending}"
            )
            if batch < args.max_batches:
                await asyncio.sleep(args.pause_seconds)
        print(
            f"FINALIZADO: nuevos documentos OK en esta ejecucion={total_ok}. "
            "No se ha ejecutado SyncRunner ni migracion historica."
        )
        return 0
    finally:
        await db.dispose()


def entrypoint():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--pause-seconds", type=int, default=5)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize-real-documents", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 20:
        parser.error("--batch-size solo puede estar entre 1 y 20.")
    if not 1 <= args.max_batches <= 5:
        parser.error("--max-batches solo puede estar entre 1 y 5.")
    if not 2 <= args.pause_seconds <= 600:
        parser.error("--pause-seconds debe estar entre 2 y 600.")
    try:
        raise SystemExit(asyncio.run(main(args)))
    except (SafetyStop, Exception) as exc:
        # Only display a stable safety message for expected failures, never raw SQL/logs/PII.
        if isinstance(exc, SafetyStop):
            print(f"BLOQUEADO: {exc}", file=sys.stderr)
        else:
            print(
                f"BLOQUEADO: incidencia no prevista ({type(exc).__name__}). No reintentar sin revisar.", file=sys.stderr
            )
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("INTERRUMPIDO: comprueba la auditoria antes de reanudar.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    entrypoint()
