"""Scaffolded benchmark for a self-hosted quantized model served via vLLM.

Not executed in this environment - there's no GPU in this sandbox. This
script is written to run as-is against a live vLLM OpenAI-compatible
endpoint (e.g. an AWQ/INT4 Llama-3.1-8B-Instruct or Qwen2.5-7B-Instruct on a
RunPod/Lambda GPU box). See benchmark/results/results.md for how its numbers
are estimated in the meantime, and for instructions on filling in real ones.

vLLM prefix caching (`--enable-prefix-caching`) is a *server startup flag*,
not a per-request option, so this script can't toggle it mid-run. The
intended methodology is: start the vLLM server once with prefix caching on
and once with it off, run this script against each, and diff the two
`results/vllm_bench_*.json` files it writes.

    # Server 1 (baseline, no prefix caching):
    vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ --quantization awq \\
        --port 8000

    # Server 2 (prefix caching on):
    vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ --quantization awq \\
        --enable-prefix-caching --port 8000

    python -m benchmark.vllm_bench --label no_prefix_cache --repeats 3
    # ... restart server with --enable-prefix-caching, then:
    python -m benchmark.vllm_bench --label prefix_cache --repeats 3

Requires: pip install openai (OpenAI-compatible client; vLLM speaks the same
wire format), and a running vLLM server at VLLM_ENDPOINT.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmark.common_prompts import build_shared_prefix, load_claim_narratives

RESULTS_DIR = Path(__file__).parent / "results"

DEFAULT_ENDPOINT = os.environ.get("VLLM_ENDPOINT", "http://localhost:8000/v1")
DEFAULT_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")


@dataclass
class CallResult:
    latency_s: float
    prompt_tokens: int
    completion_tokens: int


@dataclass
class ConditionResult:
    label: str
    calls: list[CallResult] = field(default_factory=list)

    def summarize(self, gpu_hourly_cost_usd: float) -> dict:
        latencies = sorted(c.latency_s for c in self.calls)

        def pct(p: float) -> float:
            if not latencies:
                return 0.0
            idx = min(len(latencies) - 1, int(len(latencies) * p))
            return latencies[idx]

        n = len(self.calls)
        total_wallclock = sum(c.latency_s for c in self.calls)
        # Cost model: GPU rental is billed by wall-clock time regardless of
        # how many tokens flow through it, so cost/1000 docs is just the
        # rental rate applied to the wall-clock time this batch consumed,
        # scaled to 1000 documents. Requires --gpu-hourly-cost from the
        # caller; label it ESTIMATED unless it's the actual RunPod/Lambda bill.
        cost_per_1000 = (gpu_hourly_cost_usd / 3600) * (total_wallclock / n) * 1000 if n else 0.0

        return {
            "label": self.label,
            "n_calls": n,
            "p50_latency_s": round(pct(0.50), 3),
            "p99_latency_s": round(pct(0.99), 3),
            "mean_latency_s": round(statistics.mean(latencies), 3) if latencies else 0.0,
            "throughput_req_per_s": round(n / total_wallclock, 3) if total_wallclock else 0.0,
            "total_prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "total_completion_tokens": sum(c.completion_tokens for c in self.calls),
            "gpu_hourly_cost_usd_assumption": gpu_hourly_cost_usd,
            "cost_per_1000_docs_usd": round(cost_per_1000, 4),
            "cost_basis": "ESTIMATED from wall-clock time x assumed GPU hourly rate, not a measured cloud bill",
        }


def run(
    endpoint: str,
    model: str,
    repeats: int,
    limit: int | None,
    label: str,
    gpu_hourly_cost_usd: float,
) -> dict:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "This script needs the 'openai' package (OpenAI-compatible client for vLLM). "
            "Install with: pip install openai"
        ) from exc

    client = OpenAI(base_url=endpoint, api_key="not-needed-for-local-vllm")
    shared_prefix = build_shared_prefix()
    narratives = load_claim_narratives(limit=limit)

    result = ConditionResult(label=label)
    print(f"Running {len(narratives)} claims x {repeats} repeats against {model} @ {endpoint} (label={label}) ...")

    for narrative in narratives:
        for _ in range(repeats):
            start = time.perf_counter()
            response = client.chat.completions.create(
                model=model,
                max_tokens=512,
                messages=[
                    {"role": "system", "content": shared_prefix},
                    {"role": "user", "content": narrative},
                ],
                # vLLM's OpenAI-compatible server accepts a raw JSON-schema
                # response_format for guided decoding on supported backends;
                # left permissive here since guided-decoding config varies
                # by vLLM version and backend (outlines/lm-format-enforcer).
            )
            elapsed = time.perf_counter() - start
            usage = response.usage
            result.calls.append(
                CallResult(
                    latency_s=elapsed,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                )
            )

    summary = {
        "endpoint": endpoint,
        "model": model,
        "n_claims": len(narratives),
        "repeats_per_claim": repeats,
        **result.summarize(gpu_hourly_cost_usd),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"vllm_bench_{label}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote results to {out_path}")
    print(json.dumps(summary, indent=2))
    print(
        "\nNote: vLLM's chat/completions response does not report prefix-cache hits per request. "
        "To confirm caching actually engaged, check the server's Prometheus metrics endpoint "
        "(vllm:gpu_prefix_cache_hit_rate) or server logs while this script runs."
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--label", default="run", help="Distinguishes this run's output file, e.g. 'prefix_cache' vs 'no_prefix_cache'")
    parser.add_argument(
        "--gpu-hourly-cost",
        type=float,
        default=2.50,
        help="USD/hour GPU rental assumption for cost projection (default: 2.50, a rough single-L4/A10G on-demand rate as of 2026 - override with your actual rate)",
    )
    args = parser.parse_args()
    run(
        endpoint=args.endpoint,
        model=args.model,
        repeats=args.repeats,
        limit=args.limit,
        label=args.label,
        gpu_hourly_cost_usd=args.gpu_hourly_cost,
    )
