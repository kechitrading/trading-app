"""End-to-end smoke (paper mode, in-memory adapters): app boots through its lifespan, a proposal is
approved, the order fills on the paper broker, the kill switch blocks the next order, and the audit
chain verifies.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from aqta.api import build_in_memory_container, create_app
from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.settings import Settings
from aqta.execution import OrderState, Stage
from aqta.proposals import Horizon, Proposal, ProposalStatus
from conftest import TEST_API_TOKEN
from factories import make_order

pytestmark = pytest.mark.smoke
AUTH = {"Authorization": f"Bearer {TEST_API_TOKEN}"}


def test_paper_flow_end_to_end(settings: Settings, clock: FrozenClock) -> None:
    container = build_in_memory_container(settings, clock)
    proposal = Proposal(
        id="prop_1",
        created_at=clock.now(),
        valid_until=clock.now() + timedelta(minutes=5),
        horizon=Horizon.INTRADAY,
        underlying="NIFTY",
        legs=(make_order(),),
        status=ProposalStatus.PENDING_APPROVAL,
    )

    with TestClient(create_app(container=container)) as client:
        assert client.get("/health").json()["status"] == "ok"
        client.portal.call(container.proposals.submit, proposal)  # type: ignore[union-attr]
        assert client.get("/api/v1/proposals", headers=AUTH).json()[0]["id"] == "prop_1"

        r = client.post("/api/v1/proposals/prop_1/approve", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["proposal"]["status"] == "executed"
        assert body["orders"][0]["state"] == OrderState.FILLED.value

        r = client.post(
            "/api/v1/kill-switch", headers=AUTH, json={"action": "trigger", "reason": "smoke test"}
        )
        assert r.json()["active"] is True

        async def blocked() -> None:
            order = make_order(quantity=150)
            token = container.tokens.issue(order, "kashyap")
            result = await container.gateway.submit_order(order, token)
            assert result.stage is Stage.RISK

        client.portal.call(blocked)  # type: ignore[union-attr]

    audit = container.audit
    assert isinstance(audit, InMemoryAuditLog)
    kinds = [e.event_type for e in audit.entries]
    assert kinds[0] == "api.started"
    assert "proposal.approved" in kinds and "order.filled" in kinds
    assert "kill_switch.triggered" in kinds and kinds[-1] == "order.rejected"
    assert audit.verify().ok
