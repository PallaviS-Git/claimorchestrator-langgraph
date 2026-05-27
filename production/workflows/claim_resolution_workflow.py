from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional

from ..checkpoints.redis_checkpointer import get_checkpointer
from ..graphs.claim_resolution_graph import build_claim_resolution_graph
from ..observability import build_graph_callbacks
from ..state.models import ClaimResolutionState


@lru_cache(maxsize=8)
def _get_compiled_graph(*, redis_url: Optional[str] = None) -> Any:
    checkpointer = get_checkpointer(redis_url=redis_url)
    return build_claim_resolution_graph(checkpointer=checkpointer)


def build_initial_state(*, claim_id: str, claim_input: Dict[str, Any]) -> ClaimResolutionState:
    max_intake_retries = int(claim_input.get("max_intake_retries", 2))
    max_ocr_retries = int(claim_input.get("max_ocr_retries", 1))
    max_escalations = int(claim_input.get("max_escalations", 2))
    payout_escalation_threshold = float(claim_input.get("payout_escalation_threshold", 100000.0))

    return {
        "claim_id": claim_id,
        "status": "received",
        "log": [],
        "events": [],
        "claim_input": claim_input,
        "extracted_facts": {},
        "verification_result": {},
        "fraud_result": {},
        "decision_result": {},
        "human_review_result": {},
        "resolution": {},
        "payout_result": {},
        "communication_result": {},
        "error": None,
        "intake_retry_count": 0,
        "ocr_retry_count": 0,
        "max_intake_retries": max_intake_retries,
        "max_ocr_retries": max_ocr_retries,
        "escalation_count": 0,
        "max_escalations": max_escalations,
        "payout_escalation_threshold": payout_escalation_threshold,
    }


