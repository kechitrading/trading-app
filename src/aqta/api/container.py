"""Composition root: wires ports to adapters for the API process.

``build_container`` is the real wiring (Postgres + Redis). ``build_in_memory_container`` wires the
same services to in-memory adapters for tests; it is never used when APP_ENV=prod.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from aqta.audit import AuditSink, InMemoryAuditLog, SqlAuditLog
from aqta.core.cache import create_redis, ping_redis
from aqta.core.clock import Clock, SystemClock
from aqta.core.db import create_engine, create_session_factory, ping_db
from aqta.core.errors import ConfigError
from aqta.core.settings import AppEnv, Settings
from aqta.core.totp import TotpVerifier
from aqta.execution import OrderGateway, select_broker
from aqta.notifications import (
    FakeProposalPublisher,
    NotifierPort,
    TelegramProposalPublisher,
    build_bot,
    build_notifier,
    build_publisher,
)
from aqta.proposals import (
    ApprovalService,
    ApprovalTokenService,
    InMemoryNonceStore,
    InMemoryProposalRepository,
    NonceStore,
    ProposalRepository,
    ProposalService,
)
from aqta.proposals.adapters import RedisNonceStore, SqlProposalRepository
from aqta.risk import (
    InMemoryKillSwitchStore,
    InMemoryRiskEventSink,
    InMemoryRiskState,
    KillSwitch,
    KillSwitchStore,
    PreTradeRiskEngine,
    RiskEventSink,
    RiskHalts,
    RiskLimits,
)
from aqta.risk.adapters import RedisKillSwitchStore, SqlKillSwitchStore, SqlRiskEventSink


@dataclass
class Container:
    settings: Settings
    clock: Clock
    audit: AuditSink
    kill_switch: KillSwitch
    halts: RiskHalts
    risk: PreTradeRiskEngine
    tokens: ApprovalTokenService
    approvals: ApprovalService
    gateway: OrderGateway
    proposals: ProposalService
    notifier: NotifierPort
    publisher: TelegramProposalPublisher | FakeProposalPublisher
    engine: AsyncEngine | None = None
    redis: Any | None = None
    mfa: TotpVerifier | None = None  # NFR-009; set when MFA_TOTP_SECRET is configured
    telegram_bot: Any | None = None  # polled by the API process (see aqta.api.app)

    async def check_ready(self) -> dict[str, str]:
        checks: dict[str, str] = {}
        for name, probe in (("database", self._db_ok), ("redis", self._redis_ok)):
            try:
                checks[name] = "ok" if await probe() else "unavailable"
            except Exception as exc:
                checks[name] = f"error: {type(exc).__name__}"
        return checks

    async def _db_ok(self) -> bool:
        return self.engine is not None and await ping_db(self.engine)

    async def _redis_ok(self) -> bool:
        return self.redis is not None and await ping_redis(self.redis)

    async def close(self) -> None:
        if self.telegram_bot is not None:
            await self.telegram_bot.session.close()
        if self.redis is not None:
            await self.redis.aclose()
        if self.engine is not None:
            await self.engine.dispose()


def _wire(
    settings: Settings,
    clock: Clock,
    audit: AuditSink,
    events: RiskEventSink,
    fast_store: KillSwitchStore,
    durable_store: KillSwitchStore | None,
    nonces: NonceStore,
    proposal_repo: ProposalRepository,
    engine: AsyncEngine | None,
    redis: Any | None,
) -> Container:
    secret = settings.approval_secret.get_secret_value()
    if not secret:
        raise ConfigError("APPROVAL_SECRET must be set (see .env.example)")
    limits = RiskLimits.from_settings(settings.risk)
    kill_switch = KillSwitch(fast_store, audit, events, clock, durable=durable_store)
    halts = RiskHalts(limits, clock, events, audit)
    # TODO(FR-014, FR-027): replace with portfolio-backed state reconciled with the broker.
    state = InMemoryRiskState(limits.capital_inr)
    risk = PreTradeRiskEngine(limits, state, kill_switch, halts, events, clock)
    tokens = ApprovalTokenService(secret, clock, nonces, settings.approval_ttl_seconds)
    gateway = OrderGateway(settings, select_broker(settings), tokens, risk, audit, clock)
    kill_switch.register_on_trigger(gateway.on_kill_switch)
    approvals = ApprovalService(tokens, audit, clock)
    proposals = ProposalService(proposal_repo, approvals, tokens, audit, clock)
    bot = build_bot(settings)
    publisher = build_publisher(settings, bot)
    proposals.on_new_pending(publisher.publish)  # FR-023: every open proposal goes to Telegram
    return Container(
        settings=settings,
        clock=clock,
        audit=audit,
        kill_switch=kill_switch,
        halts=halts,
        risk=risk,
        tokens=tokens,
        approvals=approvals,
        gateway=gateway,
        proposals=proposals,
        notifier=build_notifier(settings, bot),
        publisher=publisher,
        telegram_bot=bot,
        engine=engine,
        redis=redis,
        mfa=_build_mfa(settings, clock),
    )


def _build_mfa(settings: Settings, clock: Clock) -> TotpVerifier | None:
    if settings.mfa_totp_secret is None:
        return None
    return TotpVerifier(settings.mfa_totp_secret.get_secret_value(), clock)


def build_container(settings: Settings, clock: Clock | None = None) -> Container:
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url.get_secret_value())
    sessions = create_session_factory(engine)
    redis = create_redis(settings.redis_url.get_secret_value())
    return _wire(
        settings,
        clock,
        audit=SqlAuditLog(sessions, clock),
        events=SqlRiskEventSink(sessions),
        fast_store=RedisKillSwitchStore(redis),
        durable_store=SqlKillSwitchStore(sessions),
        nonces=RedisNonceStore(redis),
        proposal_repo=SqlProposalRepository(sessions, clock),
        engine=engine,
        redis=redis,
    )


def build_in_memory_container(
    settings: Settings, clock: Clock | None = None, redis: Any | None = None
) -> Container:
    if settings.app_env == AppEnv.PROD:
        raise ConfigError("in-memory container is not allowed in prod")
    clock = clock or SystemClock()
    return _wire(
        settings,
        clock,
        audit=InMemoryAuditLog(clock),
        events=InMemoryRiskEventSink(),
        fast_store=RedisKillSwitchStore(redis) if redis is not None else InMemoryKillSwitchStore(),
        durable_store=None,
        nonces=InMemoryNonceStore(),
        proposal_repo=InMemoryProposalRepository(),
        engine=None,
        redis=redis,
    )
