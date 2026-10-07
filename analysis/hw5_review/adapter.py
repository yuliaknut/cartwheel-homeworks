"""HW5 judge review: one judge version's dev verdicts -> trace-review samples.

Reads only saved artifacts: the judge file (predictions and critiques under
its current prompt hash), the HW5 labels (Pass = 1), the split, and the HW4
conversation store. Keeps the dev traces the model judged (the code gate's
Passes are left out), disagreements first and ringed in the tracker, then
the agreements for comparison. Test traces never enter: the source set is the dev split, and a judge
that is not frozen has no test predictions anyway.

    uv run python -m analysis.hw5_review.adapter                 # latest version
    uv run python -m analysis.hw5_review.adapter --judge unnecessary_escalation-v1
    uv run python -m analysis.hw5_review.adapter --judge unnecessary_escalation-v1 --split test   # frozen judges only
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STATE = HERE.parent / "state"
MODE = "unnecessary_escalation"
WORLD_DATE = "2026-07-01"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_judge(mode: str) -> str:
    return _read(STATE / "judges" / f"_history_{mode}.json")["versions"][-1]["judge_id"]


GATE_PREFIX = "Code gate:"
HELDOUT_BATCH = "b8-escalation-heldout"


def convert(record: dict[str, Any], judge: dict[str, Any], pred: int, human: int, critique: str, split: str = "dev") -> dict[str, Any]:
    md = record.get("metadata") or {}
    sid = (record.get("meta") or {}).get("scenario_id") or record["trace_id"]
    word = {1: "Pass", 0: "Fail"}
    messages: list[dict[str, Any]] = [{
        "role": "observation", "label": "session",
        "text": f"{md.get('cartwheel.user_role')} · user {md.get('cartwheel.user_id')} · world date {WORLD_DATE}",
    }]
    for m in record["trace"]:
        role = m.get("role")
        if role == "tool_call":
            messages.append({"role": "tool_call", "name": m.get("name"), "arguments": m.get("arguments")})
        elif role == "tool_result":
            messages.append({"role": "tool_result", "name": m.get("name"), "content": m.get("content")})
        elif role in ("user", "assistant"):
            messages.append({"role": role, "text": m.get("text") or ""})
    tickets = [m for m in record["trace"] if m.get("role") == "tool_call" and m.get("name") == "escalate_to_human"]
    refunds = [m.get("content", {}).get("status") for m in record["trace"]
               if m.get("role") == "tool_result" and m.get("name") == "issue_refund" and isinstance(m.get("content"), dict)]
    t, e = record.get("scenario") or {}, record.get("expected") or {}
    src = e.get("source") or {}
    objective = e.get("evaluation") == "objective"
    scenario_card = {
        "title": "Scenario (HW3 plan)",
        "collapsible": True,
        "headline": (e.get("outcome") if objective else "human judgment") if e else "no scenario file entry",
        "body": (e.get("reason") if objective else e.get("criterion")) or "",
        "fields": {k: v for k, v in {
            "group": record.get("scenario_group"),
            "source": f"{src.get('type')} · {src.get('reference')}" if src else None,
            "intent": t.get("intent"),
            "record": " · ".join(str(x) for x in [t.get("record_state"), f"order {t['order_id']}" if t.get("order_id") else None,
                                                  f"product {t['product_id']}" if t.get("product_id") else None] if x),
            "policy": t.get("applicable_policy"),
            "difficulty": t.get("difficulty"),
            "style": t.get("user_style"),
            "turns": f"{t.get('turn_count')} · tools: {t.get('tools_needed')}" if t else None,
            "damaged record": record.get("data_quality_case_id"),
        }.items() if v},
    }
    return {
        "id": sid,
        "group": split,
        "dot_class": "ring" if pred != human else "",
        "chips": [md.get("cartwheel.user_role") or "?",
                  {"text": f"judge {word[pred]} · you {word[human]}" + ("" if pred != human else " · agree"),
                   "color": "orange" if pred != human else "green"}],
        "meta": [f"user {md.get('cartwheel.user_id')}", f"prompt {md.get('cartwheel.prompt_version')}", f"judge {judge['judge_id']} · {judge['model']}"],
        "link": record.get("permalink"),
        "link_label": "open in Langfuse ↗",
        "messages": messages,
        "context": [scenario_card, {
            "title": f"Judge v{judge['version']} · {judge['model']}",
            "headline": f"judge {word[pred]} · you {word[human]}" + (" · disagree" if pred != human else " · agree"),
            "body": critique or "(no critique saved)",
            "fields": {
                "your label": f"{word[human]} ({'failure absent' if human == 1 else 'unnecessary ticket present'})",
                "tickets opened": str(len(tickets)),
                "refund results": ", ".join(refunds) or "none",
                "source": f"judges/{judge['judge_id']}.json, hw5_labels",
            },
        }],
    }


def build(judge_id: str, mode: str = MODE, split: str = "dev") -> list[dict[str, Any]]:
    judge = _read(STATE / "judges" / f"{judge_id}.json")
    if split in ("test", "heldout") and judge.get("status") != "frozen":
        raise SystemExit(f"{judge_id} is not frozen; {split} verdicts stay hidden until it is")
    preds = judge["predictions"].get(judge["prompt_hash"], {})
    crits = (judge.get("critiques") or {}).get(judge["prompt_hash"], {})
    labels = {json.loads(l)["trace_id"]: json.loads(l)["label"]
              for l in (STATE / "hw5_labels" / f"{mode}.jsonl").read_text().splitlines() if l.strip()}
    if split == "heldout":  # labeled after HW5: read the label file (failure present = 1) and flip to Pass = 1
        live: dict[str, int] = {}
        for l in (STATE / "labels" / f"{mode}.jsonl").read_text().splitlines():
            if l.strip() and not json.loads(l).get("superseded_by"):
                live[json.loads(l)["trace_id"]] = 1 - int(json.loads(l)["label"])
        labels = {**labels, **live}
    store = {r["trace_id"]: r for r in _read(STATE / "traces.json")}
    ids = ([x["trace_id"] for x in _read(STATE / "samples.json") if x.get("batch") == HELDOUT_BATCH]
           if split == "heldout" else _read(STATE / "splits.json")[mode][split])
    out = [convert(store[t], judge, preds[t], labels[t], crits.get(t, ""), split)
           for t in ids if t in preds and not crits.get(t, "").startswith(GATE_PREFIX)]
    return sorted(out, key=lambda s: (s["dot_class"] != "ring", s["id"]))


def metrics_summary(current: str, mode: str = MODE, current_split: str = "dev") -> dict[str, Any]:
    """Version history from the saved dev reports (analysis/report/dev-<judge_id>.json)."""
    report_dir = HERE.parent / "report"
    fmt = lambda v, iv: f"{v:.2f} [{iv[0]:.2f}, {iv[1]:.2f}]" if v is not None else "n/a"
    rows, cur = [], None
    for version in _read(STATE / "judges" / f"_history_{mode}.json")["versions"]:
        path = report_dir / f"dev-{version['judge_id']}.json"
        if not path.exists():
            continue
        j = _read(path)["judge"]
        if version["judge_id"] == current and current_split == "dev":
            cur = len(rows)
        rows.append([version["judge_id"].rsplit("-", 1)[-1], str(j["n"]), str(j["tp"]), str(j["fn"]), str(j["tn"]), str(j["fp"]),
                     fmt(j["tpr"], j["tpr_interval"]), fmt(j["tnr"], j["tnr_interval"]), str(len(j["disagreements"]))])
    for version in _read(STATE / "judges" / f"_history_{mode}.json")["versions"]:
        path = report_dir / f"test-{version['judge_id']}.json"
        if path.exists():
            j = _read(path)["judge"]
            if version["judge_id"] == current and current_split == "test":
                cur = len(rows)
            rows.append([version["judge_id"].rsplit("-", 1)[-1] + " · TEST", str(j["n"]), str(j["tp"]), str(j["fn"]), str(j["tn"]), str(j["fp"]),
                         fmt(j["tpr"], j["tpr_interval"]), fmt(j["tnr"], j["tnr_interval"]), str(len(j["disagreements"]))])
    for version in _read(STATE / "judges" / f"_history_{mode}.json")["versions"]:
        path = report_dir / f"heldout-{version['judge_id']}.json"
        if path.exists():
            j = _read(path)["judge"]
            if version["judge_id"] == current and current_split == "heldout":
                cur = len(rows)
            rows.append([version["judge_id"].rsplit("-", 1)[-1] + " · HELD-OUT", str(j["n"]), str(j["tp"]), str(j["fn"]), str(j["tn"]), str(j["fp"]),
                         fmt(j["tpr"], j["tpr_interval"]), fmt(j["tnr"], j["tnr_interval"]), str(len(j["disagreements"]))])
    return {"title": "Metrics · judge only, escalated traces (Pass = positive) · dev rows, the frozen judge on test, then on the blind held-out set",
            "columns": ["version", "n", "TP", "FN", "TN", "FP", "TPR [95% CI]", "TNR [95% CI]", "disagree"],
            "rows": rows, "current_row": cur,
            "note": "FP = judge Pass on your Fail (missed unnecessary ticket); FN = judge Fail on your Pass. The 26 traces with no ticket are passed by the code gate and not counted."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge", default=None, help="judge id (default: the latest registered version)")
    ap.add_argument("--split", default="dev", choices=["dev", "test", "heldout"], help="test and heldout are allowed only for a frozen judge")
    args = ap.parse_args()
    jid = args.judge or latest_judge(MODE)
    samples = build(jid, split=args.split)
    (HERE / "samples.json").write_text(json.dumps(samples, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    cfg_path = HERE / "review.json"
    cfg = _read(cfg_path)
    cfg["summary"] = metrics_summary(jid, current_split=args.split)
    cfg["title"] = f"HW5 · unnecessary_escalation · judge review ({args.split})"
    cfg["store_key"] = f"{jid}:{args.split}"  # the page's browser backup is per judge version, so versions never bleed into each other
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(samples)} judged traces ({sum(1 for x in samples if x['dot_class'])} disagreements) for {jid} to {(HERE / 'samples.json').relative_to(HERE.parents[1])}")
