# Plutus FNOL Navigator — a portfolio project

A small, complete "agentic assist" for First Notice of Loss (FNOL) intake in
P&C insurance — the first step when a policyholder reports a claim. An agent
reads a claim narrative, extracts structured data, grounds every coverage
and exclusion claim in an explicit policy knowledge base, decides how the
claim should be triaged, and logs a full decision trace. A dashboard makes
that trace reviewable, and a benchmark appendix compares two ways of serving
the extraction step at volume.

Built as a portfolio piece for a job application at [Plutus](https://plutustech.io)
(agentic AI for insurance on ServiceNow). It deliberately mirrors their
product architecture at small scale, and adds a serving/inference-optimization
angle — cost, latency, and prefix caching at volume — that most applicants to
an agentic-AI role won't bring.

## The five-minute story

1. **Navigator** (`agent/`) reads a claim narrative and, using Claude with
   tool calling, extracts structured fields as its *first* move — not as a
   free-text guess parsed afterward, but as an actual typed tool call
   (`record_extracted_fields`). That's what makes the rest of the trace
   reliable: everything downstream is built on a value the model committed
   to, not prose regex'd out of a paragraph. If the submission includes
   attached invoice/bill PDFs or damage photos, Navigator reviews them as
   real multimodal input (`record_attachment_review`) and can flag a claim
   whose photo evidence or billed amount doesn't line up with the narrative
   — not just text-only triage.
2. **Atlas** (`atlas/`) is the semantic layer. Eight synthetic policies, their
   coverages, and their exclusions live in a small explicit structure
   (`atlas/data/policies.json`) queried through a tiny networkx graph
   (`atlas/store.py`). The agent has *no policy data in its prompt* — every
   coverage or exclusion claim it makes has to come from a tool call into
   Atlas, and every one of those results carries a citation that points at a
   specific JSON path (`policy:POL-10891.exclusions[0]`), not generated text.
3. The agent decides `auto-approve intake`, `flag for adjuster review`, or
   `request more info`, and calls `submit_decision` with a reasoning summary,
   a confidence score, and evidence copied verbatim from its own tool
   results. The full Anthropic tool-use transcript — every call, every
   result — is saved alongside that decision. That transcript *is* the
   decision trace.
4. **Prism** (`dashboard/`) is a plain HTML/JS list-and-detail viewer over
   those traces: click a claim, see the original submission, the extracted
   fields, the cited policy evidence, the reasoning, and the raw tool-call
   trace underneath it. Flagged and low-confidence claims are visually
   pushed to the front so a human reviewer's eye lands there first.
5. **The benchmark** (`benchmark/`) isolates just the extraction step and
   compares running it via Claude Haiku (API) against a self-hosted
   quantized model on vLLM — with prefix caching as the specific lever,
   since FNOL intake shares a large fixed prompt (instructions + policy
   context) across every request. See `benchmark/results/results.md` for
   the numbers and what's measured vs. estimated.

## Mapping to Plutus's architecture

| This project | Plutus | What it demonstrates |
|---|---|---|
| `agent/` (Navigator) | **Navigator** — agentic orchestration | An agent that underwrites/triages in real time via tool calling, not a single free-text LLM call |
| `atlas/` (Atlas) | **Atlas** — semantic layer / knowledge graph | Domain knowledge (policies, coverage, exclusions) as an explicit, queryable structure the agent grounds itself in, not baked into a prompt |
| `dashboard/` (Prism) | **Prism** — real-time decision visualization | A reviewer-facing view of agent decisions with low-confidence/flagged items surfaced proactively |
| `benchmark/` | *(differentiator)* | Serving cost/latency/KV-cache tradeoffs — the kind of inference-optimization reasoning most agentic-AI candidates don't bring |

## Repository layout

```
atlas/                  Policy/coverage knowledge base + graph queries
  data/policies.json     8 synthetic policies (auto + homeowners)
  models.py               Typed records + the coverage->loss_type mapping
  store.py                 Loads policies.json into a networkx graph
  rules.py                  Citation-bearing query functions (the agent's tools)

agent/                  The Navigator agent
  schemas.py              Pydantic models for the decision trace
  tools.py                  Anthropic tool-use JSON schemas
  fnol_agent.py              The extraction -> Atlas -> decision loop; process_claim (fresh),
                               resume_claim (policy number attached after the fact), and the
                               multimodal attachment content-block builder all live here
  generate_synthetic_claims.py  26 synthetic FNOL narratives + deliberate edge cases
  run_batch.py                   Runs every claim through the agent, saves traces
  data/claims/, data/traces/      Generated input/output (traces gitignored)
  data/attachments/                Uploaded invoice PDFs / damage photos, per claim_id (gitignored)

dashboard/               Prism trace viewer
  index.html, app.js, styles.css   Static, no build step; includes the "+ New claim" intake
                                     modal (narrative + file uploads) and the Attachments card
  server.py                          FastAPI: static files + /api/claims, /api/claims/process
                                        (multipart, with attachments), /api/atlas/search,
                                        /api/claims/{id}/resume, /api/claims/{id}/attachments/{filename}

benchmark/               Serving cost/latency comparison (Part 4)
  common_prompts.py         Shared extraction prompt both benchmarks use
  api_bench.py                 REAL: Claude Haiku, with/without prompt caching
  vllm_bench.py                  SCAFFOLDED: self-hosted vLLM, needs a GPU
  run_all.py                       Prints a combined comparison table
  results/results.md                 Methodology + measured vs. estimated numbers
```

## Running it

### 1. Setup

```bash
cd plutus-fnol-navigator
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env        # then fill in ANTHROPIC_API_KEY
```

### 2. Run the agent end-to-end on one claim

```python
from agent.fnol_agent import process_claim

trace = process_claim("demo-1", "Maria Alvarez, policy POL-10234. Rear-ended at a stoplight on "
                       "2026-07-14, damage to the rear bumper, about $4,200.")
print(trace.decision, trace.confidence)
print(trace.reasoning_summary)
```

### 3. Run the full batch and populate the dashboard

```bash
python -m agent.run_batch
```

This runs all 26 synthetic claims through the live agent (needs
`ANTHROPIC_API_KEY`), writes one trace per claim to `agent/data/traces/`, and
regenerates `dashboard/data.js` for the static viewer.

### 4. View the dashboard

```bash
uvicorn dashboard.server:app --reload
```

Open `http://127.0.0.1:8000`. Two working fixture traces are checked into
`agent/data/traces/` so the dashboard has something to show immediately,
before you've run a real batch or added an API key — `python -m agent.run_batch`
replaces them with real agent output. The dashboard also works opened
directly as a file (`dashboard/index.html`) once `data.js` exists, no server
required — `server.py` additionally exposes `POST /api/claims/process` to
run a brand-new narrative through the live agent from the browser.

The **"+ New claim" button** in the header opens a demo intake form —
narrative text plus optional invoice/bill PDFs and damage-photo JPG/PNGs.
This stands in for the customer-facing portal that doesn't exist in this
repo (in the real architecture, customers submit through their own channel,
not through Prism, which is employee-only). Submitting runs the live agent
with the attachments as real multimodal input and drops the new claim
straight into the list. Each claim's detail view shows an **Attachments**
card (photo thumbnails, PDF links) with the agent's per-attachment
observation underneath, when any were provided.

### 5. Deploy the dashboard (optional)

`vercel.json` at the repo root points Vercel at `dashboard/` as a static
site — no build step, no backend, no API key needed to view it. It serves
whatever's in `dashboard/data.js` at deploy time, so regenerate that (`python
-m agent.run_batch`) and commit it before deploying to refresh what's shown.
`/api/claims/process` and friends (the live "run a new narrative through the
agent," Atlas search, and resume endpoints) only exist in
`dashboard/server.py` and aren't part of this static deploy, including the
"+ New claim" upload form - the hosted version is read-only, on purpose.

```bash
npm i -g vercel   # one-time
vercel            # first run links/creates the Vercel project, then deploys
vercel --prod     # subsequent production deploys
```

Or connect the GitHub repo at vercel.com/new and let it auto-deploy on push -
no CLI needed either way, since `vercel.json` already tells it where to look.

### 6. Run the benchmark

```bash
python -m benchmark.api_bench          # real, needs ANTHROPIC_API_KEY
python -m benchmark.run_all            # prints whatever results exist
```

`benchmark/vllm_bench.py` needs a GPU and a running vLLM server — see its
docstring and `benchmark/results/results.md` for exact commands. It's not
executable in this dev environment, so its numbers there are clearly labeled
ESTIMATED with every assumption stated.

## Design notes worth walking an interviewer through

- **Why extraction is a tool call, not a free-text first message:** it turns
  the least reliable part of an LLM pipeline (getting structured data out of
  prose) into a typed, validated step, and it means the dashboard never has
  to parse anything — it just renders JSON.
- **Why Atlas has no LLM in it at all:** grounding only works if the ground
  truth can't drift. Atlas is plain Python + a JSON file + networkx; the
  agent calls into it the same way it would call any other backend service.
- **Why citations point at JSON paths instead of quoting policy text:** a
  citation like `policy:POL-10891.exclusions[0]` is checkable — you can go
  look at exactly that field in `policies.json` and verify the agent didn't
  hallucinate a clause. A citation that's just re-generated prose isn't.
- **Why the benchmark isolates the extraction step specifically:** it's the
  one step in the pipeline that runs at "volume" in a way worth optimizing —
  decisioning needs the stronger model's judgment, but extraction is
  structurally simple and repeats a large shared prompt, which is exactly
  the shape prefix caching is built for.

## What's out of scope (by design)

This is a portfolio piece, not production software: no auth on the
dashboard or API, no database (traces are flat JSON files), no retry/backoff
tuning, no real PII (every name, policy number, and address is invented),
and the vLLM benchmark numbers are honestly labeled as estimates rather than
faked. Attachment uploads get a content-type allowlist (PDF for invoices,
JPG/PNG for photos) and a 10MB size cap, but nothing beyond that - no
malware/virus scanning, no PII redaction in images, no retention policy for
`agent/data/attachments/`, none of which a real intake system could skip.
The point is a coherent, explainable system end to end, not production
hardening.
