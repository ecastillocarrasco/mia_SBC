"""Sirve el frontend actual desde su ubicación (sin copiarlo al proyecto)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mia.settings import FrontendSettings


def mount_frontend(app: FastAPI, settings: FrontendSettings) -> None:
    html = settings.legacy_html
    if html is not None and html.is_file():

        @app.get("/mia", include_in_schema=False)
        async def legacy_front() -> FileResponse:
            return FileResponse(html, media_type="text/html; charset=utf-8")

    assets = settings.assets_dir
    if assets is not None and assets.is_dir():
        app.mount("/mia-assets", StaticFiles(directory=assets), name="mia-assets")
