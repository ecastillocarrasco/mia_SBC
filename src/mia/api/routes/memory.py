"""Control visual de la Memoria Inteligente: encender/apagar, consultar y borrar recuerdos.

Aparte del chat a propósito: el interruptor y el borrado deben ser inmediatos y no depender de
que el LLM entienda una frase — ver requisito explícito del encargo ("control visible, intuitivo
y coherente con la estética de mIA"). El guardado en sí (``recordar``) sigue siendo solo
conversacional: esta ruta nunca crea recuerdos, solo los activa/consulta/borra.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from mia.api.deps import ServicesDep, UserDep, require
from mia.api.schemas import (
    MemoryDeleteResponse,
    MemoryItem,
    MemoryItemsResponse,
    MemorySettingsResponse,
    MemorySettingsUpdate,
)
from mia.auth import Permission
from mia.data.repositories import MemoryRepository

router = APIRouter(prefix="/api/memory", tags=["memoria"], dependencies=[Depends(require(Permission.MEMORIA_USAR))])


def _require_available(services: ServicesDep) -> None:
    if not services.settings.memory.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La Memoria Inteligente no está activada en este despliegue")


@router.get("/settings")
async def get_memory_settings(services: ServicesDep, user: UserDep) -> MemorySettingsResponse:
    """Nunca 404: con la memoria apagada globalmente, el frontend necesita ``available=False``
    para decidir si oculta el control, no un error con el que tropezar al cargar cada mundo."""
    if not services.settings.memory.enabled:
        return MemorySettingsResponse(available=False, enabled=False)
    async with services.db.session() as db:
        enabled = await MemoryRepository(db).is_enabled(user.user_id)
    return MemorySettingsResponse(available=True, enabled=enabled)


@router.put("/settings")
async def set_memory_settings(
    body: MemorySettingsUpdate, services: ServicesDep, user: UserDep
) -> MemorySettingsResponse:
    _require_available(services)
    async with services.db.session() as db:
        await MemoryRepository(db).set_enabled(user.user_id, body.enabled)
    return MemorySettingsResponse(available=True, enabled=body.enabled)


@router.get("/items")
async def list_memory_items(services: ServicesDep, user: UserDep) -> MemoryItemsResponse:
    _require_available(services)
    async with services.db.session() as db:
        repo = MemoryRepository(db)
        enabled = await repo.is_enabled(user.user_id)
        items = await repo.list_memories(user.user_id) if enabled else []
    return MemoryItemsResponse(
        enabled=enabled,
        items=[MemoryItem(id=m.id, content=m.content, created_at=m.created_at.isoformat()) for m in items],
    )


@router.delete("/items/{item_id}")
async def delete_memory_item(item_id: str, services: ServicesDep, user: UserDep) -> MemoryDeleteResponse:
    _require_available(services)
    async with services.db.session() as db:
        deleted = await MemoryRepository(db).delete_memory(user.user_id, item_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese recuerdo")
    return MemoryDeleteResponse(deleted=1)


@router.delete("/items")
async def delete_all_memory_items(services: ServicesDep, user: UserDep) -> MemoryDeleteResponse:
    _require_available(services)
    async with services.db.session() as db:
        count = await MemoryRepository(db).delete_all(user.user_id)
    return MemoryDeleteResponse(deleted=count)
