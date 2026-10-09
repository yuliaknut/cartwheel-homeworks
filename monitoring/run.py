"""Run the Homework 7 monitor over one period of Langfuse traces.

    uv run python -m monitoring.run --period before          # plan only, no judge calls
    uv run python -m monitoring.run --period before --yes    # paid: judge the selection
    uv run python -m monitoring.run --last-hours 24 --yes    # the scheduled form

Steps for one period:

  1. Read the period from ``monitoring/config.json``.
  2. Fetch the Langfuse traces in its time window.
  3. Keep the monitored scenarios, drop attempts that never replied (the HW3
     credit failures), check every scenario is present exactly once and that
     every trace used the configured Cartwheel model, then merge each
     conversation's turns into one record whose id is the final trace id.
  4. Record the tools and user-turn count of each conversation, from the
     trace only.
  5. Build the judge text exactly as Homework 5 did (session context, user and
     agent messages, named tool calls and results). No labels, notes, or
     scenario metadata.
  6. Select the random sample and the configured risk groups.
  7. Show the selection and the number of judge calls, and stop unless
     ``--yes`` was given.
  8. Judge the union once: the HW5 code gate passes conversations with no
     ``escalate_to_human`` call, and the frozen model judges the rest.
  9. Save the random and risk verdicts separately (1 = failure present).
 10. Correct the random-sample rate with the judge's held-out test results,
     write the Langfuse scores (stable ids, so a rerun updates them), and
     record the period in ``monitoring/history.jsonl`` and the chart.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from monitoring.sample import DEFAULT_RISK_GROUPS, select_traces

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "monitoring" / "config.json"
SCENARIOS_PATH = REPO_ROOT / "scenarios" / "monitoring_scenarios.jsonl"
OUTPUT_DIR = REPO_ROOT / "monitoring" / "output"
HISTORY_PATH = REPO_ROOT / "monitoring" / "history.jsonl"
CHART_PATH = REPO_ROOT / "monitoring" / "prevalence.svg"
GATE_TOOL = "escalate_to_human"


class PeriodRejected(ValueError):
    """The period is not a valid, comparable monitoring period."""


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _scenario_id(summary: Any) -> str | None:
    metadata = getattr(summary, "metadata", None) or {}
    attributes = metadata.get("attributes") or {}
    if isinstance(attributes, str):
        attributes = json.loads(attributes)
    return attributes.get("cartwheel.scenario_id") or metadata.get("cartwheel.scenario_id")


def fetch_window(start: dt.datetime, end: dt.datetime, scenario_ids: set[str] | None) -> list[dict[str, Any]]:
    """Normalized Langfuse traces in [start, end], optionally limited to scenario ids."""
    from analysis.helpers.langfuse_io import _client
    from analysis.helpers.normalization import normalize_trace

    client = _client()
    summaries: list[Any] = []
    page = 1
    while True:
        response = client.api.trace.list(page=page, limit=100, from_timestamp=start, to_timestamp=end)
        batch = list(response.data or [])
        summaries.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    if scenario_ids is not None:
        summaries = [s for s in summaries if _scenario_id(s) in scenario_ids]
    traces = []
    for summary in summaries:
        trace = normalize_trace(client.api.trace.get(summary.id))
        trace["agent_cost_usd"] = float(getattr(summary, "total_cost", None) or 0)
        traces.append(trace)
    return traces


def _model_matches(observed: str, configured: str) -> bool:
    """``gpt-5.5`` matches the dated snapshot name ``gpt-5.5-2026-04-23``."""
    return observed == configured or (
        observed.startswith(configured + "-") and observed[len(configured) + 1:][:4].isdigit()
    )


def judge_text(record: dict[str, Any]) -> str:
    """The Homework 5 judge input for one merged conversation."""
    from analysis.helpers.normalization import normalize_trace
    from analysis.run_judges import _judge_message, _session_context

    messages = [m for m in (_judge_message(m) for m in record["trace"]) if m]
    return normalize_trace({"trace_id": record["id"], "trace": [_session_context(record), *messages]})["text"]


def build_conversations(
    traces: list[dict[str, Any]], model: str, scenario_ids: set[str] | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge turns into conversation records and validate the period.

    With ``scenario_ids`` (a comparison period) the period is rejected unless
    every scenario appears exactly once. Without it (the scheduled window)
    traces are grouped by session id. Any replied trace that used another
    model rejects the period.
    """
    replied = [t for t in traces if t.get("output") is not None]
    report: dict[str, Any] = {
        "langfuse_traces": len(traces),
        "dropped_no_reply": len(traces) - len(replied),
        "agent_cost_usd": round(sum(t.get("agent_cost_usd", 0) for t in traces), 4),
    }

    wrong_models = sorted({m for t in replied for m in t.get("models", []) if not _model_matches(m, model)})
    if wrong_models:
        raise PeriodRejected(f"traces used another model than {model}: {wrong_models}")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sessions: dict[str, set[str]] = defaultdict(set)
    for trace in replied:
        session = str(trace["meta"].get("session_id") or trace["trace_id"])
        key = trace["meta"].get("scenario_id") if scenario_ids is not None else session
        groups[key].append(trace)
        sessions[key].add(session)

    if scenario_ids is not None:
        missing = sorted(scenario_ids - set(groups))
        if missing:
            raise PeriodRejected(f"{len(missing)} scenario ids missing from the period: {missing[:5]}")
        repeated = sorted(sid for sid, s in sessions.items() if len(s) > 1)
        if repeated:
            raise PeriodRejected(f"scenarios run more than once in the period: {repeated[:5]}")

    records = []
    for key, group in groups.items():
        group.sort(key=lambda t: t.get("timestamp") or "")
        messages = [m for t in group for m in t["trace"]]
        tools = sorted({str(m["name"]) for m in messages if m.get("role") == "tool_call" and m.get("name")})
        record = {
            "id": group[-1]["trace_id"],
            "timestamp": group[-1].get("timestamp"),
            "conversation": key,
            "trace_ids": [t["trace_id"] for t in group],
            "metadata": group[0].get("metadata") or {},
            "meta": group[0].get("meta") or {},
            "trace": messages,
            "tools": tools,
            "turn_count": sum(m.get("role") == "user" for m in messages),
        }
        record["text"] = judge_text(record)
        records.append(record)
    records.sort(key=lambda r: r["conversation"])
    report["conversations"] = len(records)
    return records, report


