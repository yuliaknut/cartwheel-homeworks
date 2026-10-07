"""Load pilot traces from Langfuse into analysis/state/samples.json for review.

Joins each trace with its scenario in the scenario file so the review page can
show the expected outcome next to the conversation. Multi-turn scenarios
produce one Langfuse trace per user message; they are merged per
(scenario_id, session_id), and when a scenario was run more than once only
the latest run is kept, so a rerun never splices two conversations together.

Usage (from the repository root, with the Langfuse stack running):

    uv run python -m analysis.load_pilot scenarios/pilot_scenarios.jsonl
    uv run python -m analysis.load_pilot scenarios/pilot_scenarios.jsonl --all   # also keep traces outside the file
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.helpers import langfuse_io
from analysis.helpers.normalization import _merge_multi_turn
from observability.instrument import load_env

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "analysis" / "state" / "samples.json"


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


def load_samples(scenario_path: Path, keep_all: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (samples, scenario ids with no trace)."""
    scenarios = _load_scenarios(scenario_path)
    client = langfuse_io._client()
    traces = langfuse_io.fetch_traces(client=client)

    # Group by (scenario, session) so a rerun does not merge into an earlier run.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        sid = trace["meta"].get("scenario_id")
        if not sid:
            continue
        session = str(trace.get("metadata", {}).get("cartwheel.session_id") or trace["trace_id"])
        groups[(sid, session)].append(trace)

    latest: dict[str, dict[str, Any]] = {}
    for (sid, _session), group in groups.items():
        merged = _merge_multi_turn(group)[0]
        current = latest.get(sid)
        if current is None or (merged.get("timestamp") or "") > (current.get("timestamp") or ""):
            latest[sid] = merged

    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
    project_id = _project_id(client)
    samples: list[dict[str, Any]] = []
    for sid, trace in latest.items():
        scenario = scenarios.get(sid)
        if scenario is None and not keep_all:
            continue
        trace = dict(trace)
        trace["permalink"] = trace.get("permalink") or _permalink(host, project_id, trace["trace_id"])
        if scenario is not None:
            trace["expected"] = scenario["expected"]
            trace["scenario_group"] = scenario["scenario_group"]
            trace["data_quality_case_id"] = scenario.get("data_quality_case_id")
            trace["scenario"] = scenario["tuple"]
            trace["scripted_messages"] = [scenario["opening_message"], *scenario.get("followups", [])]
        samples.append(trace)

    order = {sid: n for n, sid in enumerate(scenarios)}
    samples.sort(key=lambda t: (order.get(t["meta"].get("scenario_id"), 10**9), t["meta"].get("scenario_id") or ""))
    missing = [sid for sid in scenarios if sid not in latest]
    return samples, missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--all", action="store_true", help="also keep traces whose scenario id is not in the file")
    args = parser.parse_args()
    load_env()
    samples, missing = load_samples(args.scenarios, keep_all=args.all)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(samples, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(samples)} samples to {args.output}")
    if missing:
        print(f"{len(missing)} scenario(s) with no trace yet: {', '.join(missing[:10])}{' …' if len(missing) > 10 else ''}")


if __name__ == "__main__":
    main()
