"""FastAPI dependencies: container access, API-token auth and TOTP checks (NFR-009, FR-052)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aqta.api.container import Container
from aqta.core.errors import AuthError

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def check_mfa(container: Container, code: str | None) -> None:
    """NFR-009, FR-052: a fresh TOTP code is needed for sensitive actions (approving orders,
    loosening controls). Fails closed: MFA required but no verifier means refuse."""
    if not container.settings.mfa_required:
        return
    if container.mfa is None:
        raise AuthError("MFA is required but no TOTP secret is configured")
    if not container.mfa.verify(code):
        raise AuthError("invalid, reused or missing TOTP code (send it in the X-TOTP header)")


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

TotpHeader = Annotated[str | None, Header(alias="X-TOTP")]


async def require_mfa(container: ContainerDep, actor: Actor, totp: TotpHeader = None) -> str:
    """Token first, then TOTP, so unauthenticated calls cannot use up a code."""
    check_mfa(container, totp)
    return actor


MfaActor = Annotated[str, Depends(require_mfa)]
"""Use on routes that approve orders or change limits (FR-052)."""
