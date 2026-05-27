from __future__ import annotations

from typing import Any, Optional

from .logging_config import get_logger

logger = get_logger(__name__)


def build_graph_callbacks(*, claim_id: str) -> list[Any]:
    """
    Best-effort graph lifecycle callbacks for tracing.

    LangGraph exposes `GraphCallbackHandler` in some versions. This function
    returns a list of callback handlers suitable for passing into
    `config["callbacks"]`.
    """
    try:
        from langgraph.callbacks import GraphCallbackHandler  # type: ignore
    except Exception:
        return []

    class _Handler(GraphCallbackHandler):  # type: ignore[misc]
        def on_interrupt(self, event: Any) -> Any:
            logger.info("graph interrupt claim_id=%s event=%s", claim_id, _safe_event_summary(event))

        def on_resume(self, event: Any) -> Any:
            logger.info("graph resume claim_id=%s event=%s", claim_id, _safe_event_summary(event))

    return [_Handler()]


def _safe_event_summary(event: Any) -> dict[str, Any]:
    # Avoid logging huge nested structures.
    try:
        interrupts = getattr(event, "interrupts", None)
        checkpoint_id = getattr(event, "checkpoint_id", None)
        status = getattr(event, "status", None)
        return {
            "status": status,
            "checkpoint_id": checkpoint_id,
            "interrupt_count": len(interrupts) if interrupts else 0,
        }
    except Exception:
        return {"event_type": type(event).__name__}

