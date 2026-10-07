"""Load the Homework 3 support traces from Langfuse into the local review store.

Homework 4 reviews conversations, not turns. Cartwheel records one Langfuse
trace per user turn (the native session field is empty; the conversation id
lives in metadata as ``cartwheel.session_id``), so this loader:

  * pulls every trace carrying a ``cartwheel.scenario_id`` through the
    instructor's loader (``analysis.helpers.langfuse_io.fetch_traces``),
  * drops attempts that never produced a reply (the credit-exhaustion retries:
    null output, errored ``openai.response`` spans),
  * groups turns by (scenario id, session id), keeps the latest run of each
    scenario, and merges the turns in order, stamping ``turn`` and
    ``turn_trace_id`` on every message so the page can draw turn dividers
    and link each turn back to Langfuse,
  * joins the scenario file for the extra metadata (group, tuple, expected,
    damaged-record case, scripted messages),
  * writes ``analysis/state/traces.json`` (the full store, one record per
    conversation) and ``analysis/state/trace_index.json`` (a compact index
    used for batch selection and the coverage tables).

The store keeps the message list, features, meta, and metadata the
instructor's normalizer expects, so ``analysis.helpers.selection`` and
``select_traces`` can read it directly. Observations are dropped to keep the
file small; the review page renders from the message list.

    uv run python -m analysis.review_app.load_traces scenarios/support_scenarios.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.helpers import langfuse_io
from analysis.helpers.normalization import _flatten
from observability.instrument import load_env

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "analysis" / "state"
RETRIEVAL_TOOLS = {"search_help_center", "get_policy"}


def _load_scenarios(path: Path) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            scenarios[record["id"]] = record
    return scenarios


def _project_id(client: Any) -> str | None:
    try:
        projects = client.api.projects.get()
        data = getattr(projects, "data", None) or []
        return str(data[0].id) if data else None
    except Exception:  # pragma: no cover - best effort only
        return os.environ.get("LANGFUSE_PROJECT_ID")


def _permalink(host: str, project_id: str | None, trace_id: str) -> str | None:
    if not project_id:
        return None
    return f"{host.rstrip('/')}/project/{project_id}/traces/{trace_id}"


def _final_reply(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return str(m.get("text") or m.get("content") or "")
    return ""


def merge_turns(group: list[dict[str, Any]], session_id: str, host: str, project_id: str | None) -> dict[str, Any]:
    """Merge the per-turn traces of one conversation, oldest first."""
    group = sorted(group, key=lambda t: t.get("timestamp") or "")
    first = group[0]
    messages: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    models: list[str] = []
    for n, t in enumerate(group, start=1):
        for m in t.get("trace") or []:
            m = dict(m)
            m["turn"] = n
            m["turn_trace_id"] = t["trace_id"]
            messages.append(m)
        turns.append({
            "turn": n,
            "trace_id": t["trace_id"],
            "timestamp": t.get("timestamp"),
            "permalink": t.get("permalink") or _permalink(host, project_id, t["trace_id"]),
        })
        for model in t.get("models") or []:
            if model not in models:
                models.append(model)
    tool_calls = [m for m in messages if m.get("role") == "tool_call"]
    text = _flatten(messages)
    features = {
        "turn_count": sum(m.get("role") in {"user", "assistant"} for m in messages),
        "user_turns": len(turns),
        "tool_call_count": len(tool_calls),
        "distinct_tools": len({m.get("name") for m in tool_calls}),
        "has_retrieval": int(any(m.get("name") in RETRIEVAL_TOOLS for m in tool_calls)),
        "tool_errors": sum(
            1 for m in messages
            if m.get("role") == "tool_result" and isinstance(m.get("content"), dict) and m["content"].get("ok") is False
        ),
        "tokens": len(text.split()),
        "reply_chars": len(_final_reply(messages)),
    }
    return {
        "id": first["trace_id"],
        "trace_id": first["trace_id"],
        "session_id": session_id,
        "timestamp": first.get("timestamp"),
        "models": models,
        "trace": messages,
        "text": text,
        "features": features,
        "meta": dict(first.get("meta") or {}),
        "segments": dict(first.get("segments") or {}),
        "metadata": dict(first.get("metadata") or {}),
        "output": group[-1].get("output"),
        "permalink": turns[0]["permalink"],
        "turns": turns,
    }


def build_store(scenario_path: Path, keep_all: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (records, report). Records are sorted in scenario-file order."""
    scenarios = _load_scenarios(scenario_path)
    client = langfuse_io._client()
    traces = langfuse_io.fetch_traces(client=client)
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
    project_id = _project_id(client)

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    errored = 0
    for trace in traces:
        sid = trace["meta"].get("scenario_id")
        if not sid:
            continue
        if trace.get("output") is None:  # an attempt that never replied (e.g. provider 429s)
            errored += 1
            continue
        session = str(trace.get("metadata", {}).get("cartwheel.session_id") or trace["trace_id"])
        groups[(sid, session)].append(trace)

    latest: dict[str, dict[str, Any]] = {}
    reruns = 0
    for (sid, session), group in groups.items():
        record = merge_turns(group, session, host, project_id)
        current = latest.get(sid)
        if current is not None:
            reruns += 1
        if current is None or (record.get("timestamp") or "") > (current.get("timestamp") or ""):
            latest[sid] = record

    records: list[dict[str, Any]] = []
    for sid, record in latest.items():
        scenario = scenarios.get(sid)
        if scenario is None and not keep_all:
            continue
        if scenario is not None:
            record["scenario_group"] = scenario["scenario_group"]
            record["data_quality_case_id"] = scenario.get("data_quality_case_id")
            record["expected"] = scenario["expected"]
            record["scenario"] = scenario["tuple"]
            record["scripted_messages"] = [scenario["opening_message"], *scenario.get("followups", [])]
        records.append(record)
    order = {sid: n for n, sid in enumerate(scenarios)}
    records.sort(key=lambda r: (order.get(r["meta"].get("scenario_id"), 10**9), r["meta"].get("scenario_id") or ""))
    report = {
        "langfuse_traces": len(traces),
        "errored_attempts_dropped": errored,
        "reruns_superseded": reruns,
        "conversations": len(records),
        "missing_scenario_ids": [sid for sid in scenarios if sid not in latest],
    }
    return records, report


