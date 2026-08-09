"""Prints a combined comparison table from whatever result files exist in
benchmark/results/. Run api_bench.py (and, if you have GPU access,
vllm_bench.py) first - this script only reads and formats their output, it
doesn't run anything itself.
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

ROW = "{:<28} {:>10} {:>10} {:>12} {:>16} {:>10}"


def _print_row(label: str, p50, p99, throughput, cost_per_1000, source: str) -> None:
    print(
        ROW.format(
            label,
            f"{p50:.3f}s" if p50 is not None else "-",
            f"{p99:.3f}s" if p99 is not None else "-",
            f"{throughput:.2f}/s" if throughput is not None else "-",
            f"${cost_per_1000:.2f}" if cost_per_1000 is not None else "-",
            source,
        )
    )


def main() -> None:
    print(ROW.format("condition", "p50", "p99", "throughput", "$/1000 docs", "basis"))
    print("-" * 90)

    api_path = RESULTS_DIR / "api_bench_results.json"
    if api_path.exists():
        data = json.loads(api_path.read_text())
        for key in ("no_cache", "with_cache"):
            r = data[key]
            _print_row(
                f"claude-haiku ({key})",
                r["p50_latency_s"],
                r["p99_latency_s"],
                r["throughput_req_per_s"],
                r["cost_per_1000_docs_usd"],
                "MEASURED",
            )
    else:
        print("(no api_bench_results.json yet - run `python -m benchmark.api_bench`)")

    for vllm_path in sorted(RESULTS_DIR.glob("vllm_bench_*.json")):
        data = json.loads(vllm_path.read_text())
        _print_row(
            f"vllm ({data.get('label', vllm_path.stem)})",
            data["p50_latency_s"],
            data["p99_latency_s"],
            data["throughput_req_per_s"],
            data["cost_per_1000_docs_usd"],
            "ESTIMATED" if "ESTIMATED" in data.get("cost_basis", "") else "measured-latency",
        )

    if not any(RESULTS_DIR.glob("vllm_bench_*.json")):
        print("(no vllm_bench_*.json yet - needs a live vLLM endpoint, see benchmark/vllm_bench.py)")


if __name__ == "__main__":
    main()
