"""Build the HW7 review page: every conversation the monitor flagged.

    uv run python -m analysis.hw7_review.build_samples
    uv run python analysis/hw5_review/server.py --port 8022 \
        --samples analysis/hw7_review/samples.json \
        --annotations analysis/hw7_review/annotations.json \
        --config analysis/hw7_review/review.json

Reads the saved verdicts in monitoring/output/<period>/verdicts.json and the
conversations from Langfuse (read only). Shows the HW5 human label where one
exists for a "before" conversation. Makes no model calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from monitoring import run as monitor

HERE = Path(__file__).resolve().parent
LABELS = monitor.REPO_ROOT / "analysis" / "state" / "hw5_labels" / "unnecessary_escalation.jsonl"


def scenario_context(scenario: dict | None) -> dict:
    """The HW4 viewer's "Scenario context" card: the scenario's expected result and plan, always open."""
    if scenario is None:
        return {"title": "Scenario context · no scenario file entry"}
    e, t = scenario.get("expected") or {}, scenario.get("tuple") or {}
    src = e.get("source") or {}
    objective = e.get("evaluation") == "objective"
    summary = f"objective · {e.get('outcome')} · {src.get('type')}" if objective else f"human judgment · {src.get('type')} {src.get('reference') or ''}"
    record = str(t.get("record_state")) + (f" · order {t['order_id']}" if t.get("order_id") else "") + (f" · product {t['product_id']}" if t.get("product_id") else "")
    return {
        "title": f"Scenario context · {summary.strip()}",
        "headline": e.get("outcome") if objective else "human judgment",
        "body": (e.get("reason") if objective else e.get("criterion")) or "",
        "fields": {
            "source": f"{src.get('type')} {src.get('reference') or ''}".strip(),
            "group": scenario.get("scenario_group"),
            "intent": t.get("intent"),
            "record": record,
            "policy": t.get("applicable_policy"),
            "difficulty": t.get("difficulty"),
            "style": t.get("user_style"),
            "turns": f"{t.get('turn_count')} · tools: {t.get('tools_needed')}",
        },
    }


def main() -> None:
    from observability.instrument import load_env

    load_env()
    config = monitor.load_config()
    scenarios = {row["id"]: row for row in map(json.loads, filter(str.strip, monitor.SCENARIOS_PATH.read_text().splitlines()))}
    scenario_ids = set(scenarios)
    human = {}
    for line in LABELS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            human[row["trace_id"]] = "Pass" if row["label"] == 1 else "Fail"

    samples = []
    for period in config["periods"]:
        label = period["label"]
        saved = json.loads((monitor.OUTPUT_DIR / label / "verdicts.json").read_text())
        traces = monitor.fetch_window(monitor._parse_time(period["from"]), monitor._parse_time(period["to"]), scenario_ids)
        records, _ = monitor.build_conversations(traces, config["model"], scenario_ids)
        groups = {g: set(ids) for g, ids in saved["risk_membership"].items()}
        for record in records:
            tid = record["id"]
            random_flag = saved["random_verdicts"].get(tid) == 1
            risk_flag = saved["risk_verdicts"].get(tid) == 1
            if not (random_flag or risk_flag):
                continue
            scores = [s for s, on in (("random sample", random_flag), ("risk group", risk_flag)) if on]
            chips = [label, {"text": "judge Fail · " + " + ".join(scores), "color": "red"}]
            chips += [g for g, ids in groups.items() if tid in ids]
            first = record["trace_ids"][0]
            if label == "before" and first in human:
                chips.append({"text": f"your HW5 label {human[first]}", "color": "green" if human[first] == "Pass" else "red"})
            md = record["metadata"]
            messages = [{"role": "observation", "label": "session",
                         "text": f"{md.get('cartwheel.user_role')} · user {md.get('cartwheel.user_id')} · world date 2026-07-01"}]
            for m in record["trace"]:
                if m.get("role") in ("user", "assistant") and m.get("text"):
                    messages.append({"role": m["role"], "text": m["text"]})
                elif m.get("role") == "tool_call":
                    messages.append({"role": "tool_call", "name": m.get("name"), "arguments": m.get("arguments")})
                elif m.get("role") == "tool_result":
                    messages.append({"role": "tool_result", "name": m.get("name"), "content": m.get("content")})
            samples.append({
                "id": f"{record['conversation']}__{label}",
                "group": f"{label}: flagged",
                "dot_class": "",
                "chips": chips,
                "meta": [f"{record['conversation']} · {label} period", f"prompt {record['meta'].get('prompt_version')}",
                         f"judge {config['judge_id']} · gpt-4o-mini", f"final trace {tid}"],
                "messages": messages,
                "context": scenario_context(scenarios.get(record["conversation"])),
            })
    samples.sort(key=lambda s: (not any(isinstance(c, dict) and "random sample" in c["text"] for c in s["chips"]), s["id"]))
    (HERE / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(samples)} flagged conversations -> {HERE / 'samples.json'}")


if __name__ == "__main__":
    main()
