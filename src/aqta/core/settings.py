"""Typed application settings (pydantic-settings).

Safety rules encoded here (see CLAUDE.md):
- ``TRADING_MODE`` defaults to ``paper``. ``live`` additionally requires
  ``LIVE_TRADING_ENABLED=true`` or the settings refuse to load (RULE-001, FR-030).
- Astrology defaults to shadow mode with weight 0 (RULE-014).
- Risk defaults follow RULE-002 / RULE-003 / ASM-004 (to be confirmed under Q-004).
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
    mfa_required: bool = False  # TODO(NFR-009, FR-052): enforce TOTP before paper start.

    # --- approvals (RULE-001, FR-023, FR-024)
    approval_secret: SecretStr = SecretStr("")
    approval_ttl_seconds: int = 300  # default 5 min validity for intraday proposals

    # --- Telegram (FR-052)
    telegram_bot_token: SecretStr | None = None
    telegram_allowed_user_id: int | None = None

    risk: RiskSettings = Field(default_factory=RiskSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    astrology: AstrologySettings = Field(default_factory=AstrologySettings)
    sessions: MarketSessionSettings = Field(default_factory=MarketSessionSettings)

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
        return self

    @property
    def is_paper(self) -> bool:
        return self.trading_mode is TradingMode.PAPER


def load_settings(**overrides: Any) -> Settings:
    """Build settings from env/.env, then overlay secrets from the configured provider."""
    from aqta.core.secrets import build_secrets_provider  # local import avoids a cycle

    base = Settings(**overrides)
    provider = build_secrets_provider(base)
    secret_values = provider.load()
    if not secret_values:
        return base
    merged = {**secret_values, **overrides}
    return Settings(**merged)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
