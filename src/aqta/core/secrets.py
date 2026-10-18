"""Secrets provider interface (NFR-008).

Local/dev: values come from environment / ``.env`` (gitignored) via pydantic-settings, so the env
provider returns nothing extra. Production: one JSON secret in AWS Secrets Manager whose keys are
setting names (e.g. ``{"API_TOKEN": "...", "APPROVAL_SECRET": "..."}``).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from aqta.core.errors import ConfigError


class SecretsLocator(Protocol):
    """Anything that says where secrets live (``Settings`` or ``SecretsLocation``)."""

    @property
    def secrets_provider(self) -> str: ...

    @property
    def aws_region(self) -> str: ...

    @property
    def aws_secret_id(self) -> str | None: ...


class SecretsProvider(Protocol):
    def load(self) -> dict[str, Any]:
        """Return setting overrides (lower-case setting names) loaded from the secret store."""
        ...


class EnvSecretsProvider:
    """Environment variables are already read by pydantic-settings; nothing to add."""

    def load(self) -> dict[str, Any]:
        return {}


class AwsSecretsManagerProvider:
    def __init__(self, secret_id: str, region: str, client: Any | None = None) -> None:
        self._secret_id = secret_id
        self._region = region
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # optional dependency group "aws"
            except ImportError as exc:  # pragma: no cover - depends on install extras
                raise ConfigError("Install the 'aws' extra to use SECRETS_PROVIDER=aws") from exc
            self._client = boto3.client("secretsmanager", region_name=self._region)
        return self._client

    def load(self) -> dict[str, Any]:
        response = self._get_client().get_secret_value(SecretId=self._secret_id)
        raw = response.get("SecretString")
        if not raw:
            raise ConfigError(f"Secret {self._secret_id} has no SecretString")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ConfigError(f"Secret {self._secret_id} must be a JSON object")
        return {str(k).lower(): v for k, v in data.items()}


def build_secrets_provider(settings: SecretsLocator) -> SecretsProvider:
    if settings.secrets_provider == "aws":
        if not settings.aws_secret_id:
            raise ConfigError("AWS_SECRET_ID is required when SECRETS_PROVIDER=aws")
        return AwsSecretsManagerProvider(settings.aws_secret_id, settings.aws_region)
    return EnvSecretsProvider()