def judge_with_gate(judge_id: str, records: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, Any]]:
    """The frozen HW5 judge: the code gate, then the model on escalated conversations.

    Also returns what the model calls cost, measured from LiteLLM's per-call
    usage. Calls DocETL answers from its cache reach no provider and cost 0.
    """
    import litellm

    from monitoring.run_judges import judge_sample

    usage = {"provider_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def _record(kwargs: dict[str, Any], response: Any, *_: Any) -> None:
        usage["provider_calls"] += 1
        tokens = getattr(response, "usage", None)
        usage["input_tokens"] += int(getattr(tokens, "prompt_tokens", 0) or 0)
        usage["output_tokens"] += int(getattr(tokens, "completion_tokens", 0) or 0)
        usage["cost_usd"] += float(kwargs.get("response_cost") or 0)

    verdicts = {r["id"]: 0 for r in records if GATE_TOOL not in r["tools"]}
    escalated = [r for r in records if GATE_TOOL in r["tools"]]
    litellm.success_callback.append(_record)
    try:
        if escalated:
            verdicts.update(judge_sample(judge_id, [{"id": r["id"], "text": r["text"]} for r in escalated]))
    finally:
        litellm.success_callback.remove(_record)
    usage["cost_usd"] = round(usage["cost_usd"], 6)
    usage["cost_basis"] = "measured" if usage["provider_calls"] else "cache"
    return {r["id"]: verdicts[r["id"]] for r in records}, usage


def run(label: str, start: dt.datetime, end: dt.datetime, scenario_ids: set[str] | None, yes: bool) -> dict[str, Any]:
    config = load_config()
    traces = fetch_window(start, end, scenario_ids)
    records, report = build_conversations(traces, config["model"], scenario_ids)
    report.update({"period": label, "from": start.isoformat(), "to": end.isoformat()})

    out_dir = OUTPUT_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)
    if not records:
        report.update({"random_sample": 0, "risk_sample": 0, "judge_calls": 0})
        (out_dir / "verdicts.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(f"{label}: no eligible conversations; the judge was not called.")
        return report

    unknown = [g for g in config["risk_groups"] if g not in DEFAULT_RISK_GROUPS]
    if unknown:
        raise ValueError(f"unknown risk groups in config: {unknown}")
    plan = select_traces(
        records, config["random_rate"], {g: DEFAULT_RISK_GROUPS[g] for g in config["risk_groups"]}
    )
    risk_ids = list(dict.fromkeys(r["id"] for group in plan["risk_groups"].values() for r in group))
    model_calls = sum(GATE_TOOL in r["tools"] for r in plan["to_judge"])
    report.update({
        "random_sample": len(plan["random"]),
        "risk_sample": len(risk_ids),
        "risk_groups": {g: len(rs) for g, rs in plan["risk_groups"].items()},
        "to_judge": len(plan["to_judge"]),
        "judge_calls": model_calls,
    })
    print(
        f"{label}: {report['langfuse_traces']} Langfuse traces ({report['dropped_no_reply']} without a reply dropped), "
        f"{len(records)} conversations\n"
        f"  random sample {len(plan['random'])}, risk groups {report['risk_groups']} ({len(risk_ids)} unique)\n"
        f"  union to judge {len(plan['to_judge'])}: {len(plan['to_judge']) - model_calls} passed by the code gate, "
        f"{model_calls} {config['judge_id']} model calls"
    )
    if not yes:
        print("  plan only: rerun with --yes to call the judge")
        return report

    verdicts, judge_usage = judge_with_gate(config["judge_id"], plan["to_judge"])
    report["judge_usage"] = judge_usage
    print(f"  judge usage: {judge_usage}")
    result = {
        **report,
        "judge_id": config["judge_id"],
        "model": config["model"],
        "random_verdicts": {r["id"]: verdicts[r["id"]] for r in plan["random"]},
        "risk_verdicts": {tid: verdicts[tid] for tid in risk_ids},
        "risk_membership": {g: [r["id"] for r in rs] for g, rs in plan["risk_groups"].items()},
    }
    (out_dir / "verdicts.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")

    # Part C: correct the random-sample rate, write scores, record history.
    from monitoring.correct import corrected_mode_prevalence
    from monitoring.run_judges import judge_test_data
    from monitoring.write_scores import build_score_records, post_scores

    estimate = corrected_mode_prevalence(
        list(result["random_verdicts"].values()), *judge_test_data(config["judge_id"])
    )
    scores = build_score_records(
        config["judge_mode"], result["random_verdicts"], result["risk_verdicts"], estimate, label
    )
    (out_dir / "scores.json").write_text(json.dumps(scores, indent=1) + "\n", encoding="utf-8")
    stamps = {r["id"]: _parse_time(r["timestamp"]) for r in records if r.get("timestamp")}
    written = post_scores(scores, session_id=f"hw7-monitor-{label}", timestamps=stamps, period_timestamp=end)
    flagged_risk = sum(result["risk_verdicts"].values())
    print(
        f"  raw {estimate['raw']}, corrected {estimate['corrected']} "
        f"(95% CI {estimate['ci_low']}-{estimate['ci_high']}), threshold {config['threshold']}\n"
        f"  risk groups flagged {flagged_risk} of {len(risk_ids)}; {written} Langfuse scores written"
    )
    entry = {
        "period": label,
        "judge_id": config["judge_id"],
        "model": config["model"],
        "from": report["from"],
        "to": report["to"],
        "langfuse_traces": report["langfuse_traces"],
        "dropped_no_reply": report["dropped_no_reply"],
        "conversations": report["conversations"],
        "random_sample": report["random_sample"],
        "risk_sample": report["risk_sample"],
        "risk_flagged": flagged_risk,
        "judge_calls": report["judge_calls"],
        "judge_usage": report["judge_usage"],
        **{k: estimate[k] for k in ("raw", "corrected", "ci_low", "ci_high",
                                    "failure_sensitivity", "pass_specificity")},
        "threshold": config["threshold"],
        "crossed": estimate["corrected"] > config["threshold"],
    }
    result["estimate"] = estimate
    if scenario_ids is not None:
        update_history(entry, config)
    else:
        (out_dir / "history_entry.json").write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
    return result


def update_history(entry: dict[str, Any], config: dict[str, Any]) -> None:
    """One line per comparison period (a rerun replaces its line), then redraw the chart."""
    from monitoring.chart import prevalence_chart

    rows = []
    if HISTORY_PATH.exists():
        rows = [json.loads(line) for line in HISTORY_PATH.read_text().splitlines() if line.strip()]
    previous = next((r for r in rows if r["period"] == entry["period"]), None)
    if previous and entry["judge_usage"]["cost_basis"] == "cache" and previous.get("judge_usage"):
        entry["judge_usage"] = previous["judge_usage"]  # a cached rerun cost nothing; keep the paid run's cost
    if previous and "agent_usage" in previous:
        entry["agent_usage"] = previous["agent_usage"]  # the cost of producing the period's traces (HW9)
    rows = [r for r in rows if r["period"] != entry["period"]] + [entry]
    order = {p["label"]: n for n, p in enumerate(config["periods"])}
    rows.sort(key=lambda r: order.get(r["period"], len(order)))
    HISTORY_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    points = [{"label": r["period"], **{k: r[k] for k in ("corrected", "ci_low", "ci_high")}} for r in rows]
    CHART_PATH.write_text(prevalence_chart(points, config["threshold"], config["judge_mode"]), encoding="utf-8")


def main() -> None:
    from observability.instrument import load_env

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--period", help="a period label from monitoring/config.json")
    which.add_argument("--last-hours", type=float, help="monitor the trailing window, grouped by session id")
    parser.add_argument("--yes", action="store_true", help="call the judge (paid)")
    args = parser.parse_args()
    load_env()

    if args.period:
        period = next((p for p in load_config()["periods"] if p["label"] == args.period), None)
        if period is None:
            raise SystemExit(f"no period {args.period!r} in {CONFIG_PATH}")
        scenario_ids = {json.loads(line)["id"] for line in SCENARIOS_PATH.read_text().splitlines() if line.strip()}
        run(period["label"], _parse_time(period["from"]), _parse_time(period["to"]), scenario_ids, args.yes)
    else:
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(hours=args.last_hours)
        run(f"last-{args.last_hours:g}h-{end:%Y%m%dT%H%M}", start, end, None, args.yes)


if __name__ == "__main__":
    main()
