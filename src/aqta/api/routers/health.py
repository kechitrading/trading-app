"""Liveness and readiness probes (NFR-001, NFR-002). Unauthenticated, no sensitive data."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aqta.api.deps import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(container: ContainerDep) -> dict[str, str]:
    return {"status": "ok", "mode": container.settings.trading_mode.value}


@router.get("/ready")
async def ready(container: ContainerDep) -> JSONResponse:
    checks = await container.check_ready()
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "checks": checks},
        status_code=200 if ok else 503,
    )
