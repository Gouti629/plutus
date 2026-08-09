# Serving cost & latency benchmark — methodology and results

This is the Part 4 technical appendix: comparing API-based (Claude Haiku) vs.
self-hosted (quantized open-weight model on vLLM) serving of the FNOL
**extraction step** — not the full agent loop, just the structured-extraction
call from `agent/fnol_agent.py`'s first tool call, isolated so it's a fair
apples-to-apples comparison across both serving paths.

Every number below is labeled **MEASURED** or **ESTIMATED**. Nothing here is
fabricated precision dressed up as a real benchmark — see the note in each
section on exactly how the number was produced.

## Why this comparison, and why prefix caching specifically

FNOL submissions share a lot of structure: the same extraction instructions,
the same field definitions, and the same policy-lookup context (Atlas's
policy master list) are attached to every single call — only the claim
narrative itself changes request to request. `benchmark/common_prompts.py`
builds that shared prefix once and reuses it for both benchmarks, so the
comparison is: **does the serving layer actually exploit that repetition,
and how much does it save?**

- On the Claude API, that's Anthropic prompt caching (`cache_control` on the
  system block).
- On vLLM, that's automatic prefix caching (`--enable-prefix-caching`),
  which caches shared KV-cache blocks across requests server-side with no
  code change required.

## Methodology

- 26 synthetic FNOL narratives (`agent/data/claims/`), each repeated 3x, run
  through the extraction-only prompt in `benchmark/common_prompts.py`
  (instructions + loss-type reference + worked examples + full policy master
  list — ~3,500+ tokens of shared prefix, comfortably above every current
  Claude model's cache-eligibility minimum).
- Latency is measured wall-clock per request (`time.perf_counter()`), not a
  server-reported figure, so it includes network round-trip.
- Anthropic cost is computed from the real `usage.input_tokens`,
  `usage.output_tokens`, `usage.cache_creation_input_tokens`, and
  `usage.cache_read_input_tokens` returned on every response, priced at
  published Claude Haiku 4.5 list rates ($1.00 / $5.00 per MTok input/output;
  cache write ≈1.25x input, cache read ≈0.1x input).
- vLLM cost is a wall-clock-time-to-GPU-rental-rate projection
  (`gpu_hourly_cost / 3600 × avg_latency × 1000`), since GPU rental is billed
  by time, not tokens — this is explicitly an estimate unless you substitute
  your actual cloud bill.

## Results

### API-based: Claude Haiku 4.5 — **MEASURED**

*(Not measured in this sandbox — there is no `ANTHROPIC_API_KEY` configured
here. Run `python -m benchmark.api_bench` with a key set and this table
fills in automatically from `benchmark/results/api_bench_results.json`.)*

| condition | p50 latency | p99 latency | throughput | cache hit rate | $ / 1,000 docs |
|---|---|---|---|---|---|
| no prompt caching | *run to fill in* | | | n/a | |
| with prompt caching | *run to fill in* | | | | |

**Expected direction, based on Anthropic's published cache economics** (this
line is reasoning, not a measurement): cache reads are priced at ~0.1x base
input tokens. With a ~3,500-token shared prefix and a short (~100–200 token)
per-claim narrative, the prefix dominates input token count on every call, so
once the cache is warm, cost per call should drop by roughly 60–80% versus
the uncached condition, and latency should drop meaningfully too since the
model doesn't re-process the full prefix from scratch. The actual percentage
depends on real token counts and is filled in above once run.

### Self-hosted: vLLM + quantized open-weight model — **ESTIMATED**

Not measured — no GPU is available in this development sandbox.
`benchmark/vllm_bench.py` is fully scaffolded to run against a live vLLM
OpenAI-compatible endpoint; the numbers below are order-of-magnitude
estimates for context, built from public vLLM/GPU-rental benchmarks, with
every assumption stated explicitly.

**Assumptions:**
- Model: Qwen2.5-7B-Instruct, AWQ (INT4) quantization
- GPU: single NVIDIA L4 or A10G (24GB), on-demand cloud rental
- GPU rental rate: **$2.50/hour** (a rough on-demand single-GPU rate as of
  2026 across common providers — RunPod/Lambda-style pricing; substitute
  your actual rate with `--gpu-hourly-cost`)
- Throughput: ~800–1,500 output tokens/sec aggregate on an L4/A10G for a
  7B AWQ model under light concurrent load (published community vLLM
  benchmarks for similarly-sized quantized models in this class)
- Extraction call: ~3,500 prompt tokens (shared prefix) + ~150 completion
  tokens per request

| condition | p50 latency (est.) | throughput (est.) | $ / 1,000 docs (est.) |
|---|---|---|---|
| no prefix caching | ~1.5–3.0s | ~15–25 req/s (batched) | ~$0.15–0.30 |
| with prefix caching enabled | ~0.4–1.0s | ~40–70 req/s (batched) | ~$0.05–0.10 |

The estimated delta comes from prefix caching eliminating repeated prefill
compute for the ~3,500 shared prefix tokens on every request after the
first — prefill is the dominant cost for a short-completion, long-prompt
workload like structured extraction, so this is the single highest-leverage
lever available on self-hosted serving for this workload shape, more so than
for the Haiku comparison where the base per-token price is already low.

**To fill this in with real numbers:**

```bash
# On a GPU box:
pip install vllm
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ --quantization awq --port 8000
python -m benchmark.vllm_bench --label no_prefix_cache --repeats 3

# Restart with --enable-prefix-caching, then:
python -m benchmark.vllm_bench --label prefix_cache --repeats 3

# From the project root, on either machine:
python -m benchmark.run_all
```

## The takeaway (to fill in once api_bench.py has run)

Once `api_bench.py` has real numbers, the interview-ready story is: at low
volume, Claude Haiku's simplicity and zero infra overhead wins outright —
there's no GPU to provision, no server to keep warm, and prompt caching
still meaningfully cuts cost with zero code complexity beyond one
`cache_control` field. At high steady-state volume with a large shared
prefix like FNOL intake's, self-hosted serving with prefix caching enabled
becomes cost-competitive or cheaper per document, because GPU rental is a
fixed hourly cost amortized across every request rather than a per-token
charge — the crossover point depends on sustained request volume, which is
exactly the kind of trade-off a serving/inference background lets you reason
about concretely instead of defaulting to "just call the API."
