"""Homework 9 Part E: score/cost frontier over the HW8 final run and the HW9 runs.

Reads saved development results only (no model calls). Part B's diagnostic
reruns lived in a scratch directory and are left out by the student's choice.

    uv run python profile/scripts/frontier.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "optimize" / "results"
OUT = ROOT / "profile" / "results" / "frontier.csv"
RUNS = [
    "development-final-claude-haiku-5-5-20261020-001937.json",         # HW8 final, cefec04
    "development-fewer-tokens-claude-haiku-5-5-20261021-155320.json",  # Part B, reverted
    "development-cache-before-gpt-6.1-sol-20261026-130224.json",       # Part C
    "development-cache-after-gpt-6.1-sol-20261026-133807.json",        # Part C, reverted
]
COLUMNS = ["candidate", "model", "development_score", "write_pass_5",
           "cost_per_100_conversations_usd", "median_latency_seconds", "frontier_status"]


def dominates(a: dict, b: dict) -> bool:
    score_a, score_b = a["development_score"], b["development_score"]
    cost_a, cost_b = a["cost_per_100_conversations_usd"], b["cost_per_100_conversations_usd"]
    return score_a >= score_b and cost_a <= cost_b and (score_a > score_b or cost_a < cost_b)


def main() -> None:
    rows = []
    for name in RUNS:
        result = json.loads((RESULTS / name).read_text())
        rows.append({
            "candidate": result["candidate"],
            "model": result["model"],
            "development_score": result["score"],
            "write_pass_5": "" if result["write_pass_5"] is None else result["write_pass_5"],
            "cost_per_100_conversations_usd": result["cost_per_100_conversations_usd"],
            "median_latency_seconds": result["median_latency_seconds"],
        })
    for row in rows:
        beaten = any(dominates(other, row) for other in rows if other is not row)
        row["frontier_status"] = "dominated" if beaten else "frontier"
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(OUT.read_text(), end="")


if __name__ == "__main__":
    main()
