# claimorchestrator-langgraph
Enterprise Multi-Agent Insurance Claims Resolution System using LangGraph.

## Quick run (CLI)

```powershell
pip install -r requirements.txt
python run_demo.py
```

Expected: `"status": "resolved"` and payout in the JSON output.

## Run the API

1. Install deps:
   - `pip install -r requirements.txt`
2. Start server (from repo root):

```powershell
$env:PYTHONPATH = (Get-Location).Path
uvicorn production.api.main:app --reload --host 127.0.0.1 --port 8000
```

3. Resolve a claim:

```powershell
python -c "import requests, json; r=requests.post('http://127.0.0.1:8000/claims/demo-claim/resolve', json={'claim_input': {'amount': 1000, 'date': '2026-05-01', 'incident_type': 'fire', 'policy_number': 'P-123'}}); print(json.dumps(r.json(), indent=2))"
```

## Endpoints

- `GET /health`
- `POST /claims/{claim_id}/resolve` (sync)
- `POST /claims/{claim_id}/resolve-async` (async)
- `POST /claims/{claim_id}/human-review` (resume after interrupt)
- `POST /claims/{claim_id}/human-review-async` (async resume)
- `GET /workflow/mermaid` (graph visualization)

## Example traces

- `python production/examples/example_traces.py`

