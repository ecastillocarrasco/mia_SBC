"""``python -m mia``: arranque local.

Si ``MIA_COMPAT_PORT`` está definido (p. ej. 5002), el mismo proceso atiende
también ese puerto para que el frontend actual funcione sin cambios en local.
"""

from __future__ import annotations

import asyncio
import contextlib

import uvicorn

from mia.main import create_app
from mia.settings import get_settings


async def _serve() -> None:
    settings = get_settings()
    app = create_app(settings)
    servers = [uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_config=None))]
    if settings.compat_port:
        servers.append(
            uvicorn.Server(
                uvicorn.Config(app, host=settings.host, port=settings.compat_port, lifespan="off", log_config=None)
            )
        )
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve())


if __name__ == "__main__":
    main()
