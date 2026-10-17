# ADR-0002: Hexagonal ports for broker and external systems

- Status: Accepted (2026-10-17)

## Context
The broker is undecided (Q-005: Zerodha, Angel One, Upstox or Dhan). Each has a different API,
order types and session rules (2FA daily login, static IP, algo tag; REG-001..REG-006). Data, news,
LLM and Telegram providers may also change for cost reasons (Q-001, Q-009, Q-010).

## Decision
Every external system is reached only through a port (abstract class or Protocol) with swappable
adapters: `BrokerPort` (execution), `MarketDataPort`/`ExchangeDataPort`/`NewsPort`/`MacroPort`
(ingestion), `LLMPort`, `NotifierPort`, `EphemerisPort`. `PaperBroker` implements `BrokerPort` for
paper mode (FR-030). `LiveBrokerStub` raises `NotImplementedError` until a broker is chosen and
Kashyap explicitly approves live-order code. `OrderGateway` refuses a live adapter in paper mode.

## Consequences
- The broker choice touches one adapter module plus its tests.
- Paper and live use the same gateway, risk and audit path.
- Adapters must map broker states onto `OrderState`/`OrderEvent`. Reconciliation (FR-027) catches gaps.
