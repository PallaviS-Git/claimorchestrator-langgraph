from __future__ import annotations

from typing import Any, Optional

from ..checkpoints.redis_checkpointer import get_checkpointer
from ..graphs.claim_resolution_graph import build_claim_resolution_graph


def get_runnable_claim_workflow(*, redis_url: Optional[str] = None) -> Any:
    """
    Return the compiled LangGraph runnable for the claims workflow.

    Includes checkpointing so interrupts/resume are supported.
    """
    checkpointer = get_checkpointer(redis_url=redis_url)
    return build_claim_resolution_graph(checkpointer=checkpointer)

