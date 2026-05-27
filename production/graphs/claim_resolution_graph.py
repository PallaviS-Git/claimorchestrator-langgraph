from __future__ import annotations

from typing import Any, Dict, Optional

from ..nodes.claim_nodes import (
    escalation_node,
    intake_retry_node,
    communication_node,
    decision_node,
    fraud_node,
    ocr_retry_node,
    human_review_node,
    intake_node,
    payout_node,
    verification_node,
)
from ..state.models import ClaimResolutionState


def _intake_routing_selector(state: ClaimResolutionState) -> str:
    """
    Route after intake based on:
    - OCR failure -> OCR retry / human review fallback
    - missing_fields -> intake retry / human review fallback
    - else -> verification
    """
    extracted_facts = state.get("extracted_facts") or {}
    ocr_status = (extracted_facts.get("ocr_status") or "").lower()
    missing_fields = extracted_facts.get("missing_fields") or []

    ocr_retry_count = int(state.get("ocr_retry_count") or 0)
    max_ocr_retries = int(state.get("max_ocr_retries") or 0)
    intake_retry_count = int(state.get("intake_retry_count") or 0)
    max_intake_retries = int(state.get("max_intake_retries") or 0)

    if ocr_status == "failed":
        return "ocr_retry_node" if ocr_retry_count < max_ocr_retries else "human_review_node"

    if missing_fields:
        return "intake_retry_node" if intake_retry_count < max_intake_retries else "human_review_node"

    return "verification_node"


def _verification_routing_selector(state: ClaimResolutionState) -> str:
    """
    Route after verification:
    - invalid -> decision_node
    - verified -> fraud_node
    - needs_review/unknown -> decision_node (finalizes via decision logic)
    """
    verification_result = state.get("verification_result") or {}
    status = (verification_result.get("status") or "").lower()
    if status == "verified":
        return "fraud_node"
    if status == "invalid":
        return "decision_node"
    if status == "needs_review":
        return "decision_node"
    return "decision_node"


def _decision_routing_selector(state: ClaimResolutionState) -> str:
    """
    Conditional routing based on `decision_result`.

    Examples that should be satisfied by this selector:
    - fraud_score > 0.7 -> human_review_node (via decision_node computation)
    - otherwise -> payout_node or communication_node
    """
    decision_result = state.get("decision_result") or {}
    outcome = (decision_result.get("outcome") or "").lower()
    if outcome in ("approved", "approve"):
        return "payout_node"
    if outcome == "human_review":
        return "human_review_node"
    # denied / denied / anything else
    return "communication_node"


def _payout_routing_selector(state: ClaimResolutionState) -> str:
    """
    Route after payout calculation:
    - payout > threshold -> escalation_node (if retry budget) else human review
    - otherwise -> communication_node
    """
    payout_result = state.get("payout_result") or {}
    payout_amount = payout_result.get("payout_amount") or 0
    threshold = float(state.get("payout_escalation_threshold") or 0.0)

    escalation_count = int(state.get("escalation_count") or 0)
    max_escalations = int(state.get("max_escalations") or 0)

    try:
        payout_amount_num = float(payout_amount)
    except Exception:
        payout_amount_num = 0.0

    if payout_amount_num > threshold:
        return "escalation_node" if escalation_count < max_escalations else "human_review_node"

    return "communication_node"


def build_claim_resolution_graph(*, checkpointer: Optional[Any] = None) -> Any:
    """
    Build the production insurance claims orchestration graph.
    """
    try:
        from langgraph.graph import END, StateGraph
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "LangGraph is not installed. Install `langgraph` to use the graph builder."
        ) from e

    graph = StateGraph(ClaimResolutionState)

    # Core workflow nodes
    graph.add_node("intake_node", intake_node)
    graph.add_node("intake_retry_node", intake_retry_node)
    graph.add_node("ocr_retry_node", ocr_retry_node)
    graph.add_node("verification_node", verification_node)
    graph.add_node("fraud_node", fraud_node)
    graph.add_node("decision_node", decision_node)
    graph.add_node("human_review_node", human_review_node)
    graph.add_node("payout_node", payout_node)
    graph.add_node("escalation_node", escalation_node)
    graph.add_node("communication_node", communication_node)

    # Entry + intake retries/looping
    graph.set_entry_point("intake_node")
    graph.add_conditional_edges(
        "intake_node",
        _intake_routing_selector,
        {
            "verification_node": "verification_node",
            "intake_retry_node": "intake_retry_node",
            "ocr_retry_node": "ocr_retry_node",
            "human_review_node": "human_review_node",
        },
    )
    graph.add_edge("intake_retry_node", "intake_node")
    graph.add_edge("ocr_retry_node", "intake_node")

    # Verification routing (fallback edges included via selector default)
    graph.add_conditional_edges(
        "verification_node",
        _verification_routing_selector,
        {
            "fraud_node": "fraud_node",
            "decision_node": "decision_node",
        },
    )

    graph.add_edge("fraud_node", "decision_node")

    # Decision routing (fraud_score threshold is enforced inside decision_node)
    graph.add_conditional_edges(
        "decision_node",
        _decision_routing_selector,
        {
            "payout_node": "payout_node",
            "human_review_node": "human_review_node",
            "communication_node": "communication_node",
        },
    )

    # Human review can loop back into decision.
    graph.add_edge("human_review_node", "decision_node")

    # Payout -> escalation / human review / communication
    graph.add_conditional_edges(
        "payout_node",
        _payout_routing_selector,
        {
            "escalation_node": "escalation_node",
            "human_review_node": "human_review_node",
            "communication_node": "communication_node",
        },
    )
    graph.add_edge("escalation_node", "human_review_node")
    graph.add_edge("communication_node", END)

    # `checkpointer` is optional; when present it persists state between runs.
    if checkpointer is None:
        return graph.compile()

    # Interrupt handling: pause before human decisions so callers can resume.
    try:
        return graph.compile(checkpointer=checkpointer, interrupt_before=["human_review_node"])
    except TypeError:
        return graph.compile(checkpointer=checkpointer)

