"""FastAPI dependencies: container access, API-token auth and the MFA (TOTP) hook."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aqta.api.container import Container
from aqta.core.errors import AuthError

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def verify_mfa(request: Request, container: ContainerDep) -> None:
    """Placeholder for TOTP (NFR-009, FR-052). Fails closed when MFA is required."""
    if container.settings.mfa_required:
        # TODO(NFR-009): verify an `X-TOTP` code against the user's TOTP secret (pyotp).
        raise AuthError("MFA is required but TOTP verification is not implemented yet")


async def require_api_token(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    expected = container.settings.api_token
    if expected is None:
        raise AuthError("API token not configured; all API calls are refused")
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), expected.get_secret_value().encode()
    ):
        raise AuthError("invalid or missing API token")
    return "kashyap"  # single-user system (FR-052)


Actor = Annotated[str, Depends(require_api_token)]
