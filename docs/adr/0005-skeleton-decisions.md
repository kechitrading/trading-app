# ADR-0005: Smaller decisions taken while building the skeleton

- Status: Accepted (2026-10-17). Items marked **confirm** need Kashyap's review.

1. **Drawdown reset does not rebase the high-water mark** (FR-033). After a logged reset the halt
   clears, but if drawdown is still >= 5% of capital the next evaluation halts again. **Confirm**:
   should a reset rebase the peak to current equity?
2. **Drawdown halt blocks all orders, risk-reducing ones included** (FR-033 says "no order is
   accepted"). Exits during a halt must go through the kill switch's flatten path (FR-034, TODO).
   **Confirm**.
3. **Daily-loss block latches for the IST trading date** and clears on the next IST date, even if
   P&L recovers intraday (FR-032).
4. **Undefined-risk orders (no max loss) are always blocked for now.** RULE-004/FR-036 per-strategy
   approval is a TODO.
5. **Price-band check needs a reference price on every order.** Orders without one are rejected.
6. **Kill-switch reads fail closed.** If Redis cannot be read, the switch counts as active.
7. **An approval token is consumed before the risk check.** A risk-rejected order needs a fresh
   approval, which favours safety over convenience.
8. **Audit payload floats are stored as strings** so hashes survive the JSONB round trip. Use
   Decimal for money.
9. **Deploy freeze uses weekdays only**: exchange holidays count as trading days (conservative).
10. **MFA hook fails closed** when `MFA_REQUIRED=true` until TOTP is implemented (NFR-009).
11. **The BRD is not committed** because it is marked Confidential and the GitHub repo is public.
    It stays in `docs/` locally (gitignored).
12. **Local tooling on Windows**: uv, its cache and the managed Python live inside the project
    (gitignored `.tools/`, `.uv-cache/`, `.uv-python/`). Local integration tests can use an embedded
    Postgres (`pgserver`). CI uses the TimescaleDB image.
13. **The GitHub repository was empty** (no initial README commit), so `main` was created locally
    with the README titled "trading-app".
