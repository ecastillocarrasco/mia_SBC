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

GRACEFUL_SECONDS = 3


async def _serve() -> None:
    settings = get_settings()
    app = create_app(settings)
    configs = [
        uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            log_config=None,
            timeout_graceful_shutdown=GRACEFUL_SECONDS,
        )
    ]
    if settings.compat_port:
        configs.append(
            uvicorn.Config(
                app,
                host=settings.host,
                port=settings.compat_port,
                lifespan="off",
                log_config=None,
                timeout_graceful_shutdown=GRACEFUL_SECONDS,
            )
        )
    servers = [uvicorn.Server(config) for config in configs]
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    # Ctrl+C solo le llega a uno de los servidores: cuando uno termina, se detienen todos.
    # (Antes el otro se quedaba esperando y la consola se quedaba en «Shutting down».)
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for server in servers:
        server.should_exit = True
    await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve())


if __name__ == "__main__":
    main()
