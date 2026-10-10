"""AttachmentService: gestiona el ciclo de vida de adjuntos temporales."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mia.attachments.intelligence import (
    build_attachment_context,
    classify_content_type,
    get_attachment_summary,
    process_attachment,
)
from mia.attachments.model import (
    AttachmentContent,
    AttachmentRef,
    AttachmentRecord,
    AttachmentScope,
    AttachmentStatus,
)
from mia.attachments.storage import LocalStorage, StorageBackend, attachment_path
from mia.attachments.validation import sanitize_filename, sha256_hex, validate
from mia.observability import get_logger

if TYPE_CHECKING:
    from mia.llm import LLMProvider

log = get_logger(__name__)

_BYTES_PER_MB = 1024 * 1024


class AttachmentService:
    """Servicio central de adjuntos.

    Almacena registros en memoria (scope = conversación).
    Un proceso de limpieza periódico expira los registros vencidos.
    """

    def __init__(
        self,
        *,
        storage: StorageBackend,
        llm: "LLMProvider | None",
        max_files: int = 10,
        max_file_mb: int = 25,
        retention_hours: int = 24,
        vision_enabled: bool = True,
    ) -> None:
        self._storage = storage
        self._llm = llm
        self._max_files = max_files
        self._max_bytes = max_file_mb * _BYTES_PER_MB
        self._retention_hours = retention_hours
        self._vision_enabled = vision_enabled
        self._records: dict[str, AttachmentRecord] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    # ── Upload ──────────────────────────────────────────────────────────

    async def upload(
        self,
        content: bytes,
        filename: str,
        declared_mime: str,
        user_id: str,
        session_id: str | None,
        tenant_id: str = "default",
    ) -> AttachmentRecord:
        """Valida, almacena y procesa un archivo. Devuelve el registro resultante."""
        from mia.diagnostics import EventStage, EventStatus, emit as diag_emit  # noqa: PLC0415

        diag_emit(EventStage.ATTACHMENT_RECEIVED, data={
            "filename": filename,
            "size": len(content),
            "declared_mime": declared_mime,
        })

        # Validar
        diag_emit(EventStage.ATTACHMENT_VALIDATION_START)
        safe_name = sanitize_filename(filename)
        result = validate(content, safe_name, declared_mime, self._max_bytes)
        if not result.ok:
            diag_emit(EventStage.ATTACHMENT_VALIDATION_COMPLETE, status=EventStatus.ERROR, data={"error": result.error})
            record = self._make_error_record(safe_name, declared_mime, user_id, session_id, tenant_id, result.error)
            return record

        diag_emit(EventStage.ATTACHMENT_VALIDATION_COMPLETE, status=EventStatus.SUCCESS, data={
            "detected_mime": result.detected_mime,
        })

        attachment_id = self._new_id()
        now = datetime.now(UTC)
        record = AttachmentRecord(
            attachment_id=attachment_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            original_filename=safe_name,
            mime_type=declared_mime,
            detected_mime_type=result.detected_mime,
            extension=Path(safe_name).suffix.lower(),
            size_bytes=len(content),
            created_at=now,
            expires_at=now + timedelta(hours=self._retention_hours),
            status=AttachmentStatus.VALIDATING,
            content_type=classify_content_type(result.detected_mime),
            sha256=sha256_hex(content),
            scope=AttachmentScope.CONVERSATION,
        )

        # Deduplicación por hash dentro del mismo usuario/sesión
        dup = self._find_duplicate(record)
        if dup is not None:
            log.info("attachment.deduplicated", attachment_id=dup.attachment_id)
            return dup

        # Almacenar
        storage_loc = attachment_path(user_id, attachment_id)
        await self._storage.write(storage_loc, content)
        record.storage_location = storage_loc
        self._records[attachment_id] = record

        # Procesar
        diag_emit(EventStage.ATTACHMENT_PROCESSING_START, data={"attachment_id": attachment_id})
        await process_attachment(record, content, self._llm, self._vision_enabled)
        diag_emit(
            EventStage.ATTACHMENT_PROCESSING_COMPLETE,
            data=get_attachment_summary(record),
            status=EventStatus.SUCCESS if record.status == AttachmentStatus.READY else EventStatus.ERROR,
        )

        log.info(
            "attachment.ready",
            attachment_id=attachment_id,
            filename=safe_name,
            content_type=record.content_type,
            duration_ms=record.processing_duration_ms,
        )
        return record

    # ── Retrieve ────────────────────────────────────────────────────────

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        r = self._records.get(attachment_id)
        if r and r.status == AttachmentStatus.EXPIRED:
            return None
        return r

    def get_for_user(self, attachment_id: str, user_id: str) -> AttachmentRecord | None:
        """Recupera un adjunto garantizando que pertenece al usuario."""
        r = self.get(attachment_id)
        if r is None:
            return None
        if r.user_id != user_id:
            log.warning("attachment.unauthorized_access", attachment_id=attachment_id, user_id=user_id)
            return None
        return r

    def load_content(self, attachment_id: str, user_id: str) -> AttachmentContent | None:
        r = self.get_for_user(attachment_id, user_id)
        return r.content if r else None

    def build_context(self, attachment_id: str, user_id: str) -> str:
        r = self.get_for_user(attachment_id, user_id)
        if r is None:
            return f"[Adjunto {attachment_id} no disponible]"
        return build_attachment_context(r)

    def to_ref(self, record: AttachmentRecord) -> AttachmentRef:
        return AttachmentRef(
            attachment_id=record.attachment_id,
            filename=record.original_filename,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            status=record.status,
        )

    # ── Delete / Expire ─────────────────────────────────────────────────

    async def delete(self, attachment_id: str, user_id: str) -> bool:
        r = self.get_for_user(attachment_id, user_id)
        if r is None:
            return False
        await self._storage.delete(r.storage_location)
        del self._records[attachment_id]
        return True

    async def expire_old(self) -> int:
        """Elimina adjuntos vencidos. Devuelve el número eliminado."""
        from mia.diagnostics import EventStage, emit as diag_emit  # noqa: PLC0415

        now = datetime.now(UTC)
        expired_ids = [aid for aid, r in self._records.items() if r.expires_at <= now]
        for aid in expired_ids:
            r = self._records[aid]
            try:
                await self._storage.delete(r.storage_location)
            except Exception:  # noqa: BLE001
                pass
            r.status = AttachmentStatus.EXPIRED
            del self._records[aid]
            diag_emit(EventStage.ATTACHMENT_EXPIRED, data={"attachment_id": aid, "filename": r.original_filename})
        if expired_ids:
            log.info("attachment.expired_batch", count=len(expired_ids))
        return len(expired_ids)

    def start_cleanup(self, interval_seconds: float = 3600.0) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_seconds))

    async def _cleanup_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.expire_old()
            except Exception as exc:  # noqa: BLE001
                log.warning("attachment.cleanup_error", error=str(exc))

    async def aclose(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()

    # ── Helpers ─────────────────────────────────────────────────────────

    def _new_id(self) -> str:
        return uuid.uuid4().hex

    def _find_duplicate(self, candidate: AttachmentRecord) -> AttachmentRecord | None:
        for r in self._records.values():
            if (
                r.user_id == candidate.user_id
                and r.sha256 == candidate.sha256
                and r.status == AttachmentStatus.READY
            ):
                return r
        return None

    def _make_error_record(
        self,
        filename: str,
        mime: str,
        user_id: str,
        session_id: str | None,
        tenant_id: str,
        error: str,
    ) -> AttachmentRecord:
        now = datetime.now(UTC)
        r = AttachmentRecord(
            attachment_id=self._new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            original_filename=filename,
            mime_type=mime,
            detected_mime_type="",
            extension="",
            size_bytes=0,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            status=AttachmentStatus.ERROR,
            error_message=error,
        )
        return r

    @classmethod
    def build(cls, settings: Any, llm: "LLMProvider | None") -> "AttachmentService":
        from pathlib import Path  # noqa: PLC0415

        att = settings.attachments
        storage = LocalStorage(Path(att.temp_path))
        return cls(
            storage=storage,
            llm=llm,
            max_files=att.max_files,
            max_file_mb=att.max_file_mb,
            retention_hours=att.retention_hours,
            vision_enabled=att.vision_enabled,
        )
