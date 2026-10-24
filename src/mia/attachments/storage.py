"""Backend de almacenamiento para adjuntos temporales.

La interfaz StorageBackend permite migrar de local a Azure Blob sin
reescribir la lógica de adjuntos.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    async def write(self, path: str, content: bytes) -> None: ...
    async def read(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...


class LocalStorage:
    """Almacenamiento en disco local. Para dev/test; la interfaz es idéntica a Azure."""

    def __init__(self, base_path: Path) -> None:
        self._base = base_path
        base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        # Prevenir path traversal
        base = self._base.resolve()
        resolved = (base / path).resolve()
        if resolved == base or base not in resolved.parents:
            raise ValueError(f"Ruta no permitida: {path}")
        return resolved

    async def write(self, path: str, content: bytes) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, content)

    async def read(self, path: str) -> bytes:
        target = self._resolve(path)
        return await asyncio.to_thread(target.read_bytes)

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.exists():
            await asyncio.to_thread(target.unlink, missing_ok=True)

    async def exists(self, path: str) -> bool:
        target = self._resolve(path)
        return await asyncio.to_thread(target.exists)


class AzureBlobStorage:
    """Almacenamiento privado compartido entre réplicas usando identidad administrada."""

    def __init__(self, account_url: str, container: str) -> None:
        from azure.identity.aio import DefaultAzureCredential  # noqa: PLC0415
        from azure.storage.blob.aio import BlobServiceClient  # noqa: PLC0415

        self._credential = DefaultAzureCredential()
        self._service = BlobServiceClient(account_url, credential=self._credential)
        self._container = self._service.get_container_client(container)

    async def write(self, path: str, content: bytes) -> None:
        await self._container.get_blob_client(path).upload_blob(content, overwrite=True)

    async def read(self, path: str) -> bytes:
        stream = await self._container.get_blob_client(path).download_blob()
        return await stream.readall()

    async def delete(self, path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415

        with suppress(ResourceNotFoundError):
            await self._container.get_blob_client(path).delete_blob(delete_snapshots="include")

    async def exists(self, path: str) -> bool:
        return await self._container.get_blob_client(path).exists()

    async def aclose(self) -> None:
        await self._service.close()
        await self._credential.close()


def attachment_path(user_id: str, attachment_id: str) -> str:
    """Ruta relativa dentro del storage: user_id/attachment_id/raw."""
    safe_user = user_id.replace("/", "_").replace("..", "_")[:64]
    return f"{safe_user}/{attachment_id}/raw"
