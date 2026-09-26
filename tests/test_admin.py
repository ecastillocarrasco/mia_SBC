from __future__ import annotations

import httpx

from mia.api.services import Services
from mia.auth.providers import DevIdentityProvider
from mia.settings import AuthSettings


async def test_admin_sees_source_status(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/admin/sources")).json()
    keys = {s["source"] for s in body}
    assert {"empleados", "turnos", "vacaciones", "departamentos"} <= keys
    assert all(s["status"] == "never" and s["stale"] for s in body)


async def test_non_admin_is_forbidden(client: httpx.AsyncClient, services: Services) -> None:
    services.identity = DevIdentityProvider(AuthSettings(dev_roles=["mia.responsable"]))
    assert (await client.get("/api/admin/sources")).status_code == 403
