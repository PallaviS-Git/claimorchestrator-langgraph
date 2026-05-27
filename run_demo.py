"""Run a single happy-path claim and print JSON result."""
from __future__ import annotations

import json
import os
import sys

# Ensure repo root is on PYTHONPATH when run as `python run_demo.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from production.workflows import run_claim_resolution_workflow


def main() -> None:
    result = run_claim_resolution_workflow(
        claim_id="demo-claim-cli",
        claim_input={
            "amount": 1000,
            "date": "2026-05-01",
            "incident_type": "fire",
            "policy_number": "P-123",
        },
        redis_url=os.getenv("REDIS_URL"),
    )
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") != "resolved":
        raise SystemExit(1)
    print("\nSUCCESS: claim resolved.")


if __name__ == "__main__":
    main()
