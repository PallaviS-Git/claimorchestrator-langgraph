from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class ResolveClaimRequest(BaseModel):
    claim_input: Dict[str, Any] = Field(default_factory=dict)


class HumanReviewRequest(BaseModel):
    decision: str | None = None  # approved | denied
    reviewer: str | None = None
    notes: str | None = None
    escalation_comment: str | None = None
    manual_override_decision: str | None = None  # approved | denied
    manual_override_reason: str | None = None

