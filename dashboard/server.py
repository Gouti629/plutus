"""FastAPI app for Prism: serves the dashboard's static files plus a small
JSON API over the traces the Navigator agent has produced.

Run from the project root with:
    uvicorn dashboard.server:app --reload

GET  /api/claims                       -> list of all saved traces (agent/data/traces/*.json)
GET  /api/claims/{claim_id}            -> one trace
POST /api/claims/process               -> run a new narrative (+ optional invoice/photo
                                           attachments) through the live agent
                                           (requires ANTHROPIC_API_KEY; multipart/form-data)
GET  /api/claims/{claim_id}/attachments/{filename} -> serves one uploaded attachment
GET  /api/atlas/search?name=...        -> search Atlas policies by holder name
POST /api/claims/{claim_id}/resume     -> attach a reviewer-resolved policy number
                                           to an existing claim and resume
                                           decisioning without re-extracting
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.fnol_agent import DEFAULT_MODEL, process_claim, resume_claim
from atlas import rules as atlas_rules

PROJECT_ROOT = Path(__file__).parent.parent
TRACES_DIR = PROJECT_ROOT / "agent" / "data" / "traces"
ATTACHMENTS_DIR = PROJECT_ROOT / "agent" / "data" / "attachments"
STATIC_DIR = Path(__file__).parent

ALLOWED_ATTACHMENT_TYPES = {
    "invoice": {"application/pdf"},
    "damage_photo": {"image/jpeg", "image/png"},
}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB per file - a sane guard, not a real limits review

app = FastAPI(title="Prism - FNOL Decision Trace Viewer")


def _safe_filename(name: str) -> str:
    """Strips directory components and anything but ordinary filename
    characters, so an uploaded/requested filename can't be used for path
    traversal (e.g. '../../etc/passwd')."""
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "file"


async def _save_attachments(claim_id: str, kind: str, files: list[UploadFile]) -> list[dict]:
    allowed = ALLOWED_ATTACHMENT_TYPES[kind]
    claim_dir = ATTACHMENTS_DIR / claim_id
    saved = []
    for f in files:
        if f.content_type not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"'{f.filename}' has unsupported type '{f.content_type}' for a {kind} attachment.",
            )
        data = await f.read()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail=f"'{f.filename}' exceeds the 10MB attachment limit.")
        claim_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_filename(f.filename or "file")
        dest = claim_dir / safe_name
        dest.write_bytes(data)
        saved.append(
            {
                "filename": safe_name,
                "kind": kind,
                "content_type": f.content_type,
                "path": str(dest.relative_to(PROJECT_ROOT)),
                "size_bytes": len(data),
            }
        )
    return saved


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


@app.post("/api/claims/process")
async def process_new_claim(
    claim_id: str = Form(...),
    submitted_text: str = Form(...),
    model: str = Form(DEFAULT_MODEL),
    invoices: list[UploadFile] = File(default=[]),
    damage_photos: list[UploadFile] = File(default=[]),
) -> dict:
    """Run a narrative - plus any attached invoice PDFs / damage photos -
    through the live agent and persist its trace.

    This is the "process a new submission end-to-end" path referenced in the
    README - it calls the real Anthropic API, so it needs ANTHROPIC_API_KEY.
    multipart/form-data, not JSON, since it accepts file uploads.
    """
    attachments = await _save_attachments(claim_id, "invoice", invoices)
    attachments += await _save_attachments(claim_id, "damage_photo", damage_photos)

    trace = process_claim(claim_id, submitted_text, attachments=attachments, model=model)
    trace_dict = trace.model_dump(mode="json")
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    (TRACES_DIR / f"{claim_id}.json").write_text(json.dumps(trace_dict, indent=2))
    return trace_dict


@app.get("/api/claims/{claim_id}/attachments/{filename}")
def get_attachment(claim_id: str, filename: str) -> FileResponse:
    """Serves one uploaded attachment - used by the dashboard for damage-photo
    thumbnails and invoice PDF links."""
    path = ATTACHMENTS_DIR / _safe_filename(claim_id) / _safe_filename(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No attachment '{filename}' for claim_id '{claim_id}'.")
    return FileResponse(path)


@app.get("/api/atlas/search")
def search_atlas(name: str) -> list[dict]:
    """Search Atlas for policies by holder name - used by the "missing
    policy number" follow-up UI to resolve a real policy_number instead of
    guessing one or asking the customer to resubmit."""
    return atlas_rules.search_policies_by_name(name)


class ResumeRequest(BaseModel):
    policy_number: str


@app.post("/api/claims/{claim_id}/resume")
def resume_claim_endpoint(claim_id: str, req: ResumeRequest) -> dict:
    """Attach a policy number a reviewer resolved (via Atlas search or a
    real out-of-band channel) to an existing claim and resume decisioning
    from the Atlas lookup step - not a re-run of extraction, since the
    narrative itself hasn't changed. Needs ANTHROPIC_API_KEY.
    """
    path = TRACES_DIR / f"{claim_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No trace for claim_id '{claim_id}'.")
    existing = json.loads(path.read_text())
    extracted = {**(existing.get("extracted") or {}), "policy_number": req.policy_number}

    trace = resume_claim(claim_id, existing["submitted_text"], extracted, model=DEFAULT_MODEL)
    trace_dict = trace.model_dump(mode="json")
    trace_dict["edge_case"] = existing.get("edge_case")
    path.write_text(json.dumps(trace_dict, indent=2))
    return trace_dict


# Static files last, so /api/* above takes priority over the catch-all mount.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="dashboard")
