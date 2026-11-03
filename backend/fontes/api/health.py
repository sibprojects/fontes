import asyncio
from collections.abc import Sequence

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fontes.application.ports.health import HealthCheck

router = APIRouter()


async def _run(check: HealthCheck, limit: float) -> str:
    try:
        async with asyncio.timeout(limit):
            await check.check()
    except TimeoutError:
        return "timeout"
    except Exception as exc:
        return str(exc) or type(exc).__name__
    return "ok"


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    checks: Sequence[HealthCheck] = request.app.state.health_checks
    timeout: float = request.app.state.health_timeout
    results = await asyncio.gather(*(_run(c, timeout) for c in checks))
    statuses = {c.name: result for c, result in zip(checks, results, strict=True)}
    ok = all(result == "ok" for result in results)
    return JSONResponse(
        {"status": "ok" if ok else "fail", "checks": statuses},
        status_code=200 if ok else 503,
    )
