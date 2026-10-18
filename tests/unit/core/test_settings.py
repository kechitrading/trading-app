from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import SecretStr, ValidationError

from aqta.core.errors import ConfigError
from aqta.core.secrets import AwsSecretsManagerProvider, EnvSecretsProvider, build_secrets_provider
from aqta.core.settings import Settings, TradingMode, load_settings

TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # test-only value


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_defaults_are_paper_and_safe() -> None:
    s = make()
    assert s.trading_mode is TradingMode.PAPER
    assert s.is_paper
    assert s.live_trading_enabled is False
    assert s.astrology.shadow_mode is True
    assert s.astrology.default_weight == 0.0
    assert s.risk.capital_inr == Decimal("1000000")
    assert s.risk.max_loss_per_trade_pct == Decimal("1.0")
    assert s.risk.daily_loss_limit_pct == Decimal("2.0")
    assert s.risk.max_drawdown_pct == Decimal("5.0")
    assert s.risk.margin_cap_pct == Decimal("60.0")
    assert s.budget.data_monthly_inr == Decimal("1000")
    assert s.budget.ai_monthly_inr == Decimal("2000")
    assert s.approval_ttl_seconds == 300


def test_live_mode_refuses_without_explicit_enable() -> None:
    with pytest.raises(ValidationError, match="LIVE_TRADING_ENABLED"):
        make(trading_mode="live")


def test_live_mode_from_env_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(ValidationError):
        make()


def test_live_mode_allowed_with_double_opt_in() -> None:
    s = make(trading_mode="live", live_trading_enabled=True)
    assert s.trading_mode is TradingMode.LIVE
    assert not s.is_paper


def test_order_rate_cap_cannot_exceed_five() -> None:
    with pytest.raises(ValidationError):
        make(risk={"max_orders_per_second": 6})


def test_astrology_weight_must_be_zero_in_shadow() -> None:
    with pytest.raises(ValidationError, match="RULE-014"):
        make(astrology={"default_weight": 0.2})


def test_prod_requires_strong_secrets() -> None:
    with pytest.raises(ValidationError, match="APPROVAL_SECRET"):
        make(app_env="prod", api_token="x")
    with pytest.raises(ValidationError, match="API_TOKEN"):
        make(app_env="prod", approval_secret="s" * 40)
    with pytest.raises(ValidationError, match="MFA_REQUIRED"):
        make(app_env="prod", approval_secret="s" * 40, api_token="t")
    ok = make(
        app_env="prod",
        approval_secret="s" * 40,
        api_token="t",
        mfa_required=True,
        mfa_totp_secret=TOTP_SECRET,
    )
    assert ok.app_env == "prod"


def test_mfa_required_needs_a_valid_secret() -> None:
    with pytest.raises(ValidationError, match="MFA_TOTP_SECRET"):
        make(mfa_required=True)
    with pytest.raises(ValidationError, match="base32"):
        make(mfa_required=True, mfa_totp_secret="not base32 !!")
    with pytest.raises(ValidationError, match="16 bytes"):
        make(mfa_required=True, mfa_totp_secret="JBSWY3DP")
    assert make(mfa_required=True, mfa_totp_secret=TOTP_SECRET).mfa_required


def test_secrets_never_render_in_repr() -> None:
    s = make(api_token="super-secret-value", approval_secret="another-secret")
    assert "super-secret-value" not in repr(s)
    assert "another-secret" not in str(s.model_dump())


def test_nested_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RISK__MAX_OPEN_ORDERS", "7")
    assert make().risk.max_open_orders == 7


def test_env_provider_adds_nothing() -> None:
    assert EnvSecretsProvider().load() == {}
    assert isinstance(build_secrets_provider(make()), EnvSecretsProvider)


def test_aws_provider_requires_secret_id() -> None:
    with pytest.raises(ConfigError):
        build_secrets_provider(make(secrets_provider="aws"))
    provider = build_secrets_provider(make(secrets_provider="aws", aws_secret_id="aqta/prod"))
    assert isinstance(provider, AwsSecretsManagerProvider)


class _FakeSM:
    def __init__(self, payload: str | None) -> None:
        self.payload = payload

    def get_secret_value(self, SecretId: str) -> dict[str, str | None]:  # noqa: N803
        return {"SecretString": self.payload}


def test_aws_provider_loads_json_secret() -> None:
    client = _FakeSM(json.dumps({"API_TOKEN": "from-aws", "APPROVAL_SECRET": "x" * 40}))
    data = AwsSecretsManagerProvider("id", "ap-south-1", client=client).load()
    assert data == {"api_token": "from-aws", "approval_secret": "x" * 40}


@pytest.mark.parametrize("payload", [None, "[1, 2]"])
def test_aws_provider_rejects_bad_secret(payload: str | None) -> None:
    with pytest.raises(ConfigError):
        AwsSecretsManagerProvider("id", "ap-south-1", client=_FakeSM(payload)).load()


def test_load_settings_overlays_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aqta.core.secrets.EnvSecretsProvider.load", lambda self: {"api_token": "overlaid"}
    )
    s = load_settings(_env_file=None)
    assert isinstance(s.api_token, SecretStr)
    assert s.api_token.get_secret_value() == "overlaid"


def test_prod_secrets_from_aws_are_applied_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: on the server only APP_ENV, SECRETS_PROVIDER and AWS_SECRET_ID are in the env;
    the other secrets live in Secrets Manager. Prod checks must see the merged values."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_PROVIDER", "aws")
    monkeypatch.setenv("AWS_SECRET_ID", "aqta/prod")
    # Same shape as the JSON in docs/AWS_SETUP.md, including the empty Telegram placeholders.
    secret = json.dumps(
        {
            "APP_ENV": "prod",
            "DATABASE_URL": "postgresql+asyncpg://aqta:pw@postgres:5432/aqta",
            "REDIS_URL": "redis://redis:6379/0",
            "POSTGRES_PASSWORD": "pw",
            "API_TOKEN": "t" * 43,
            "APPROVAL_SECRET": "s" * 43,
            "MFA_REQUIRED": "true",
            "MFA_TOTP_SECRET": TOTP_SECRET,
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_ALLOWED_USER_ID": "",
        }
    )
    monkeypatch.setattr(
        "aqta.core.secrets.AwsSecretsManagerProvider._get_client", lambda self: _FakeSM(secret)
    )
    s = load_settings(_env_file=None)
    assert s.app_env == "prod"
    assert s.approval_secret.get_secret_value() == "s" * 43
    assert s.database_url.get_secret_value().endswith("@postgres:5432/aqta")
    assert s.telegram_bot_token is None
    assert s.telegram_allowed_user_id is None


def test_prod_still_refuses_when_secret_lacks_approval_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_PROVIDER", "aws")
    monkeypatch.setenv("AWS_SECRET_ID", "aqta/prod")
    monkeypatch.setattr(
        "aqta.core.secrets.AwsSecretsManagerProvider._get_client",
        lambda self: _FakeSM(json.dumps({"API_TOKEN": "t" * 43})),
    )
    with pytest.raises(ValidationError, match="APPROVAL_SECRET"):
        load_settings(_env_file=None)


def test_aws_provider_drops_empty_values() -> None:
    raw = json.dumps(
        {
            "API_TOKEN": "x",
            "TELEGRAM_ALLOWED_USER_ID": "",
            "TELEGRAM_BOT_TOKEN": " ",
            "AWS_REGION": None,
            "TELEGRAM_X": 0,
        }
    )
    data = AwsSecretsManagerProvider("id", "ap-south-1", client=_FakeSM(raw)).load()
    assert data == {"api_token": "x", "telegram_x": 0}
