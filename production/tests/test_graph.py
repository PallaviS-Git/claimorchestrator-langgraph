from __future__ import annotations

from typing import Any, Dict

import pytest

from production.nodes.claim_nodes import (
    intake_node,
    verification_node,
    fraud_node,
    decision_node,
)
from production.state.models import ClaimResolutionState


def _base_state() -> ClaimResolutionState:
    return {
        "claim_id": "c-1",
        "status": "received",
        "log": [],
        "events": [],
        "claim_input": {"amount": 100, "date": "2026-01-01", "incident_type": "fire"},
        "extracted_facts": {},
        "verification_result": {},
        "fraud_result": {},
        "decision_result": {},
        "human_review_result": {},
        "payout_result": {},
        "communication_result": {},
        "resolution": {},
        "error": None,
    }


def test_nodes_produce_state_updates():
    state = _base_state()
    upd1 = intake_node(state)
    assert upd1["status"] == "intake_complete"
    assert "amount" in upd1["extracted_facts"]

    # Merge minimal
    state2: Dict[str, Any] = {**state, **upd1}
    # Verification should mark claim as needing review/verified based on policy_number presence.
    upd2 = verification_node(state2)
    assert upd2["status"] == "verification_complete"

    state3: Dict[str, Any] = {**state2, **upd2}
    upd3 = fraud_node(state3)
    assert upd3["status"] == "fraud_complete"
    assert "fraud_risk" in upd3["fraud_result"]

    state4: Dict[str, Any] = {**state3, **upd3}
    upd4 = decision_node(state4)
    assert upd4["status"] == "decision_complete"
    assert "outcome" in upd4["decision_result"]


def test_graph_builder_imports_and_compiles_if_deps_exist():
    pytest.importorskip("langgraph")
    graph_builder = pytest.importorskip("production.graphs.claim_resolution_graph")

    graph = graph_builder.build_claim_resolution_graph(checkpointer=None)
    assert graph is not None

