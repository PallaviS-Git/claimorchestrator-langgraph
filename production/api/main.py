from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException

from .schemas import HumanReviewRequest, ResolveClaimRequest
from ..observability import configure_logging, get_logger
from ..state.models import ResolveClaimResponseModel
from ..workflows import (
    resume_claim_resolution_workflow,
    resume_claim_resolution_workflow_async,
    run_claim_resolution_workflow,
    run_claim_resolution_workflow_async,
)
from ..graphs.visualization import get_workflow_mermaid
from ..graphs.claim_resolution_graph import build_claim_resolution_graph
from ..checkpoints.redis_checkpointer import get_checkpointer

logger = get_logger(__name__)

app = FastAPI(title="claimorchestrator-langgraph", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    configure_logging()
    logger.info("Service startup complete")


@app.get("/health", tags=["health"])
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/workflow/mermaid", tags=["workflow"])
def workflow_mermaid() -> dict[str, Any]:
    """
    Mermaid visualization of the compiled claims workflow graph.
    """
    redis_url = os.getenv("REDIS_URL")
    checkpointer = get_checkpointer(redis_url=redis_url)
    compiled = build_claim_resolution_graph(checkpointer=checkpointer)
    mermaid = get_workflow_mermaid(compiled_graph=compiled)
    return {"mermaid": mermaid}


@app.post(
    "/claims/{claim_id}/resolve",
    response_model=ResolveClaimResponseModel,
    tags=["claims"],
)
def resolve_claim(claim_id: str, req: ResolveClaimRequest) -> ResolveClaimResponseModel:
    redis_url = os.getenv("REDIS_URL")
    try:
        result = run_claim_resolution_workflow(
            claim_id=claim_id,
            claim_input=req.claim_input,
            redis_url=redis_url,
        )
        return ResolveClaimResponseModel.model_validate(result)
    except Exception as e:
        logger.exception("Claim resolution failed for claim_id=%s", claim_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post(
    "/claims/{claim_id}/resolve-async",
    response_model=ResolveClaimResponseModel,
    tags=["claims"],
)
async def resolve_claim_async(claim_id: str, req: ResolveClaimRequest) -> ResolveClaimResponseModel:
    redis_url = os.getenv("REDIS_URL")
    try:
        result = await run_claim_resolution_workflow_async(
            claim_id=claim_id,
            claim_input=req.claim_input,
            redis_url=redis_url,
        )
        return ResolveClaimResponseModel.model_validate(result)
    except Exception as e:
        logger.exception("Async claim resolution failed for claim_id=%s", claim_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post(
    "/claims/{claim_id}/human-review",
    response_model=ResolveClaimResponseModel,
    tags=["claims"],
)
def submit_human_review(claim_id: str, req: HumanReviewRequest) -> ResolveClaimResponseModel:
    """
    Resume a paused workflow after human approval/denial (with optional manual override).
    """
    redis_url = os.getenv("REDIS_URL")
    payload = {
        "human_review_decision": req.decision,
        "human_reviewer": req.reviewer,
        "human_review_notes": req.notes,
        "escalation_comment": req.escalation_comment,
        "manual_override_decision": req.manual_override_decision,
        "manual_override_reason": req.manual_override_reason,
    }
    # Remove empty keys to keep audit metadata clean.
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        result = resume_claim_resolution_workflow(
            claim_id=claim_id,
            review_payload=payload,
            redis_url=redis_url,
        )
        return ResolveClaimResponseModel.model_validate(result)
    except Exception as e:
        logger.exception("Human review resume failed for claim_id=%s", claim_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post(
    "/claims/{claim_id}/human-review-async",
    response_model=ResolveClaimResponseModel,
    tags=["claims"],
)
async def submit_human_review_async(claim_id: str, req: HumanReviewRequest) -> ResolveClaimResponseModel:
    """
    Async resume endpoint.
    """
    redis_url = os.getenv("REDIS_URL")
    payload = {
        "human_review_decision": req.decision,
        "human_reviewer": req.reviewer,
        "human_review_notes": req.notes,
        "escalation_comment": req.escalation_comment,
        "manual_override_decision": req.manual_override_decision,
        "manual_override_reason": req.manual_override_reason,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        result = await resume_claim_resolution_workflow_async(
            claim_id=claim_id,
            review_payload=payload,
            redis_url=redis_url,
        )
        return ResolveClaimResponseModel.model_validate(result)
    except Exception as e:
        logger.exception("Async human review resume failed for claim_id=%s", claim_id)
        raise HTTPException(status_code=500, detail=str(e)) from e