def index_record(r: dict[str, Any]) -> dict[str, Any]:
    t = r.get("scenario") or {}
    f = r.get("features") or {}
    return {
        "trace_id": r["trace_id"],
        "scenario_id": r["meta"].get("scenario_id"),
        "session_id": r.get("session_id"),
        "role": r["meta"].get("role") or t.get("role"),
        "group": r.get("scenario_group"),
        "intent": t.get("intent"),
        "dq": r.get("data_quality_case_id"),
        "difficulty": t.get("difficulty"),
        "record_state": t.get("record_state"),
        "applicable_policy": t.get("applicable_policy"),
        "tools_needed": t.get("tools_needed"),
        "user_style": t.get("user_style"),
        "user_turns": f.get("user_turns"),
        "tools": f.get("tool_call_count"),
        "distinct_tools": f.get("distinct_tools"),
        "has_retrieval": f.get("has_retrieval"),
        "tool_errors": f.get("tool_errors"),
        "reply_chars": f.get("reply_chars"),
        "permalink": r.get("permalink"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("--state", type=Path, default=STATE_DIR, help="state directory (default analysis/state)")
    parser.add_argument("--all", action="store_true", help="also keep conversations whose scenario id is not in the file")
    args = parser.parse_args()
    load_env()
    records, report = build_store(args.scenarios, keep_all=args.all)
    args.state.mkdir(parents=True, exist_ok=True)
    (args.state / "traces.json").write_text(json.dumps(records, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.state / "trace_index.json").write_text(
        json.dumps([index_record(r) for r in records], indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=1))
    print(f"wrote {len(records)} conversations to {args.state / 'traces.json'} and the index to {args.state / 'trace_index.json'}")


if __name__ == "__main__":
    main()
