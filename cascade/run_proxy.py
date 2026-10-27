"""Homework 9 Part D: a proxy judge for a model cascade.

Oracle: the frozen Homework 5 judge unnecessary_escalation-v2 (gpt-4o-mini),
whose saved verdicts in analysis/state/judges/ are reused, never re-run.
Proxy: claude-haiku-5-5 with the same judge prompt plus one instruction to
state its confidence. Traces the oracle's code gate decided (no ticket, so
no model call) keep the gate's Pass and never reach the proxy; agreement and
cost are computed over the model-judged traces only.

Run from the repository root:

    uv run python cascade/run_proxy.py run --split dev     # paid: proxy calls
    uv run python cascade/run_proxy.py sweep               # free: thresholds.csv
    uv run python cascade/run_proxy.py run --split test    # paid, once
    uv run python cascade/run_proxy.py check --threshold T # free: check.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.helpers.normalization import normalize_trace  # noqa: E402

STATE = ROOT / "analysis" / "state"
RESULTS = ROOT / "cascade" / "results"
JUDGE_ID = "unnecessary_escalation"
ORACLE_FILE = STATE / "judges" / f"{JUDGE_ID}-v2.json"
PROXY_MODEL = "claude-haiku-5-5"
PROXY_LITELLM = "anthropic/claude-haiku-5-5"
GATE_PREFIX = "Code gate"
THRESHOLDS = [round(0.05 * step, 2) for step in range(10, 21)]  # 0.50 .. 1.00

# The text analysis/helpers/scale.py wraps around every judged trace.
JUDGE_SUFFIX = (
    "First write a critique of the trace against the criterion. "
    "Use specific evidence from the provided trace. Then return result "
    "as exactly Pass when the named failure is absent, or Fail when present."
)
# The one added instruction the handout asks for.
CONFIDENCE_LINE = (
    "Also give your confidence that your result is correct, as a number from 0 to 1."
)
# DocETL enforced the oracle's output schema; the direct call states it instead.
FORMAT_LINE = (
    'Answer with only a JSON object: {"critique": string, '
    '"result": "Pass" or "Fail", "confidence": number}.'
)


def load_json(path: Path):
    return json.loads(path.read_text())


def prices(model: str) -> dict:
    return load_json(ROOT / "optimize" / "config.json")["prices_per_million_tokens_usd"][model]


def oracle_cost_per_call() -> float:
    """Average cost of one oracle call, from the Part A estimate in costs.csv."""
    with (ROOT / "profile" / "results" / "costs.csv").open() as handle:
        row = next(r for r in csv.DictReader(handle) if r["call_site"].startswith("analysis/helpers/scale.py"))
    return float(row["cost_usd"]) / int(row["calls"])


def load_split(split: str) -> dict:
    """Ids, human labels, oracle verdicts and gate status for one HW5 split."""
    ids = load_json(STATE / "splits.json")[JUDGE_ID][split]
    labels = {}
    for line in (STATE / "hw5_labels" / f"{JUDGE_ID}.jsonl").read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            labels[record["trace_id"]] = record["label"]
    oracle = load_json(ORACLE_FILE)
    verdicts = oracle["predictions"][oracle["prompt_hash"]]
    critiques = oracle["critiques"][oracle["prompt_hash"]]
    judged = [tid for tid in ids if not critiques[tid].startswith(GATE_PREFIX)]
    return {"ids": ids, "judged": judged, "labels": labels, "oracle": verdicts,
            "prompt_text": oracle["prompt_text"], "prompt_hash": oracle["prompt_hash"]}


def trace_texts() -> dict[str, str]:
    texts = {}
    for name in ("hw5_trace_inputs.json", "hw5_heldout_inputs.json"):
        for record in load_json(STATE / name):
            trace = normalize_trace(record)
            texts[trace["trace_id"]] = trace["text"]
    return texts


def parse_answer(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in the proxy answer")
    answer = json.loads(match.group(0))
    if answer.get("result") not in ("Pass", "Fail"):
        raise ValueError(f"result must be Pass or Fail, got {answer.get('result')!r}")
    confidence = float(answer["confidence"])
    if not 0 <= confidence <= 1:
        raise ValueError(f"confidence out of range: {confidence}")
    return {"verdict": 1 if answer["result"] == "Pass" else 0,
            "confidence": confidence, "critique": answer.get("critique", "")}


def run(split: str) -> None:
    import litellm

    from observability.instrument import load_env

    load_env()
    out = RESULTS / f"proxy-{split}.json"
    saved = load_json(out) if out.exists() else {}
    if saved.get("complete"):
        raise SystemExit(f"{out.relative_to(ROOT)} is complete; the proxy runs once per split")
    data = load_split(split)
    texts = trace_texts()
    price = prices(PROXY_MODEL)
    rows = saved.get("rows", {})  # resume: a saved trace is never called again

    def save(complete: bool) -> None:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "split": split, "proxy_model": PROXY_MODEL, "oracle": ORACLE_FILE.name,
            "oracle_prompt_hash": data["prompt_hash"], "judged_traces": len(data["judged"]),
            "gated_traces": len(data["ids"]) - len(data["judged"]), "complete": complete,
            "cost_usd": round(sum(r["cost_usd"] for r in rows.values()), 6),
            "notes": saved.get("notes", []), "rows": rows,
        }, indent=1))

    for number, tid in enumerate(data["judged"], 1):
        if tid in rows:
            continue
        prompt = (f"{data['prompt_text']}\n\n--- Trace to evaluate ---\n{texts[tid]}\n\n"
                  f"{JUDGE_SUFFIX} {CONFIDENCE_LINE}\n\n{FORMAT_LINE}")
        for attempt in (1, 2, 3):
            response = litellm.completion(model=PROXY_LITELLM, max_tokens=2048,
                                          messages=[{"role": "user", "content": prompt}])
            usage = response.usage
            try:
                if response.choices[0].finish_reason == "length":
                    raise ValueError("answer cut off at max_tokens")
                answer = parse_answer(response.choices[0].message.content)
                break
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                if attempt == 3:
                    raise SystemExit(f"{tid}: unusable proxy answer ({exc})")
        cost = (usage.prompt_tokens * price["input"] + usage.completion_tokens * price["output"]) / 1e6
        rows[tid] = {**answer, "input_tokens": usage.prompt_tokens,
                     "output_tokens": usage.completion_tokens, "cost_usd": round(cost, 6),
                     "attempts": attempt}
        print(f"{number:2}/{len(data['judged'])} {tid[:12]} "
              f"{'Pass' if answer['verdict'] else 'Fail'} {answer['confidence']:.2f} "
              f"oracle {'Pass' if data['oracle'][tid] else 'Fail'} ${cost:.5f}")
        save(complete=False)
    save(complete=True)
    print(f"wrote {out.relative_to(ROOT)}; proxy cost ${sum(r['cost_usd'] for r in rows.values()):.4f}")


def cascade_at(threshold: float, split: str) -> dict:
    data = load_split(split)
    saved = load_json(RESULTS / f"proxy-{split}.json")
    if not saved.get("complete"):
        raise SystemExit(f"proxy-{split}.json is incomplete; finish the proxy run first")
    proxy = saved["rows"]
    per_oracle = oracle_cost_per_call()
    judged = data["judged"]
    kept = [tid for tid in judged if proxy[tid]["confidence"] >= threshold]
    final = {tid: proxy[tid]["verdict"] if tid in kept else data["oracle"][tid] for tid in judged}
    with_oracle = sum(final[tid] == data["oracle"][tid] for tid in judged)
    with_labels = sum(final[tid] == data["labels"][tid] for tid in judged)
    cost = sum(proxy[tid]["cost_usd"] for tid in judged) + per_oracle * (len(judged) - len(kept))
    return {
        "threshold": threshold,
        "judged_traces": len(judged),
        "disagreements_with_oracle": len(judged) - with_oracle,
        "agreement_with_oracle": round(with_oracle / len(judged), 4),
        "label_matches": with_labels,
        "agreement_with_human_labels": round(with_labels / len(judged), 4),
        "oracle_label_matches": sum(data["oracle"][tid] == data["labels"][tid] for tid in judged),
        "proxy_share": round(len(kept) / len(judged), 4),
        "cost_per_1000_verdicts_usd": round(cost / len(judged) * 1000, 4),
    }


def sweep() -> None:
    columns = ["threshold", "agreement_with_oracle", "agreement_with_human_labels",
               "proxy_share", "cost_per_1000_verdicts_usd"]
    results = [cascade_at(threshold, "dev") for threshold in THRESHOLDS]
    with (RESULTS / "thresholds.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"oracle alone: ${oracle_cost_per_call() * 1000:.4f} per 1000 verdicts, "
          f"label matches {results[0]['oracle_label_matches']}/{results[0]['judged_traces']}")
    for r in results:
        print(f"t={r['threshold']:.2f} oracle {r['agreement_with_oracle']:.3f} "
              f"({r['disagreements_with_oracle']} off) labels {r['agreement_with_human_labels']:.3f} "
              f"({r['label_matches']}) proxy_share {r['proxy_share']:.2f} "
              f"${r['cost_per_1000_verdicts_usd']:.4f}/1000")
    print(f"wrote {(RESULTS / 'thresholds.csv').relative_to(ROOT)}")


def check(threshold: float) -> None:
    out = RESULTS / "check.json"
    if out.exists():
        raise SystemExit("check.json exists; the threshold is checked once")
    result = cascade_at(threshold, "test")
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--split", choices=("dev", "test"), required=True)
    commands.add_parser("sweep")
    check_parser = commands.add_parser("check")
    check_parser.add_argument("--threshold", type=float, required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args.split)
    elif args.command == "sweep":
        sweep()
    else:
        check(args.threshold)


if __name__ == "__main__":
    main()
