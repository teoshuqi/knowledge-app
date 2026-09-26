"""F-06 gate — CPU llama-server throughput vs. the per-item SLA
(tech design §2.4 consideration, §6 target SLAs).

Local (llama.cpp) inference is meaningfully slower than an API call on CPU.
Before the hourly enrichment fast path (§3.2) is allowed to default to a
local llama-server instead of the Anthropic API, confirm it actually clears
the <5s per-item SLA on real hardware. This checks throughput only —
grammar-constrained decoding already guarantees valid *shape*; extraction
*quality* is judged separately (§2.4), not by this script.

Requires a running llama-server (see docker-compose.yml's optional
llama-server service, added in H-03) and LLAMA_SERVER_URL set.

Run: python scripts/benchmark_llama_server.py
"""

import statistics
import sys
import time

import httpx

from src.config import get_settings

# Representative of the enrichment prompt's length (§2.4: text truncated to
# ~4000 chars) — throughput, not content quality, is what this gate checks.
SAMPLE_PROMPT = (
    "Extract a summary, key entities, and topic tags from this content.\n\n"
    "TITLE: vLLM adds native support for speculative decoding\n"
    "TEXT: "
    + (
        "Speculative decoding reduces inference latency by drafting "
        "multiple tokens with a small model and verifying them in a "
        "single pass with the larger target model. " * 40
    )
)
N_RUNS = 10
PER_ITEM_SLA_SECONDS = 5.0


def main() -> None:
    settings = get_settings()
    if not settings.llama_server_url:
        sys.exit("LLAMA_SERVER_URL is not set — nothing to benchmark.")

    url = f"{settings.llama_server_url}/v1/chat/completions"
    latencies = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(N_RUNS):
            start = time.perf_counter()
            response = client.post(
                url,
                json={
                    "model": "local",
                    "messages": [{"role": "user", "content": SAMPLE_PROMPT}],
                    "max_tokens": 300,
                },
            )
            response.raise_for_status()
            latencies.append(time.perf_counter() - start)
            print(f"run {i + 1}/{N_RUNS}: {latencies[-1]:.2f}s")

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[max(0, int(N_RUNS * 0.95) - 1)]
    print(f"\np50={p50:.2f}s  p95={p95:.2f}s  (SLA: {PER_ITEM_SLA_SECONDS}s)")

    if p95 > PER_ITEM_SLA_SECONDS:
        print(
            "VERDICT: local llama-server misses the per-item SLA on this "
            "hardware — route the hourly fast path through the Anthropic "
            "API instead (set LLM_MODEL to an Anthropic model name)."
        )
    else:
        print(
            "VERDICT: local llama-server clears the per-item SLA — safe "
            "to default LLM_MODEL to it."
        )


if __name__ == "__main__":
    main()
