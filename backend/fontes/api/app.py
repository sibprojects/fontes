from collections.abc import Sequence

from fastapi import FastAPI

from fontes.api import health
from fontes.application.ports.health import HealthCheck


def create_app(checks: Sequence[HealthCheck], health_timeout: float) -> FastAPI:
    app = FastAPI(title="Fontes")
    app.state.health_checks = list(checks)
    app.state.health_timeout = health_timeout
    app.include_router(health.router)
    return app
