from __future__ import annotations

import json
import os

from production.workflows import run_claim_resolution_workflow, resume_claim_resolution_workflow


def _print(title: str, obj: object) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print(json.dumps(obj, indent=2, default=str))


def main() -> None:
    redis_url = os.getenv("REDIS_URL")

    # 1) Happy path
    out1 = run_claim_resolution_workflow(
        claim_id="claim-happy",
        claim_input={
            "amount": 1000,
            "date": "2026-05-01",
            "incident_type": "fire",
            "policy_number": "P-123",
        },
        redis_url=redis_url,
    )
    _print("TRACE 1 - Happy path", out1)

    # 2) OCR failure -> OCR retry loop
    out2 = run_claim_resolution_workflow(
        claim_id="claim-ocr",
        claim_input={
            "amount": 2500,
            "date": "2026-05-01",
            "incident_type": "fire",
            "policy_number": "P-123",
            "ocr_fail": True,
            "max_ocr_retries": 1,
        },
        redis_url=redis_url,
    )
    _print("TRACE 2 - OCR failure with retry", out2)

    # 3) Missing fields -> intake retry loop then fallback to human review
    out3 = run_claim_resolution_workflow(
        claim_id="claim-missing",
        claim_input={
            "amount": None,
            "date": None,
            "incident_type": None,
            "policy_number": "P-123",
            "max_intake_retries": 1,
            "intake_retry_fix": {"amount": 500, "date": "2026-05-01", "incident_type": "fire"},
        },
        redis_url=redis_url,
    )
    _print("TRACE 3 - Missing fields with intake retry", out3)

    # 4) Fraud score -> human review interrupt
    out4 = run_claim_resolution_workflow(
        claim_id="claim-fraud",
        claim_input={
            "amount": 200000,
            "date": "2026-05-01",
            "incident_type": "fire",
            "policy_number": "P-123",
        },
        redis_url=redis_url,
    )
    _print("TRACE 4 - High fraud -> human review pending", out4)
    if out4.get("status") == "human_review_pending":
        out4_resume = resume_claim_resolution_workflow(
            claim_id="claim-fraud",
            review_payload={
                "human_review_decision": "approved",
                "human_reviewer": "fraud-auditor-1",
                "human_review_notes": "Approved after document review.",
                "escalation_comment": "Escalated to fraud team; resolved.",
            },
            redis_url=redis_url,
        )
        _print("TRACE 4R - Resume after approval", out4_resume)

    # 5) Payout escalation -> human review interrupt
    out5 = run_claim_resolution_workflow(
        claim_id="claim-escalation",
        claim_input={
            "amount": 250000,
            "date": "2026-05-01",
            "incident_type": "fire",
            "policy_number": "P-123",
            "payout_percent": 0.9,
            "payout_escalation_threshold": 100000,
        },
        redis_url=redis_url,
    )
    _print("TRACE 5 - Payout escalation -> human review pending", out5)
    if out5.get("status") == "human_review_pending":
        out5_resume = resume_claim_resolution_workflow(
            claim_id="claim-escalation",
            review_payload={
                "human_review_decision": "denied",
                "human_reviewer": "payout-escalations-2",
                "human_review_notes": "Denied due to policy mismatch.",
                "escalation_comment": "Escalation denied after policy check.",
                "manual_override_decision": None,
            },
            redis_url=redis_url,
        )
        _print("TRACE 5R - Resume after denial", out5_resume)


if __name__ == "__main__":
    main()

