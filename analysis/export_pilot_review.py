"""Turn the review page's annotations into scenarios/pilot_review.jsonl.

Homework 3, Part B asks for one record per reviewed scenario with:
scenario_id, scenario_valid, confirmed_failure, evidence, scenario_change.
The Homework 3 review page stores each trace's note and decisions in
analysis/state/hw3/annotations.json (moved out of analysis/state/annotations.json
when Homework 4 took that file over); this script writes the handout's file from
them. Records are emitted only for traces that were actually reviewed (a note
or at least one decision) and carry an explicit verdict: scenario_valid is
never inferred from its absence. A confirmed failure is never counted when the
scenario is invalid, and inline notes are appended to the evidence as
[quote] note lines.

    uv run python -m analysis.export_pilot_review
    uv run python -m analysis.export_pilot_review --output scenarios/pilot_review.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = REPO_ROOT / "analysis" / "state" / "hw3" / "annotations.json"
DEFAULT_OUTPUT = REPO_ROOT / "scenarios" / "pilot_review.jsonl"


def _load_all(path: Path, kind: str) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if isinstance(data, dict):
        data = data.get("annotations", [])
    return [a for a in data if isinstance(a, dict) and a.get("kind") == kind]


def _load_annotations(path: Path) -> list[dict]:
    return _load_all(path, kind="trace_note")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scenarios", type=Path, default=REPO_ROOT / "scenarios" / "pilot_scenarios.jsonl",
                        help="only annotations whose scenario id is in this file are exported")
    args = parser.parse_args()

    allowed = {json.loads(l)["id"] for l in args.scenarios.read_text(encoding="utf-8").splitlines() if l.strip()}
    records, skipped = [], []
    inline_notes = _load_all(args.annotations, kind="inline")
    for a in sorted(_load_annotations(args.annotations), key=lambda a: a.get("scenario_id") or ""):
        if a.get("scenario_id") not in allowed:
            continue
        note = (a.get("note") or "").strip()
        valid, failure = a.get("scenario_valid"), a.get("confirmed_failure")
        if not note and valid is None and failure is None:
            continue
        if valid is False:
            failure = False  # the handout counts failures only for valid scenarios
        if valid is None or failure is None:
            skipped.append(a.get("scenario_id"))  # no explicit verdict; validity is never inferred
            continue
        inline = [x for x in inline_notes if x.get("scenario_id") == a.get("scenario_id")]
        if inline:
            note = (note + "\n" if note else "") + "\n".join(f"[{(x.get('quote') or '').strip()[:120]}] {(x.get('note') or '').strip()}" for x in inline)
        records.append(
            {
                "scenario_id": a["scenario_id"],
                "scenario_valid": bool(valid),
                "confirmed_failure": bool(failure) and bool(valid),
                "evidence": note,
                "scenario_change": (a.get("scenario_change") or "").strip() or None,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    failures = sum(r["confirmed_failure"] for r in records)
    print(f"wrote {len(records)} review records to {args.output}; confirmed failures: {failures} (handout minimum 5)")
    if skipped:
        print(f"{len(skipped)} annotated trace(s) missing a verdict (pass, fail, or invalid scenario), not exported: {', '.join(map(str, skipped))}")


if __name__ == "__main__":
    main()
