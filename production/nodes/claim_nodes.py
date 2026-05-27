from __future__ import annotations

from typing import Any, Dict, Optional

from ..observability import get_logger
from ..state.models import ClaimResolutionState, EventRecord, utc_now_iso


logger = get_logger(__name__)


def _append_event(
    state: ClaimResolutionState,
    *,
    node: str,
    message: str,
    level: str = "INFO",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Event logging used for auditability.

    Stored in both:
    - `events` (structured record)
    - `log` (human-readable list)
    """
    events = list(state.get("events") or [])
    event: EventRecord = {
        "timestamp": utc_now_iso(),
        "node": node,
        "level": level,  # type: ignore[typeddict-item]
        "message": message,
        "meta": meta or {},
    }
    events.append(event)

    log = list(state.get("log") or [])
    log.append(f"[{node}] {message}")

    return {"events": events, "log": log}


def _claim_input(state: ClaimResolutionState) -> Dict[str, Any]:
    return state.get("claim_input") or {}


def _append_log(state: ClaimResolutionState, message: str) -> list[str]:
    # Backwards-compatible helper for the placeholder nodes.
    log = list(state.get("log") or [])
    log.append(message)
    return log


def intake_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Intake/normalize inbound claim input.

    This node is responsible for shaping the claim into a canonical form
    for downstream verification, fraud, and payout calculation.
    """
    claim_input = _claim_input(state)

    required_fields = ("amount", "date", "incident_type")
    missing = [k for k in required_fields if claim_input.get(k) in (None, "", [])]

    # OCR is treated as an upstream extraction dependency.
    # In this skeleton, you signal OCR failure via `claim_input["ocr_fail"]=true`
    # or `claim_input["ocr_error"]="..."`.
    ocr_fail = bool(claim_input.get("ocr_fail")) or bool(claim_input.get("ocr_error"))
    extracted_facts_ocr: Dict[str, Any] = {}
    if ocr_fail:
        extracted_facts_ocr = {
            "ocr_status": "failed",
            "ocr_error": claim_input.get("ocr_error") or "ocr_failed",
        }
    else:
        extracted_facts_ocr = {"ocr_status": "ok"}
    extracted_facts: Dict[str, Any] = {
        "amount": claim_input.get("amount"),
        "date": claim_input.get("date"),
        "incident_type": claim_input.get("incident_type"),
        "policy_number": claim_input.get("policy_number"),
        "currency": claim_input.get("currency") or "USD",
        "claimant_id": claim_input.get("claimant_id"),
        "missing_fields": missing,
    }
    extracted_facts.update(extracted_facts_ocr)

    # Status is informational; routing is driven by `extracted_facts`.
    update = {"status": "intake_complete", "extracted_facts": extracted_facts}
    update.update(
        _append_event(
            state,
            node="intake_node",
            message="Intake complete" if not missing else f"Intake complete (missing: {missing})",
            meta={"missing_fields": missing, "ocr_status": extracted_facts.get("ocr_status")},
        )
    )
    return update


def intake_retry_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retry intake by applying a caller-provided correction patch.

    Provide a dict patch in `claim_input["intake_retry_fix"]`.
    """
    claim_input = _claim_input(state)
    count = int(state.get("intake_retry_count") or 0) + 1
    max_retries = int(state.get("max_intake_retries") or 0)

    fix = claim_input.get("intake_retry_fix") or {}
    if not isinstance(fix, dict):
        fix = {}

    # Apply fix patch (if any) and clear extracted_facts so intake_node recalculates.
    patched_claim_input = {**claim_input, **fix}

    update: Dict[str, Any] = {
        "status": "intake_retrying",
        "intake_retry_count": count,
        "claim_input": patched_claim_input,
        "extracted_facts": {},
    }

    update.update(
        _append_event(
            state,
            node="intake_retry_node",
            message="Intake retry applied"
            if fix
            else f"Intake retry scheduled (no fix patch provided). attempt={count}/{max_retries}",
            meta={"intake_retry_count": count, "max_intake_retries": max_retries, "fix_keys": list(fix.keys())},
        )
    )
    return update


def ocr_retry_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retry OCR extraction.

    In this skeleton, after the first OCR retry we flip `ocr_fail` off if present.
    """
    claim_input = _claim_input(state)
    count = int(state.get("ocr_retry_count") or 0) + 1
    max_retries = int(state.get("max_ocr_retries") or 0)

    patched_claim_input = dict(claim_input)
    # Deterministic behavior: once we retry, we assume OCR succeeds next time.
    if patched_claim_input.get("ocr_fail") is True or patched_claim_input.get("ocr_error"):
        patched_claim_input["ocr_fail"] = False
        patched_claim_input["ocr_error"] = None

    update: Dict[str, Any] = {
        "status": "ocr_retrying",
        "ocr_retry_count": count,
        "claim_input": patched_claim_input,
        "extracted_facts": {},
    }

    update.update(
        _append_event(
            state,
            node="ocr_retry_node",
            message=f"OCR retry scheduled. attempt={count}/{max_retries}",
            meta={"ocr_retry_count": count, "max_ocr_retries": max_retries},
        )
    )
    return update


def verification_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Verify required claim attributes and basic policy validity.
    """
    extracted_facts = state.get("extracted_facts") or {}
    policy_number = extracted_facts.get("policy_number")
    required_present = all(
        extracted_facts.get(k) not in (None, "", []) for k in ("amount", "date", "incident_type")
    )

    if not required_present:
        verification_result = {
            "status": "needs_review",
            "reason": "missing_required_fields",
            "missing_fields": [k for k in ("amount", "date", "incident_type") if extracted_facts.get(k) in (None, "", [])],
        }
    elif policy_number in (None, "", []):
        verification_result = {
            "status": "needs_review",
            "reason": "policy_number_missing",
        }
    elif str(policy_number).upper() == "INVALID":
        verification_result = {
            "status": "invalid",
            "reason": "policy_not_found",
        }
    else:
        verification_result = {
            "status": "verified",
            "reason": "basic policy and claim fields validated",
            "coverage_eligible": True,
        }

    update = {"status": "verification_complete", "verification_result": verification_result}
    update.update(
        _append_event(
            state,
            node="verification_node",
            message="Verification complete",
            meta={"verification_result": verification_result},
        )
    )
    return update


def fraud_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run fraud heuristics / (optional) LLM classification to generate fraud signals.
    """
    extracted_facts = state.get("extracted_facts") or {}
    verification_result = state.get("verification_result") or {}

    amount = extracted_facts.get("amount")
    incident_type = extracted_facts.get("incident_type")

    missing_critical = amount in (None, "", []) or incident_type in (None, "", [])
    policy_invalid = verification_result.get("status") == "invalid"

    # Deterministic heuristic first.
    if policy_invalid:
        fraud_risk = "high"
        reasons = ["policy invalid"]
    elif missing_critical:
        fraud_risk = "high"
        reasons = ["missing critical fields"]
    elif isinstance(amount, (int, float)) and amount >= 100000:
        fraud_risk = "high"
        reasons = ["amount exceeds threshold"]
    elif incident_type == "unknown":
        fraud_risk = "medium"
        reasons = ["incident_type unknown"]
    else:
        fraud_risk = "low"
        reasons = ["heuristic checks passed"]

    used_llm = False

    # Optional LangChain integration:
    # Pass `config={"llm": your_llm}` where your_llm has `.invoke(...)`.
    llm = (config or {}).get("llm")
    if llm is not None:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore

            prompt = (
                "You are a fraud classifier for insurance claims.\n"
                "Return exactly one token: `high`, `medium`, or `low`.\n\n"
                f"claim_facts: {extracted_facts}\n"
                f"verification_result: {verification_result}\n"
            )
            messages = [
                SystemMessage(content="Classify the provided insurance claim for fraud risk."),
                HumanMessage(content=prompt),
            ]
            resp = llm.invoke(messages)
            text = getattr(resp, "content", None) or str(resp)
            normalized = text.strip().lower()
            if "high" in normalized:
                fraud_risk = "high"
            elif "medium" in normalized:
                fraud_risk = "medium"
            elif "low" in normalized:
                fraud_risk = "low"
            used_llm = True
        except Exception:
            used_llm = False

    fraud_score_map: Dict[str, float] = {"low": 0.1, "medium": 0.6, "high": 0.9}
    fraud_score = float(fraud_score_map.get(fraud_risk, 0.0))

    fraud_result: Dict[str, Any] = {
        "fraud_risk": fraud_risk,
        "fraud_score": fraud_score,
        "reasons": reasons,
        "used_llm": used_llm,
    }

    update = {"status": "fraud_complete", "fraud_result": fraud_result}
    update.update(
        _append_event(
            state,
            node="fraud_node",
            message="Fraud signals generated",
            meta={"fraud_result": fraud_result},
        )
    )
    return update


def decision_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Make the final routing decision based on verification/fraud, plus any human review outcome.
    """
    verification_result = state.get("verification_result") or {}
    fraud_result = state.get("fraud_result") or {}
    human_review_result = state.get("human_review_result") or {}

    # If human review already completed, finalize based on it.
    if human_review_result.get("status") == "completed":
        outcome = human_review_result.get("outcome") or "approved"
        if outcome in ("approved", "approve"):
            decision_outcome = "approved"
            reason = human_review_result.get("reason") or "human approved claim"
        elif outcome in ("denied", "deny"):
            decision_outcome = "denied"
            reason = human_review_result.get("reason") or "human denied claim"
        else:
            decision_outcome = "approved"
            reason = "human review outcome defaulted to approved"
    else:
        # No human decision yet; decide based on verification/fraud.
        status = verification_result.get("status")
        fraud_score = float(fraud_result.get("fraud_score") or 0.0)
        fraud_risk = fraud_result.get("fraud_risk")

        if status == "invalid":
            decision_outcome = "denied"
            reason = verification_result.get("reason") or "policy invalid"
        elif status == "needs_review" or fraud_score > 0.7 or fraud_risk in ("high", "medium"):
            decision_outcome = "human_review"
            reason = "verification needs review or fraud risk elevated"
        else:
            decision_outcome = "approved"
            reason = "verification OK and fraud risk acceptable"

    decision_result = {
        "outcome": decision_outcome,
        "reason": reason,
        "verification_status": verification_result.get("status"),
        "fraud_risk": fraud_result.get("fraud_risk"),
        "fraud_score": fraud_result.get("fraud_score"),
        "human_review_required": decision_outcome == "human_review",
    }

    update = {"status": "decision_complete", "decision_result": decision_result}
    update.update(
        _append_event(
            state,
            node="decision_node",
            message=f"Decision made: {decision_outcome}",
            meta={"decision_result": decision_result},
        )
    )
    return update


def human_review_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Manual review placeholder.

    In production, this would likely:
    - emit a task to a human queue
    - optionally interrupt execution until the outcome is provided
    - then set `human_review_result` to unblock routing
    """
    decision_result = state.get("decision_result") or {}

    if decision_result.get("outcome") != "human_review" and (state.get("human_review_result") or {}).get("status") != "completed":
        # No-op: routing should prevent unnecessary execution.
        return {
            "status": "human_review_complete",
        }

    claim_input = _claim_input(state)
    requested_outcome = claim_input.get("human_review_decision", claim_input.get("human_review_outcome"))
    requested_outcome = requested_outcome.lower() if isinstance(requested_outcome, str) else requested_outcome

    manual_override_decision = claim_input.get("manual_override_decision")
    manual_override_decision = (
        manual_override_decision.lower() if isinstance(manual_override_decision, str) else manual_override_decision
    )
    escalation_comment = claim_input.get("escalation_comment")
    reviewer = claim_input.get("human_reviewer") or "unknown_reviewer"

    manual_override = manual_override_decision in ("approved", "approve", "denied", "deny")
    if manual_override:
        if manual_override_decision in ("approved", "approve"):
            outcome = "approved"
        else:
            outcome = "denied"
        reason = claim_input.get("manual_override_reason") or "manual override decision"
    else:
        if requested_outcome in ("approved", "approve", True):
            outcome = "approved"
        elif requested_outcome in ("denied", "deny", False):
            outcome = "denied"
        else:
            # If no decision was supplied on resume, keep workflow in review state.
            outcome = "human_review"
        reason = claim_input.get("human_review_notes") or "manual review completed"

    human_review_result: Dict[str, Any] = {
        "status": "completed" if outcome in ("approved", "denied") else "pending",
        "outcome": outcome,
        "reason": reason,
        "reviewer": reviewer,
        "manual_override": manual_override,
        "manual_override_reason": claim_input.get("manual_override_reason"),
        "escalation_comment": escalation_comment,
    }

    update = {"status": "human_review_complete", "human_review_result": human_review_result}
    update.update(
        _append_event(
            state,
            node="human_review_node",
            message="Human review completed" if human_review_result["status"] == "completed" else "Human review pending decision",
            meta={"human_review_result": human_review_result},
        )
    )
    return update


def payout_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Calculate payout amount based on decision and extracted claim facts.
    """
    extracted_facts = state.get("extracted_facts") or {}
    decision_result = state.get("decision_result") or {}

    amount = extracted_facts.get("amount")
    currency = extracted_facts.get("currency") or "USD"

    outcome = decision_result.get("outcome")
    payout_percent = state.get("claim_input", {}).get("payout_percent", 0.9) if state.get("claim_input") else 0.9

    if outcome == "approved" and isinstance(amount, (int, float)):
        payout_amount = int(amount * float(payout_percent))
        calc = {"amount": amount, "payout_percent": payout_percent}
    else:
        payout_amount = 0
        calc = {"amount": amount, "payout_percent": payout_percent, "note": "not eligible for payout"}

    payout_result = {"payout_amount": payout_amount, "currency": currency, "calculation": calc}

    update = {"status": "payout_calculated", "payout_result": payout_result}
    update.update(
        _append_event(
            state,
            node="payout_node",
            message="Payout calculation complete",
            meta={"payout_result": payout_result},
        )
    )
    return update


def escalation_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Escalate a high-value payout for human review.

    Example trigger: payout_amount > payout_escalation_threshold.
    """
    payout_result = state.get("payout_result") or {}
    decision_result = state.get("decision_result") or {}

    payout_amount = payout_result.get("payout_amount") or 0
    threshold = float(state.get("payout_escalation_threshold") or 0.0)

    count = int(state.get("escalation_count") or 0) + 1
    max_escalations = int(state.get("max_escalations") or 0)

    # Force decision outcome to human review so the graph path flows into it.
    decision_result = dict(decision_result)
    decision_result.update(
        {
            "outcome": "human_review",
            "reason": "payout_escalation_exceeded_threshold",
            "payout_amount": payout_amount,
            "payout_escalation_threshold": threshold,
            "escalation_count": count,
            "max_escalations": max_escalations,
            "human_review_required": True,
        }
    )

    update: Dict[str, Any] = {
        "status": "escalation_complete",
        "escalation_count": count,
        "decision_result": decision_result,
        # Reset payout calculation artifacts if you want; keeping them is useful for audit.
        "human_review_result": {},
    }

    update.update(
        _append_event(
            state,
            node="escalation_node",
            message="Escalation requested (forcing human review)"
            if count <= max_escalations
            else "Escalation limit exceeded (still forcing human review)",
            meta={
                "payout_amount": payout_amount,
                "threshold": threshold,
                "escalation_count": count,
                "max_escalations": max_escalations,
            },
        )
    )
    return update


def communication_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Send (or prepare) communications to the claimant and/or stakeholders.
    """
    decision_result = state.get("decision_result") or {}
    payout_result = state.get("payout_result") or {}
    extracted_facts = state.get("extracted_facts") or {}

    channel = (state.get("claim_input") or {}).get("communication_channel") or "email"

    outcome = decision_result.get("outcome")
    if outcome == "approved":
        message = f"Your claim has been approved. Payout: {payout_result.get('payout_amount')} {payout_result.get('currency')}"
        final_status = "resolved"
    else:
        message = f"Your claim requires manual review/was denied. Reason: {decision_result.get('reason')}"
        final_status = "denied"

    communication_result: Dict[str, Any] = {
        "channel": channel,
        "message": message,
        "status": "sent",
        "claim_date": extracted_facts.get("date"),
    }

    resolution = {
        "decision": outcome,
        "reason": decision_result.get("reason"),
        "verification_result": state.get("verification_result"),
        "fraud_result": state.get("fraud_result"),
        "human_review_result": state.get("human_review_result"),
        "payout_result": payout_result if outcome == "approved" else {},
        "communication_result": communication_result,
    }

    update = {
        # Final status used by API/UX.
        "status": final_status,
        "communication_result": communication_result,
        "resolution": resolution,
    }
    update.update(
        _append_event(
            state,
            node="communication_node",
            message="Communication completed",
            meta={"communication_result": communication_result, "final_status": final_status},
        )
    )
    return update


def extract_claim_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extract and normalize claim facts from `claim_input`.

    In a real system this is where you would use LangChain prompts, tools, and/or OCR/IE.
    """
    claim_input = state.get("claim_input") or {}

    extracted_facts: Dict[str, Any] = {
        "raw": claim_input,
        # Simple placeholders; replace with real extraction.
        "reported_amount": claim_input.get("amount"),
        "reported_date": claim_input.get("date"),
        "incident_type": claim_input.get("incident_type") or "unknown",
    }

    return {
        "status": "extracted",
        "extracted_facts": extracted_facts,
        "log": _append_log(state, "Extracted claim facts"),
    }


def validate_policy_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Validate the extracted facts against coverage rules / policy constraints.
    """
    extracted_facts = state.get("extracted_facts") or {}

    # Placeholder: decide coverage based on presence of incident_type.
    incident_type = extracted_facts.get("incident_type")
    is_covered = incident_type not in (None, "", "unknown")

    policy_validation: Dict[str, Any] = {
        "is_covered": is_covered,
        "reason": "incident_type missing/unknown" if not is_covered else "basic coverage check passed",
        "incident_type": incident_type,
    }

    return {
        "status": "policy_validated",
        "policy_validation": policy_validation,
        "log": _append_log(state, "Validated policy coverage"),
    }


def fraud_check_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run fraud heuristics (or an LLM classifier) over the claim.
    """
    extracted_facts = state.get("extracted_facts") or {}
    policy_validation = state.get("policy_validation") or {}

    # Placeholder heuristic: high risk if not covered or missing key fields.
    missing_critical = extracted_facts.get("reported_amount") is None or extracted_facts.get("reported_date") is None
    is_not_covered = not bool(policy_validation.get("is_covered"))

    fraud_risk = "high" if (is_not_covered or missing_critical) else "low"
    used_llm = False

    # Optional LangChain LLM integration:
    # If you pass a LangChain-compatible `llm` in `config`, we try to classify fraud risk.
    llm = (config or {}).get("llm")
    if llm is not None:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore

            prompt = (
                "You are a fraud classifier for insurance claims.\n"
                "Return exactly one token: `high` or `low`.\n\n"
                f"claim_facts: {extracted_facts}\n"
                f"policy_validation: {policy_validation}\n"
            )
            messages = [
                SystemMessage(content="Classify the provided insurance claim for fraud risk."),
                HumanMessage(content=prompt),
            ]
            resp = llm.invoke(messages)
            text = getattr(resp, "content", None) or str(resp)
            normalized = text.strip().lower()
            if "high" in normalized:
                fraud_risk = "high"
            elif "low" in normalized:
                fraud_risk = "low"
            used_llm = True
        except Exception:
            # Keep deterministic heuristic as fallback.
            used_llm = False

    fraud_signals: Dict[str, Any] = {
        "fraud_risk": fraud_risk,
        "missing_critical": missing_critical,
        "policy_not_covered": is_not_covered,
        "used_llm": used_llm,
    }

    return {
        "status": "fraud_checked",
        "fraud_signals": fraud_signals,
        "log": _append_log(state, "Completed fraud signal checks" + (" (LLM)" if used_llm else "")),
    }


def resolve_claim_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Produce a final resolution for covered, low-fraud claims.
    """
    policy_validation = state.get("policy_validation") or {}
    extracted_facts = state.get("extracted_facts") or {}

    amount = extracted_facts.get("reported_amount") or 0
    # Placeholder: approve at 90% of reported amount.
    approved_amount = int(amount * 0.9) if isinstance(amount, (int, float)) else amount

    resolution: Dict[str, Any] = {
        "decision": "approved",
        "approved_amount": approved_amount,
        "coverage_reason": policy_validation.get("reason"),
    }

    return {
        "status": "resolved",
        "resolution": resolution,
        "log": _append_log(state, "Resolved claim (approved)"),
    }


def fail_claim_node(state: ClaimResolutionState, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Produce a failure / manual-review resolution when fraud risk or coverage fails.
    """
    fraud_signals = state.get("fraud_signals") or {}
    policy_validation = state.get("policy_validation") or {}

    resolution: Dict[str, Any] = {
        "decision": "failed",
        "reason": "manual_review_due_to_high_fraud_or_coverage_failure",
        "fraud_risk": fraud_signals.get("fraud_risk"),
        "policy_is_covered": policy_validation.get("is_covered"),
    }

    return {
        "status": "failed",
        "resolution": resolution,
        "log": _append_log(state, "Resolved claim (failed/manual review)"),
    }

