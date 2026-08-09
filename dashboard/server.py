"""FastAPI app for Prism: serves the dashboard's static files plus a small
JSON API over the traces the Navigator agent has produced.

Run from the project root with:
    uvicorn dashboard.server:app --reload

GET  /api/claims            -> list of all saved traces (agent/data/traces/*.json)
GET  /api/claims/{claim_id} -> one trace
POST /api/claims/process    -> run a new narrative through the live agent
                                (requires ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.fnol_agent import DEFAULT_MODEL, process_claim

TRACES_DIR = Path(__file__).parent.parent / "agent" / "data" / "traces"
STATIC_DIR = Path(__file__).parent

app = FastAPI(title="Prism - FNOL Decision Trace Viewer")


def _load_traces() -> list[dict]:
    traces = []
    for path in sorted(TRACES_DIR.glob("*.json")):
        traces.append(json.loads(path.read_text()))
    return traces


@app.get("/api/claims")
def list_claims() -> list[dict]:
    return _load_traces()


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: str) -> dict:
    path = TRACES_DIR / f"{claim_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No trace for claim_id '{claim_id}'.")
    return json.loads(path.read_text())


class ProcessRequest(BaseModel):
    claim_id: str
    submitted_text: str
    model: str = DEFAULT_MODEL


@app.post("/api/claims/process")
def process_new_claim(req: ProcessRequest) -> dict:
    """Run a narrative through the live agent and persist its trace.

    This is the "process a new submission end-to-end" path referenced in the
    README - it calls the real Anthropic API, so it needs ANTHROPIC_API_KEY.
    """
    trace = process_claim(req.claim_id, req.submitted_text, model=req.model)
    trace_dict = trace.model_dump(mode="json")
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    (TRACES_DIR / f"{req.claim_id}.json").write_text(json.dumps(trace_dict, indent=2))
    return trace_dict


# Static files last, so /api/* above takes priority over the catch-all mount.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="dashboard")
