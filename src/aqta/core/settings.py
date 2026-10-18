"""Typed application settings (pydantic-settings).

Safety rules encoded here (see CLAUDE.md):
- ``TRADING_MODE`` defaults to ``paper``. ``live`` additionally requires
  ``LIVE_TRADING_ENABLED=true`` or the settings refuse to load (RULE-001, FR-030).
- Astrology defaults to shadow mode with weight 0 (RULE-014).
- Risk defaults follow RULE-002 / RULE-003 / ASM-004 (confirmed 2026-10-18, BRD D-012).
- Secrets are ``SecretStr`` so they never render in logs or reprs (NFR-008).
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aqta.core.errors import ConfigError, LiveTradingNotEnabledError

MIN_SECRET_LENGTH = 32


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class RiskSettings(BaseModel):
    """RULE-002 / RULE-003 defaults. Loosening any limit needs FR-037 (two-step, 24h cool-off)."""

    capital_inr: Decimal = Decimal("1000000")  # Rs 10,00,000 (RULE-002)
    max_loss_per_trade_pct: Decimal = Decimal("1.0")  # RULE-003
    daily_loss_limit_pct: Decimal = Decimal("2.0")  # RULE-003
    max_drawdown_pct: Decimal = Decimal("5.0")  # RULE-002
    margin_cap_pct: Decimal = Decimal("60.0")  # RULE-003
    max_open_orders: int = 20
    max_orders_per_second: int = 5  # FR-031, REG-003: internal cap at or below 5/sec
    max_lots_per_order: int = 50
    price_band_pct: Decimal = Decimal("5.0")  # FR-031 price band vs reference price
    duplicate_window_seconds: int = 30

    @field_validator("max_orders_per_second")
    @classmethod
    def _rate_cap(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("max_orders_per_second must be between 1 and 5 (FR-031, REG-003)")
        return v


class BudgetSettings(BaseModel):
    """CON-002 / FR-053 monthly budgets in INR."""

    data_monthly_inr: Decimal = Decimal("1000")
    ai_monthly_inr: Decimal = Decimal("2000")
    alert_thresholds_pct: tuple[int, ...] = (80, 100)


class AstrologySettings(BaseModel):
    """RULE-014: shadow mode and zero weight until a rule passes the gate and is approved."""

    shadow_mode: bool = True
    default_weight: float = 0.0
    # ASM-013 accuracy gate (to be confirmed under Q-016).
    gate_fdr: float = 0.05
    gate_min_oos_events: int = 30
    gate_min_hit_rate: float = 0.60


class ProposalSettings(BaseModel):
    """How long a proposal stays open for approval, per horizon (FR-023; decided 2026-10-18)."""

    intraday_seconds: int = Field(default=300, gt=0)  # BRD default: 5 minutes
    swing_seconds: int = Field(default=1800, gt=0)
    positional_seconds: int = Field(default=3600, gt=0)


class MarketSessionSettings(BaseModel):
    """Session times in IST. MCX close varies with US DST, hence configurable."""

    equity_open: time = time(9, 15)
    equity_close: time = time(15, 30)
    mcx_open: time = time(9, 0)
    mcx_close: time = time(23, 30)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
        # Never echo input values in validation errors: they contain secrets (NFR-008).
        hide_input_in_errors=True,
    )

    app_env: AppEnv = AppEnv.DEV
    log_level: str = "INFO"
    log_json: bool = True

    # --- trading mode (safety rule 1)
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    algo_tag: str = Field(
        default="AQTA-UNREGISTERED",
        description="Exchange/broker algo identifier attached to every order (FR-028, Q-008).",
    )

    # --- infrastructure
    database_url: SecretStr = SecretStr("postgresql+asyncpg://aqta:aqta@localhost:5432/aqta")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # --- secrets provider (NFR-008)
    secrets_provider: Literal["env", "aws"] = "env"
    aws_region: str = "ap-south-1"
    aws_secret_id: str | None = None

    # --- API
    api_token: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=list)
    # NFR-009, FR-052: TOTP on sensitive actions. Always on in prod; the secret comes from
    # scripts/mfa_setup.py and is added to your authenticator app.
    mfa_required: bool = False
    mfa_totp_secret: SecretStr | None = None
    # /docs and /openapi.json are always on outside prod; in prod only when explicitly enabled
    # (the API is reachable only through nginx from allowlisted IPs).
    docs_enabled: bool = False

    # --- approvals (RULE-001, FR-023, FR-024)
    approval_secret: SecretStr = SecretStr("")
    approval_ttl_seconds: int = 300  # default 5 min validity for intraday proposals

    # --- Telegram (FR-052)
    telegram_bot_token: SecretStr | None = None
    telegram_allowed_user_id: int | None = None
    # Only one process may poll a bot token. Turn off on a dev machine while prod runs the bot.
    telegram_polling: bool = True

    # --- Broker: Angel One SmartAPI (Q-005 closed 2026-10-18). Credentials only; no live-order
    # adapter exists yet (CLAUDE.md safety rule 2). Login needs client code + MPIN + TOTP (FR-029).
    angel_one_api_key: SecretStr | None = None
    angel_one_client_code: str | None = None
    angel_one_mpin: SecretStr | None = None
    angel_one_totp_secret: SecretStr | None = None

    # --- AI: Anthropic Claude (Q-010 closed 2026-10-18), within BUDGET__AI_MONTHLY_INR.
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"  # reports, deep dives, advice (FR-016, FR-040)
    llm_model_routine: str = "claude-opus-5-5"  # summaries, sentiment tagging (FR-006, FR-044)

    # --- News and global macro: Finnhub (Q-001 closed 2026-10-18; Indian prices come from the
    # broker and exchange files, ASM-001).
    finnhub_api_key: SecretStr | None = None

    risk: RiskSettings = Field(default_factory=RiskSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    astrology: AstrologySettings = Field(default_factory=AstrologySettings)
    sessions: MarketSessionSettings = Field(default_factory=MarketSessionSettings)
    proposals: ProposalSettings = Field(default_factory=ProposalSettings)

    @model_validator(mode="after")
    def _enforce_safety(self) -> Settings:
        if self.trading_mode is TradingMode.LIVE and not self.live_trading_enabled:
            raise LiveTradingNotEnabledError(
                "TRADING_MODE=live requires LIVE_TRADING_ENABLED=true; refusing to start."
            )
        if self.astrology.default_weight != 0.0 and self.astrology.shadow_mode:
            raise ConfigError("Astrology weight must be 0 while in shadow mode (RULE-014).")
        if self.app_env is AppEnv.PROD:
            secret = self.approval_secret.get_secret_value()
            if len(secret) < MIN_SECRET_LENGTH:
                raise ConfigError(
                    f"APPROVAL_SECRET must be at least {MIN_SECRET_LENGTH} chars in prod."
                )
            if self.api_token is None:
                raise ConfigError("API_TOKEN must be set in prod.")
            if not self.mfa_required:
                raise ConfigError("MFA_REQUIRED must be true in prod (NFR-009).")
        if self.mfa_required:
            from aqta.core.totp import decode_secret  # local import keeps settings light

            if self.mfa_totp_secret is None:
                raise ConfigError(
                    "MFA_REQUIRED=true needs MFA_TOTP_SECRET (run scripts/mfa_setup.py)."
                )
            decode_secret(self.mfa_totp_secret.get_secret_value())
        return self

    @property
    def is_paper(self) -> bool:
        return self.trading_mode is TradingMode.PAPER


class SecretsLocation(BaseSettings):
    """Only where secrets come from. Read first, so that the full ``Settings`` (and its prod
    checks) is validated once, after the secret store's values have been merged in."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

    secrets_provider: Literal["env", "aws"] = "env"
    aws_region: str = "ap-south-1"
    aws_secret_id: str | None = None


_LOCATION_KEYS = ("_env_file", "secrets_provider", "aws_region", "aws_secret_id")


def load_settings(**overrides: Any) -> Settings:
    """Build settings from env/.env plus values from the configured secret store.

    Precedence: explicit overrides > secret store > environment / .env.
    """
    from aqta.core.secrets import build_secrets_provider  # local import avoids a cycle

    location = SecretsLocation(**{k: v for k, v in overrides.items() if k in _LOCATION_KEYS})
    secret_values = build_secrets_provider(location).load()
    return Settings(**{**secret_values, **overrides})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
