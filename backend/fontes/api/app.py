from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from fontes.api import health
from fontes.application.ports.health import HealthCheck

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    checks: Sequence[HealthCheck],
    health_timeout: float,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="Fontes", lifespan=lifespan)
    app.state.health_checks = list(checks)
    app.state.health_timeout = health_timeout
    app.include_router(health.router)
    return app
