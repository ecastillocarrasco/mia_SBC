from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from mia.api.services import Services
from mia.auth.providers import DevIdentityProvider
from mia.data import Report
from mia.settings import AuthSettings


async def _report(services: Services, tmp_path: Path, *, expires_in: timedelta) -> str:
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF-1.4 prueba")
    async with services.db.session() as db:
        db.add(
            Report(
                id="r1",
                user_id="dev-user",
                title="T",
                format="pdf",
                file_name="T.pdf",
                path=str(path),
                expires_at=datetime.now(UTC) + expires_in,
            )
        )
    return "/api/reports/r1"


async def test_owner_downloads_report(client: httpx.AsyncClient, services: Services, tmp_path: Path) -> None:
    url = await _report(services, tmp_path, expires_in=timedelta(hours=1))
    response = await client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


async def test_other_user_cannot_download(client: httpx.AsyncClient, services: Services, tmp_path: Path) -> None:
    url = await _report(services, tmp_path, expires_in=timedelta(hours=1))
    services.identity = DevIdentityProvider(AuthSettings(dev_user_id="otra-persona"))
    assert (await client.get(url)).status_code == 404


async def test_expired_report_is_gone(client: httpx.AsyncClient, services: Services, tmp_path: Path) -> None:
    url = await _report(services, tmp_path, expires_in=timedelta(hours=-1))
    assert (await client.get(url)).status_code == 410
