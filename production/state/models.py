from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict

from pydantic import BaseModel, Field


class EventRecord(TypedDict, total=False):
    timestamp: str
    node: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    message: str
    meta: Dict[str, Any]


class ClaimResolutionState(TypedDict, total=False):
    """
    LangGraph state schema (typed dict).

    Nodes return partial updates; LangGraph merges them into the running state.
    """

    claim_id: str
    status: Literal[
        "received",
        "intake_complete",
        "intake_retrying",
        "ocr_retrying",
        "verification_complete",
        "fraud_complete",
        "decision_complete",
        "human_review_complete",
        "escalation_complete",
        "payout_calculated",
        "communication_complete",
        "resolved",
        "denied",
        "failed",
    ]
    # Human-readable event trail. Also stored in `events`.
    log: List[str]
    # Structured event log (for auditability). Stored in state so checkpoints persist it.
    events: List[EventRecord]

    # Domain payloads
    claim_input: Dict[str, Any]
    extracted_facts: Dict[str, Any]
    verification_result: Dict[str, Any]
    fraud_result: Dict[str, Any]
    decision_result: Dict[str, Any]
    human_review_result: Dict[str, Any]
    payout_result: Dict[str, Any]
    communication_result: Dict[str, Any]
    resolution: Dict[str, Any]

    # Optional metadata
    error: Optional[str]

    # Retry/loop counters & limits
    intake_retry_count: int
    ocr_retry_count: int
    max_intake_retries: int
    max_ocr_retries: int
    escalation_count: int
    max_escalations: int

    # Thresholds for conditional escalation
    payout_escalation_threshold: float


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimResolutionStateModel(BaseModel):
    """Pydantic representation of the LangGraph state (useful at API boundaries)."""

    claim_id: str
    status: str = "received"
    log: List[str] = Field(default_factory=list)
    events: List[EventRecord] = Field(default_factory=list)
    claim_input: Dict[str, Any] = Field(default_factory=dict)

    extracted_facts: Dict[str, Any] = Field(default_factory=dict)
    verification_result: Dict[str, Any] = Field(default_factory=dict)
    fraud_result: Dict[str, Any] = Field(default_factory=dict)
    decision_result: Dict[str, Any] = Field(default_factory=dict)
    human_review_result: Dict[str, Any] = Field(default_factory=dict)
    payout_result: Dict[str, Any] = Field(default_factory=dict)
    communication_result: Dict[str, Any] = Field(default_factory=dict)
    resolution: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

    intake_retry_count: int = 0
    ocr_retry_count: int = 0
    max_intake_retries: int = 2
    max_ocr_retries: int = 1
    escalation_count: int = 0
    max_escalations: int = 2
    payout_escalation_threshold: float = 100000.0

    def to_typed_state(self) -> ClaimResolutionState:
        return self.model_dump()  # type: ignore[return-value]


class ResolveClaimRequestModel(BaseModel):
    claim_id: str
    claim_input: Dict[str, Any] = Field(default_factory=dict)


class ResolveClaimResponseModel(BaseModel):
    claim_id: str
    status: str
    resolution: Dict[str, Any] = Field(default_factory=dict)
    log: List[str] = Field(default_factory=list)
    events: List[EventRecord] = Field(default_factory=list)
    human_review_result: Dict[str, Any] = Field(default_factory=dict)
    interrupt: Optional[Any] = None
    error: Optional[str] = None

