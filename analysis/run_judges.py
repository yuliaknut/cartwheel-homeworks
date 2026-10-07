"""Homework 5: one LLM judge for ``unnecessary_escalation``.

Parts B to D of ``homework/module-2/hw5.md``, run from the repository root:

    uv run python -m analysis.run_judges export     # HW4 labels -> hw5_labels/<mode>.jsonl (Pass = 1)
    uv run python -m analysis.run_judges inputs     # judge inputs -> state/hw5_trace_inputs.json
    uv run python -m analysis.run_judges split      # 20/40/40 split, once, printed with class counts
    uv run python -m analysis.run_judges dev analysis/prompts/unnecessary_escalation-v0.txt   # paid: gpt-4o-mini on dev
    uv run python -m analysis.run_judges freeze unnecessary_escalation-v1   # once, for the chosen version
    uv run python -m analysis.run_judges test unnecessary_escalation-v1     # paid: the frozen judge on test, once
    uv run python -m analysis.run_judges heldout unnecessary_escalation-v2  # paid: the frozen judge on the blind held-out batch

``export_labels`` and ``prepare_inputs`` both read the eligible set: every
labeled conversation minus the close variants listed in
``state/hw5_exclusions.json``. The HW4 label files stay untouched.

The judge input is the whole conversation (the student's choice): user
messages, the agent's narration, every tool call and result, and the final
reply, preceded by the session context the agent itself was given plus the
world date. Nothing from review goes in: no labels, notes, scenario plans,
answer keys, or batch reasons.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / "analysis" / "state"
MODE = "unnecessary_escalation"
INPUTS_PATH = STATE_DIR / "hw5_trace_inputs.json"
EXCLUSIONS_PATH = STATE_DIR / "hw5_exclusions.json"
# The seeded world's "today" (meta.world_asof in data/cartwheel.db). Every
# conversation ran against it, and the human labels assumed it.
WORLD_DATE = "2026-07-01"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _live_labels(mode: str) -> dict[str, dict[str, Any]]:
    """The current HW4-convention label per trace (1 = failure present)."""
    live: dict[str, dict[str, Any]] = {}
    for line in (STATE_DIR / "labels" / f"{mode}.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("superseded_by"):
            continue
        live[row["trace_id"]] = row
    return live


def _excluded() -> set[str]:
    return set(_read_json(EXCLUSIONS_PATH)["excluded_trace_ids"]) if EXCLUSIONS_PATH.exists() else set()


def eligible_trace_ids(mode: str = MODE) -> list[str]:
    """Labeled conversations for ``mode`` minus the excluded close variants."""
    excluded = _excluded()
    return sorted(tid for tid in _live_labels(mode) if tid not in excluded)


def export_labels(mode: str = MODE) -> Path:
    """Write ``hw5_labels/<mode>.jsonl``: ``trace_id`` and ``label`` only, Pass = 1.

    HW4 stores failure-present = 1, so the value is flipped. Binary by the
    student's choice: no source or authorship column.
    """
    live = _live_labels(mode)
    out = STATE_DIR / "hw5_labels" / f"{mode}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"trace_id": tid, "label": 1 - int(live[tid]["label"])} for tid in eligible_trace_ids(mode)]
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return out


def _as_json(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _judge_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """One message as the judge reads it.

    The shared renderer (``normalization._flatten``) prints a tool call as
    ``tool_call: <arguments>`` and a result as ``tool_result: <content>``,
    dropping the tool name, so the name is written into the text here:
    without it the judge cannot tell ``escalate_to_human`` from ``issue_refund``.
    """
    role = message.get("role")
    name = message.get("name")
    if role == "tool_call":
        return {"role": "tool_call", "name": name, "arguments": f"{name}({_as_json(message.get('arguments'))})"}
    if role == "tool_result":
        return {"role": "tool_result", "name": name, "content": f"{name} -> {_as_json(message.get('content'))}"}
    if role in ("user", "assistant") and message.get("text"):
        return {"role": role, "text": message["text"]}
    return None


def _session_context(record: dict[str, Any]) -> dict[str, str]:
    md = record.get("metadata") or {}
    role = md.get("cartwheel.user_role") or (record.get("meta") or {}).get("role")
    parts = [f"User role: {role}", f"User id: {md.get('cartwheel.user_id')}"]
    if md.get("cartwheel.store_id"):
        parts.append(f"Store id: {md['cartwheel.store_id']}")
    parts.append(f"World date of the conversation: {WORLD_DATE}")
    return {"role": "session_context", "text": "; ".join(parts)}


def prepare_inputs(mode: str = MODE) -> Path:
    """Save one judge input per eligible conversation to ``hw5_trace_inputs.json``.

    Reads the HW4 store (``state/traces.json``). Each record is
    ``{"trace_id", "trace": [messages]}``; the file is frozen after the first
    prompt run so every version is scored on identical inputs.
    """
    store = {r["trace_id"]: r for r in _read_json(STATE_DIR / "traces.json")}
    ids = eligible_trace_ids(mode)
    missing = [tid for tid in ids if tid not in store]
    if missing:
        raise ValueError(f"{len(missing)} eligible labels have no conversation in traces.json: {missing[:3]}")
    records = []
    for tid in ids:
        messages = [m for m in (_judge_message(m) for m in store[tid]["trace"]) if m]
        records.append({"trace_id": tid, "trace": [_session_context(store[tid]), *messages]})
    INPUTS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return INPUTS_PATH


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """Split the HW5 labels 20/40/40 with the course helper. Run once."""
    from analysis.helpers import split_labels

    records = _read_json(INPUTS_PATH)
    return split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=10,
        eligible_trace_ids=[record["trace_id"] for record in records],
    )


def _split_report(mode: str, splits: dict[str, list[str]]) -> None:
    """Class counts per split, plus how many Passes sit on the escalation boundary."""
    labels = {json.loads(l)["trace_id"]: json.loads(l)["label"]
              for l in (STATE_DIR / "hw5_labels" / f"{mode}.jsonl").read_text().splitlines() if l.strip()}
    store = {r["trace_id"]: r for r in _read_json(STATE_DIR / "traces.json")}
    escalated = {tid for tid, r in store.items()
                 if any(m.get("role") == "tool_call" and m.get("name") == "escalate_to_human" for m in r["trace"])}
    print(f"{'split':6} {'Pass':>5} {'Fail':>5}   Pass escalated / not")
    for name in ("train", "dev", "test"):
        ids = splits[name]
        c = Counter(labels[t] for t in ids)
        hard = sum(1 for t in ids if labels[t] == 1 and t in escalated)
        print(f"{name:6} {c[1]:5} {c[0]:5}   {hard:>4} / {c[1] - hard}")


JUDGE_MODEL = "gpt-4o-mini"
REPORT_DIR = REPO_ROOT / "analysis" / "report"


def _use_saved_inputs() -> None:
    """Point the helpers at the frozen inputs and load OPENAI_API_KEY from .env."""
    import os

    from observability.instrument import load_env

    load_env()
    os.environ.setdefault("CARTWHEEL_JUDGE_TRACE_SOURCE", str(INPUTS_PATH))


def _judge_for_prompt(mode: str, prompt_text: str) -> str:
    """The judge id already registered for this exact prompt, else a new registration.

    Resuming an interrupted run must not register the same prompt twice.
    """
    from analysis.helpers import register_judge
    from analysis.helpers.tools import _prompt_hash

    history = STATE_DIR / "judges" / f"_history_{mode}.json"
    wanted = _prompt_hash(prompt_text, JUDGE_MODEL)
    if history.exists():
        for version in _read_json(history)["versions"]:
            if version["prompt_hash"] == wanted:
                return version["judge_id"]
    return register_judge(mode=mode, prompt_text=prompt_text, judge_model=JUDGE_MODEL)["judge_id"]


GATE_CRITIQUE = "Code gate: no escalate_to_human call in the conversation, so no ticket to judge. Pass by definition; the model was not called."


def _escalated_ids(ids: list[str]) -> set[str]:
    """Traces whose judge input contains an escalate_to_human call."""
    inputs = {r["trace_id"]: r for r in _read_json(INPUTS_PATH)}
    return {t for t in ids if any(m.get("role") == "tool_call" and m.get("name") == "escalate_to_human"
                                  for m in inputs[t]["trace"])}


class _GateVerdicts(dict):
    """Gate predictions in the shape run_judge expects from a classifier (Pass = 1)."""

    def __init__(self, ids: list[str]) -> None:
        super().__init__({t: 1 for t in ids})
        self.critiques = {t: GATE_CRITIQUE for t in ids}


def _run_gated(judge_id: str, split: str, mode: str) -> tuple[list[str], list[str]]:
    """Code gate first, then the model on the escalated traces only.

    Traces with no escalate_to_human call are Pass by definition, so the gate
    writes Pass into the judge's prediction cache (through run_judge's own
    ``classify`` hook, with a critique saying the gate decided) and the model
    is called only where a ticket was opened.
    """
    from analysis.helpers import run_judge

    ids = _read_json(STATE_DIR / "splits.json")[mode][split]
    escalated = sorted(_escalated_ids(ids))
    gated = sorted(set(ids) - set(escalated))
    if gated:
        run_judge(judge_id, trace_ids=gated, classify=lambda _prompt, batch: _GateVerdicts(batch))
    if escalated:
        run_judge(judge_id, trace_ids=escalated, batch_size=10)
    return escalated, gated


def _confusion(judge_id: str, ids: list[str], mode: str) -> dict[str, Any]:
    """TPR/TNR with Wilson intervals over ``ids``, from the saved predictions (Pass = 1 = positive)."""
    from analysis.helpers.tools import _wilson_interval

    judge = _read_json(STATE_DIR / "judges" / f"{judge_id}.json")
    preds = judge["predictions"][judge["prompt_hash"]]
    labels = {json.loads(l)["trace_id"]: json.loads(l)["label"]
              for l in (STATE_DIR / "hw5_labels" / f"{mode}.jsonl").read_text().splitlines() if l.strip()}
    tp = sum(1 for t in ids if labels[t] == 1 and preds[t] == 1)
    fn = sum(1 for t in ids if labels[t] == 1 and preds[t] == 0)
    tn = sum(1 for t in ids if labels[t] == 0 and preds[t] == 0)
    fp = sum(1 for t in ids if labels[t] == 0 and preds[t] == 1)
    return {"n": len(ids), "tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "tpr": tp / (tp + fn) if tp + fn else None, "tpr_interval": _wilson_interval(tp, tp + fn),
            "tnr": tn / (tn + fp) if tn + fp else None, "tnr_interval": _wilson_interval(tn, tn + fp),
            "disagreements": sorted(t for t in ids if labels[t] != preds[t])}


def run_development(mode: str, prompt_path: str | Path) -> dict[str, Any]:
    """Register the prompt (once), gate + judge the dev split, save the metrics.

    ``judge`` (the headline) scores the model on the traces it actually judged,
    the escalated ones; the gate's free Passes would inflate TPR. ``system``
    is the course helper's judge_alignment over the whole split, gate included.
    """
    from analysis.helpers import judge_alignment

    _use_saved_inputs()
    judge_id = _judge_for_prompt(mode, Path(prompt_path).read_text(encoding="utf-8"))
    escalated, gated = _run_gated(judge_id, "dev", mode)
    metrics = {"judge_id": judge_id, "prompt_path": str(Path(prompt_path)), "model": JUDGE_MODEL, "split": "dev",
               "judge": _confusion(judge_id, escalated, mode),
               "system": judge_alignment(judge_id, split="dev"),
               "gated_pass_ids": gated}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"dev-{judge_id}.json").write_text(json.dumps(metrics, indent=1) + "\n", encoding="utf-8")
    return metrics


def freeze(judge_id: str) -> dict[str, Any]:
    """Freeze the chosen version (the course helper refuses a second freeze)."""
    from analysis.helpers import freeze_judge

    return freeze_judge(judge_id)


def run_test(judge_id: str, mode: str = MODE) -> dict[str, Any]:
    """Score the frozen judge on test: code gate, then the model on escalated traces, once.

    Split from ``freeze`` so the freeze and the paid run are approved separately.
    Rerunning after an interruption only fills in missing predictions (cached).
    """
    from analysis.helpers import judge_alignment

    judge = _read_json(STATE_DIR / "judges" / f"{judge_id}.json")
    if judge.get("status") != "frozen":
        raise SystemExit(f"{judge_id} is not frozen; run the freeze step first")
    _use_saved_inputs()
    escalated, gated = _run_gated(judge_id, "test", mode)
    labels = {json.loads(l)["trace_id"]: json.loads(l)["label"]
              for l in (STATE_DIR / "hw5_labels" / f"{mode}.jsonl").read_text().splitlines() if l.strip()}
    test_ids = _read_json(STATE_DIR / "splits.json")[mode]["test"]
    metrics = {"judge_id": judge_id, "model": judge["model"], "split": "test", "frozen_at": judge.get("frozen_at"),
               "class_counts": {"test_pass": sum(labels[t] for t in test_ids), "test_fail": sum(1 - labels[t] for t in test_ids),
                                "judged_pass": sum(labels[t] for t in escalated), "judged_fail": sum(1 - labels[t] for t in escalated)},
               "judge": _confusion(judge_id, escalated, mode),
               "system": judge_alignment(judge_id, split="test"),
               "gated_pass_ids": gated}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"test-{judge_id}.json").write_text(json.dumps(metrics, indent=1) + "\n", encoding="utf-8")
    return metrics


HELDOUT_BATCH = "b8-escalation-heldout"
HELDOUT_INPUTS = STATE_DIR / "hw5_heldout_inputs.json"


def run_heldout(judge_id: str, mode: str = MODE, batch: str = HELDOUT_BATCH) -> dict[str, Any]:
    """Score a frozen judge on the blind held-out batch (generated after HW5, labeled before any judge saw it).

    Inputs are built exactly as for HW5 but saved to their own file, so
    hw5_trace_inputs.json stays unchanged. Labels come from the label file
    (failure-present = 1) and are flipped to Pass = 1 here; the HW5 label
    export and split are not touched.
    """
    import os

    from analysis.helpers import run_judge
    from analysis.helpers.tools import _wilson_interval
    from observability.instrument import load_env

    judge = _read_json(STATE_DIR / "judges" / f"{judge_id}.json")
    if judge.get("status") != "frozen":
        raise SystemExit(f"{judge_id} is not frozen")
    store = {r["trace_id"]: r for r in _read_json(STATE_DIR / "traces.json")}
    ids = [s["trace_id"] for s in _read_json(STATE_DIR / "samples.json") if s.get("batch") == batch]
    live = _live_labels(mode)
    missing = [t for t in ids if t not in live]
    if missing:
        raise SystemExit(f"{len(missing)} held-out traces are unlabeled; label them first")
    labels = {t: 1 - int(live[t]["label"]) for t in ids}
    records = [{"trace_id": t, "trace": [_session_context(store[t]), *[m for m in (_judge_message(m) for m in store[t]["trace"]) if m]]}
               for t in ids]
    HELDOUT_INPUTS.write_text(json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    load_env()
    os.environ["CARTWHEEL_JUDGE_TRACE_SOURCE"] = str(HELDOUT_INPUTS)
    escalated = sorted(t for t in ids if any(m.get("role") == "tool_call" and m.get("name") == "escalate_to_human"
                                             for m in store[t]["trace"]))
    gated = sorted(set(ids) - set(escalated))
    if gated:
        run_judge(judge_id, trace_ids=gated, classify=lambda _prompt, b: _GateVerdicts(b))
    run_judge(judge_id, trace_ids=escalated, batch_size=10)
    judge = _read_json(STATE_DIR / "judges" / f"{judge_id}.json")
    preds = judge["predictions"][judge["prompt_hash"]]

    def confusion(subset: list[str]) -> dict[str, Any]:
        tp = sum(1 for t in subset if labels[t] == 1 and preds[t] == 1)
        fn = sum(1 for t in subset if labels[t] == 1 and preds[t] == 0)
        tn = sum(1 for t in subset if labels[t] == 0 and preds[t] == 0)
        fp = sum(1 for t in subset if labels[t] == 0 and preds[t] == 1)
        return {"n": len(subset), "tp": tp, "fn": fn, "tn": tn, "fp": fp,
                "tpr": tp / (tp + fn) if tp + fn else None, "tpr_interval": _wilson_interval(tp, tp + fn),
                "tnr": tn / (tn + fp) if tn + fp else None, "tnr_interval": _wilson_interval(tn, tn + fp),
                "disagreements": sorted(t for t in subset if labels[t] != preds[t])}

    metrics = {"judge_id": judge_id, "model": judge["model"], "split": "heldout", "batch": batch,
               "class_counts": {"pass": sum(labels.values()), "fail": len(ids) - sum(labels.values()),
                                "judged_pass": sum(labels[t] for t in escalated), "judged_fail": sum(1 - labels[t] for t in escalated)},
               "judge": confusion(escalated), "system": confusion(ids), "gated_pass_ids": gated,
               "note": "Blind held-out set: 30 scenarios generated after HW5 from fresh users and orders, labeled by the student before any judge saw them, judged once by the frozen judge."}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"heldout-{judge_id}.json").write_text(json.dumps(metrics, indent=1) + "\n", encoding="utf-8")
    return metrics


def _print_metrics(m: dict[str, Any]) -> None:
    j, sysm = m["judge"], m["system"]
    fmt = lambda v, iv: f"{v:.2f} [{iv[0]:.2f}, {iv[1]:.2f}]" if v is not None else "n/a"
    print(f"{m['judge_id']} on {m['split']}, judge only (escalated traces, n={j['n']}):")
    print(f"  TP {j['tp']}  FN {j['fn']}  TN {j['tn']}  FP {j['fp']}")
    print(f"  TPR {fmt(j['tpr'], j['tpr_interval'])}   TNR {fmt(j['tnr'], j['tnr_interval'])}   disagreements {len(j['disagreements'])}")
    print(f"system, gate + judge (n={sysm['n']}): TPR {sysm['tpr']:.2f}  TNR {sysm['tnr']:.2f}  ({len(m['gated_pass_ids'])} gated Passes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["export", "inputs", "split", "dev", "freeze", "test", "heldout"])
    parser.add_argument("prompt", nargs="?", help="prompt file (dev) or judge id (freeze, test)")
    parser.add_argument("--mode", default=MODE)
    args = parser.parse_args()
    if args.step == "export":
        path = export_labels(args.mode)
        print(f"wrote {sum(1 for _ in path.open())} labels to {path.relative_to(REPO_ROOT)}")
    elif args.step == "inputs":
        path = prepare_inputs(args.mode)
        print(f"wrote {len(_read_json(path))} judge inputs to {path.relative_to(REPO_ROOT)}")
    elif args.step == "split":
        _split_report(args.mode, split_data(args.mode))
    elif args.step == "freeze":
        if not args.prompt:
            parser.error("freeze needs a judge id")
        j = freeze(args.prompt)
        print(f"froze {j['judge_id']} at {j['frozen_at']}")
    elif args.step == "heldout":
        if not args.prompt:
            parser.error("heldout needs a judge id")
        _print_metrics(run_heldout(args.prompt, args.mode))
    elif args.step == "test":
        if not args.prompt:
            parser.error("test needs a judge id")
        _print_metrics(run_test(args.prompt, args.mode))
    else:
        if not args.prompt:
            parser.error("dev needs a prompt file")
        _print_metrics(run_development(args.mode, args.prompt))


if __name__ == "__main__":
    main()
