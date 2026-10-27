"""Homework 9 Part A: cost per model call site.

Builds profile/results/costs.csv from saved artifacts only (no model calls):

- customer_conversation, server/app.py: the Homework 3 Langfuse export
  (traces/support_traces.json). Token counts are the ones the LLM API returned.
- judge, analysis/helpers/scale.py: the Homework 5 unnecessary_escalation judge
  runs. Calls are the cached predictions the model actually answered (code-gated
  traces are skipped). Tokens were not saved, so they are estimated here.
- judge, monitoring/run.py: the Homework 7 monitoring runs in
  monitoring/history.jsonl, whose token counts were already estimates.

Run from the repository root:

    uv run python profile/scripts/costs.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis.helpers.normalization import normalize_trace  # noqa: E402

OUT = ROOT / "profile" / "results" / "costs.csv"

# USD per million tokens. gpt-5.5 prices come from third-party trackers
# (unconfirmed, as in Homework 8); gpt-4o-mini is OpenAI's list price and
# reproduces the cost Homework 7 saved for its judge runs.
PRICES = {
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

GATE_PREFIX = "Code gate"
# The text analysis/helpers/scale.py wraps around every judged trace.
JUDGE_SUFFIX = (
    "First write a critique of the trace against the criterion. "
    "Use specific evidence from the provided trace. Then return result "
    "as exactly Pass when the named failure is absent, or Fail when present."
)
# JSON keys, quotes and the Pass/Fail word around each saved critique.
OUTPUT_OVERHEAD_TOKENS = 12


def cost(model: str, input_tokens: int, output_tokens: int, cached: int = 0) -> float:
    price = PRICES[model]
    total = (
        (input_tokens - cached) * price["input"]
        + cached * price.get("cached_input", price["input"])
        + output_tokens * price["output"]
    )
    return total / 1_000_000


def conversation_row() -> dict:
    export = json.loads((ROOT / "traces" / "support_traces.json").read_text())
    calls = failed = input_tokens = cached = output_tokens = 0
    for trace in export["traces"]:
        for obs in trace["observations"]:
            if obs["type"] != "GENERATION":
                continue
            usage = obs.get("usageDetails") or {}
            if not usage:
                failed += 1
                continue
            calls += 1
            # Langfuse splits OpenAI's input into uncached "input" and
            # "input_cached_tokens"; their sum is what the API reported.
            cached += usage.get("input_cached_tokens", 0)
            input_tokens += usage.get("input", 0) + usage.get("input_cached_tokens", 0)
            output_tokens += usage.get("output", 0)
    return {
        "cost_category": "customer_conversation",
        "call_site": "server/app.py:223",
        "purpose": (
            f"Cartwheel agent answering users (Homework 3 export, {len(export['traces'])} turns). "
            f"API token counts; input includes {cached} cached tokens "
            f"({cached / input_tokens:.1%}) billed at the cached price; "
            f"{failed} calls failed with no credits and carry no tokens"
        ),
        "model": "gpt-5.5",
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost("gpt-5.5", input_tokens, output_tokens, cached), 6),
    }


def hw5_judge_row() -> dict:
    texts = {}
    for name in ("hw5_trace_inputs.json", "hw5_heldout_inputs.json"):
        for record in json.loads((ROOT / "analysis" / "state" / name).read_text()):
            trace = normalize_trace(record)
            texts[trace["trace_id"]] = trace["text"]

    encoding = tiktoken.get_encoding("o200k_base")
    calls = input_tokens = output_tokens = 0
    versions = []
    for version in range(3):
        judge = json.loads(
            (ROOT / "analysis" / "state" / "judges" / f"unnecessary_escalation-v{version}.json").read_text()
        )
        critiques = judge["critiques"][judge["prompt_hash"]]
        judged = {tid: text for tid, text in critiques.items() if not text.startswith(GATE_PREFIX)}
        missing = sorted(set(judged) - set(texts))
        if missing:
            raise SystemExit(f"v{version}: no saved judge input for {len(missing)} traces, e.g. {missing[0]}")
        for trace_id, critique in judged.items():
            prompt = f"{judge['prompt_text']}\n\n--- Trace to evaluate ---\n{texts[trace_id]}\n\n{JUDGE_SUFFIX}"
            input_tokens += len(encoding.encode(prompt))
            output_tokens += len(encoding.encode(critique)) + OUTPUT_OVERHEAD_TOKENS
        calls += len(judged)
        versions.append(f"v{version} {len(judged)}")
    return {
        "cost_category": "judge",
        "call_site": "analysis/helpers/scale.py:234",
        "purpose": (
            "Homework 5 unnecessary_escalation judge development, test and held-out runs "
            f"({', '.join(versions)} model calls; code-gated traces excluded). "
            "ESTIMATED tokens: input = rebuilt prompt counted with o200k_base, "
            "missing DocETL's own wrapper text, so low; output = saved critique "
            f"+ {OUTPUT_OVERHEAD_TOKENS} tokens"
        ),
        "model": "gpt-4o-mini",
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost("gpt-4o-mini", input_tokens, output_tokens), 6),
    }


def hw7_judge_row() -> dict:
    runs = [json.loads(line) for line in (ROOT / "monitoring" / "history.jsonl").read_text().splitlines() if line.strip()]
    calls = sum(run["judge_usage"]["provider_calls"] for run in runs)
    input_tokens = sum(run["judge_usage"]["input_tokens"] for run in runs)
    output_tokens = sum(run["judge_usage"]["output_tokens"] for run in runs)
    return {
        "cost_category": "judge",
        "call_site": "monitoring/run.py:172",
        "purpose": (
            "Homework 7 monitoring with unnecessary_escalation-v2 "
            f"({', '.join(run['period'] for run in runs)} periods). "
            "ESTIMATED tokens copied from monitoring/history.jsonl: input counted "
            "with o200k_base, output assumed 250 per call"
        ),
        "model": "gpt-4o-mini",
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost("gpt-4o-mini", input_tokens, output_tokens), 6),
    }


def main() -> None:
    rows = [conversation_row(), hw5_judge_row(), hw7_judge_row()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(f"{row['cost_category']:22} {row['call_site']:32} {row['calls']:5} calls "
              f"{row['input_tokens']:>10,} in {row['output_tokens']:>8,} out ${row['cost_usd']:.4f}")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
