"""Real, runnable benchmark: the extraction step via Claude Haiku, with and
without Anthropic prompt caching on the shared instructions+policy-context
prefix from common_prompts.py.

Requires ANTHROPIC_API_KEY. This is the "measured" half of the Part 4
comparison - see benchmark/results/results.md for the vLLM side, which is
scaffolded but not measured (no GPU in the dev sandbox).

Usage:
    python -m benchmark.api_bench                 # default: 3 repeats/claim, all 26 claims
    python -m benchmark.api_bench --repeats 5 --limit 10
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from benchmark.common_prompts import EXTRACTION_JSON_SCHEMA, build_shared_prefix, load_claim_narratives

RESULTS_DIR = Path(__file__).parent / "results"

# Anthropic list pricing per 1M tokens (see SKILL model table). Cache write is
# ~1.25x base input for the default 5-minute TTL; cache read is ~0.1x.
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


@dataclass
class CallResult:
    latency_s: float
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass
class ConditionResult:
    label: str
    calls: list[CallResult] = field(default_factory=list)

    def summarize(self) -> dict:
        latencies = sorted(c.latency_s for c in self.calls)

        def pct(p: float) -> float:
            if not latencies:
                return 0.0
            idx = min(len(latencies) - 1, int(len(latencies) * p))
            return latencies[idx]

        total_input = sum(c.input_tokens for c in self.calls)
        total_output = sum(c.output_tokens for c in self.calls)
        total_cache_write = sum(c.cache_creation_input_tokens for c in self.calls)
        total_cache_read = sum(c.cache_read_input_tokens for c in self.calls)

        cost = (
            total_input * HAIKU_INPUT_PER_MTOK
            + total_output * HAIKU_OUTPUT_PER_MTOK
            + total_cache_write * HAIKU_INPUT_PER_MTOK * CACHE_WRITE_MULTIPLIER
            + total_cache_read * HAIKU_INPUT_PER_MTOK * CACHE_READ_MULTIPLIER
        ) / 1_000_000

        n = len(self.calls)
        cost_per_1000 = (cost / n * 1000) if n else 0.0

        return {
            "label": self.label,
            "n_calls": n,
            "p50_latency_s": round(pct(0.50), 3),
            "p99_latency_s": round(pct(0.99), 3),
            "mean_latency_s": round(statistics.mean(latencies), 3) if latencies else 0.0,
            "throughput_req_per_s": round(n / sum(c.latency_s for c in self.calls), 3) if self.calls else 0.0,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cache_creation_input_tokens": total_cache_write,
            "total_cache_read_input_tokens": total_cache_read,
            "cache_hit_rate": round(total_cache_read / total_input, 3) if total_input else 0.0,
            "measured_cost_usd": round(cost, 4),
            "cost_per_1000_docs_usd": round(cost_per_1000, 4),
        }


def _run_condition(
    client: anthropic.Anthropic,
    model: str,
    narratives: list[str],
    repeats: int,
    use_cache: bool,
    label: str,
) -> ConditionResult:
    shared_prefix = build_shared_prefix()
    result = ConditionResult(label=label)

    system_block: dict = {"type": "text", "text": shared_prefix}
    if use_cache:
        system_block["cache_control"] = {"type": "ephemeral"}

    for narrative in narratives:
        for _ in range(repeats):
            start = time.perf_counter()
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system=[system_block],
                messages=[{"role": "user", "content": narrative}],
                output_config={"format": {"type": "json_schema", "schema": EXTRACTION_JSON_SCHEMA}},
            )
            elapsed = time.perf_counter() - start
            usage = response.usage
            result.calls.append(
                CallResult(
                    latency_s=elapsed,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                )
            )
    return result


def run(model: str, repeats: int, limit: int | None) -> dict:
    client = anthropic.Anthropic()
    narratives = load_claim_narratives(limit=limit)
    print(f"Running {len(narratives)} claims x {repeats} repeats against {model} ...")

    print("\n[1/2] WITHOUT prompt caching (cold, every call pays full prefix cost) ...")
    no_cache = _run_condition(client, model, narratives, repeats, use_cache=False, label="no_cache")

    print("[2/2] WITH prompt caching (cache_control on the shared prefix) ...")
    with_cache = _run_condition(client, model, narratives, repeats, use_cache=True, label="with_cache")

    summary = {
        "model": model,
        "n_claims": len(narratives),
        "repeats_per_claim": repeats,
        "no_cache": no_cache.summarize(),
        "with_cache": with_cache.summarize(),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "api_bench_results.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\nWrote results to {out_path}")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per claim narrative")
    parser.add_argument("--limit", type=int, default=None, help="Only use the first N claims")
    args = parser.parse_args()
    run(model=args.model, repeats=args.repeats, limit=args.limit)