def run_claim_resolution_workflow(
    *,
    claim_id: str,
    claim_input: Dict[str, Any],
    redis_url: Optional[str] = None,
    # You can pass configuration values through to nodes/LLMs/tooling later.
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute the LangGraph workflow for a single claim.

    Returns the final state produced by the graph.
    """
    graph = _get_compiled_graph(redis_url=redis_url)
    state = build_initial_state(claim_id=claim_id, claim_input=claim_input)

    invoke_config: Dict[str, Any] = _build_invoke_config(claim_id=claim_id, runtime_config=runtime_config)
    invoke_config.setdefault("callbacks", []).extend(build_graph_callbacks(claim_id=claim_id))
    return _invoke_with_interrupt_awareness(
        graph=graph,
        invoke_config=invoke_config,
        state_input=state,
        claim_id=claim_id,
    )


async def run_claim_resolution_workflow_async(
    *,
    claim_id: str,
    claim_input: Dict[str, Any],
    redis_url: Optional[str] = None,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Async variant of `run_claim_resolution_workflow` (uses `ainvoke` if available).
    """
    graph = _get_compiled_graph(redis_url=redis_url)
    state = build_initial_state(claim_id=claim_id, claim_input=claim_input)

    invoke_config: Dict[str, Any] = _build_invoke_config(claim_id=claim_id, runtime_config=runtime_config)
    invoke_config.setdefault("callbacks", []).extend(build_graph_callbacks(claim_id=claim_id))
    return await _ainvoke_with_interrupt_awareness(
        graph=graph,
        invoke_config=invoke_config,
        state_input=state,
        claim_id=claim_id,
    )

def resume_claim_resolution_workflow(
    *,
    claim_id: str,
    review_payload: Dict[str, Any],
    redis_url: Optional[str] = None,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resume a checkpointed workflow after human review input.

    `review_payload` supports:
    - human_review_decision: approved|denied
    - human_review_notes
    - human_reviewer
    - escalation_comment
    - manual_override_decision: approved|denied
    - manual_override_reason
    """
    graph = _get_compiled_graph(redis_url=redis_url)
    invoke_config: Dict[str, Any] = _build_invoke_config(claim_id=claim_id, runtime_config=runtime_config)
    invoke_config.setdefault("callbacks", []).extend(build_graph_callbacks(claim_id=claim_id))

    snapshot = _safe_get_snapshot(graph, invoke_config)
    existing_values = snapshot.get("values") if snapshot else {}
    if not isinstance(existing_values, dict):
        existing_values = {}

    previous_claim_input = existing_values.get("claim_input")
    if not isinstance(previous_claim_input, dict):
        previous_claim_input = {}
    merged_claim_input = {**previous_claim_input, **review_payload}

    # Best effort checkpoint update so resumed node receives review payload.
    try:
        if hasattr(graph, "update_state"):
            graph.update_state(invoke_config, {"claim_input": merged_claim_input})
        else:
            # Fallback: invoke a no-op update with only claim_input patch.
            graph.invoke({"claim_input": merged_claim_input}, invoke_config)
    except Exception:
        # Keep going; we'll still try to resume.
        pass

    # For static interrupt_before breakpoints, resume is done by passing None.
    return _invoke_with_interrupt_awareness(
        graph=graph,
        invoke_config=invoke_config,
        state_input=None,
        claim_id=claim_id,
    )


async def resume_claim_resolution_workflow_async(
    *,
    claim_id: str,
    review_payload: Dict[str, Any],
    redis_url: Optional[str] = None,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Async variant of `resume_claim_resolution_workflow`.
    """
    graph = _get_compiled_graph(redis_url=redis_url)
    invoke_config: Dict[str, Any] = _build_invoke_config(claim_id=claim_id, runtime_config=runtime_config)
    invoke_config.setdefault("callbacks", []).extend(build_graph_callbacks(claim_id=claim_id))

    snapshot = _safe_get_snapshot(graph, invoke_config)
    existing_values = snapshot.get("values") if snapshot else {}
    if not isinstance(existing_values, dict):
        existing_values = {}

    previous_claim_input = existing_values.get("claim_input")
    if not isinstance(previous_claim_input, dict):
        previous_claim_input = {}
    merged_claim_input = {**previous_claim_input, **review_payload}

    try:
        if hasattr(graph, "update_state"):
            graph.update_state(invoke_config, {"claim_input": merged_claim_input})
        else:
            # Fallback: invoke a no-op update with only claim_input patch.
            if hasattr(graph, "ainvoke"):
                await graph.ainvoke({"claim_input": merged_claim_input}, invoke_config)
            else:
                graph.invoke({"claim_input": merged_claim_input}, invoke_config)
    except Exception:
        pass

    return await _ainvoke_with_interrupt_awareness(
        graph=graph,
        invoke_config=invoke_config,
        state_input=None,
        claim_id=claim_id,
    )

def _build_invoke_config(*, claim_id: str, runtime_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # LangGraph's config conventions differ across versions. Using `configurable`
    # is the most common pattern (e.g., to set `thread_id` / session key).
    invoke_config: Dict[str, Any] = {"configurable": {"thread_id": claim_id}}
    if runtime_config:
        invoke_config["configurable"].update(runtime_config)
    return invoke_config


def _safe_get_snapshot(graph: Any, invoke_config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        snapshot = graph.get_state(invoke_config)  # type: ignore[attr-defined]
    except Exception:
        return {}
    return {
        "raw": snapshot,
        "values": getattr(snapshot, "values", None),
        "interrupts": getattr(snapshot, "interrupts", None),
        "next": getattr(snapshot, "next", None),
    }


def _is_paused_for_human_review(snapshot_info: Dict[str, Any]) -> bool:
    """Detect static interrupt_before breakpoints via snapshot.next / interrupts."""
    interrupts = snapshot_info.get("interrupts") or ()
    if interrupts:
        return True
    nxt = snapshot_info.get("next") or ()
    return "human_review_node" in nxt


def _format_pending_human_review(
    *,
    snapshot_info: Dict[str, Any],
    result: Dict[str, Any],
    claim_id: str,
) -> Dict[str, Any]:
    values = snapshot_info.get("values") or result
    if not isinstance(values, dict):
        values = dict(result)

    interrupt_values = []
    for intr in snapshot_info.get("interrupts") or ():
        interrupt_values.append(getattr(intr, "value", None))

    out = dict(values)
    out.setdefault("claim_id", claim_id)
    out.setdefault("resolution", {})
    out.setdefault("log", [])
    out.setdefault("events", [])
    out["status"] = "human_review_pending"
    out["interrupt"] = interrupt_values[0] if interrupt_values else {"next": list(snapshot_info.get("next") or ())}
    return out


def _invoke_with_interrupt_awareness(
    *,
    graph: Any,
    invoke_config: Dict[str, Any],
    state_input: Optional[Dict[str, Any]],
    claim_id: str,
) -> Dict[str, Any]:
    # Resumability improvement:
    # If a checkpoint already exists for this thread_id, merge the previous claim_input
    # with the new `claim_input` patch so human review outcomes / retries can be applied.
    if state_input is not None:
        try:
            snapshot = graph.get_state(invoke_config)  # type: ignore[attr-defined]
            values = getattr(snapshot, "values", None)
            prev_claim_input = (values or {}).get("claim_input") if isinstance(values, dict) else None
            if isinstance(prev_claim_input, dict):
                state_input["claim_input"] = {**prev_claim_input, **(state_input.get("claim_input") or {})}
        except Exception:
            pass

    result: Dict[str, Any] = {}
    try:
        result = graph.invoke(state_input, invoke_config)
    except Exception as e:
        # Some LangGraph versions may raise on static interrupts.
        exc_name = type(e).__name__.lower()
        if "interrupt" in exc_name:
            snapshot_info = _safe_get_snapshot(graph, invoke_config)
            if _is_paused_for_human_review(snapshot_info):
                return _format_pending_human_review(
                    snapshot_info=snapshot_info,
                    result=result,
                    claim_id=claim_id,
                )
        raise

    # Static interrupts pause execution before a node. If that happens, surface a
    # "pending" status to callers so they can resume later.
    snapshot_info = _safe_get_snapshot(graph, invoke_config)
    if _is_paused_for_human_review(snapshot_info):
        return _format_pending_human_review(
            snapshot_info=snapshot_info,
            result=dict(result),
            claim_id=claim_id,
        )

    return dict(result)


async def _ainvoke_with_interrupt_awareness(
    *,
    graph: Any,
    invoke_config: Dict[str, Any],
    state_input: Optional[Dict[str, Any]],
    claim_id: str,
) -> Dict[str, Any]:
    if state_input is not None:
        try:
            snapshot = graph.get_state(invoke_config)  # type: ignore[attr-defined]
            values = getattr(snapshot, "values", None)
            prev_claim_input = (values or {}).get("claim_input") if isinstance(values, dict) else None
            if isinstance(prev_claim_input, dict):
                state_input["claim_input"] = {**prev_claim_input, **(state_input.get("claim_input") or {})}
        except Exception:
            pass

    result: Dict[str, Any] = {}
    try:
        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(state_input, invoke_config)
        else:
            result = graph.invoke(state_input, invoke_config)
    except Exception as e:
        exc_name = type(e).__name__.lower()
        if "interrupt" in exc_name:
            snapshot_info = _safe_get_snapshot(graph, invoke_config)
            if _is_paused_for_human_review(snapshot_info):
                return _format_pending_human_review(
                    snapshot_info=snapshot_info,
                    result=result,
                    claim_id=claim_id,
                )
        raise

    snapshot_info = _safe_get_snapshot(graph, invoke_config)
    if _is_paused_for_human_review(snapshot_info):
        return _format_pending_human_review(
            snapshot_info=snapshot_info,
            result=dict(result),
            claim_id=claim_id,
        )

    return dict(result)

