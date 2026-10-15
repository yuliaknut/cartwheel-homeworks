"""Run a Homework 5 judge in-process on the input it was validated on.

The course replay path (``replay.rollout.judge_reply_with_text``) shows a
judge only the final reply and the retrieved policy documents, with a direct
LiteLLM call and a lenient parser. The ``unnecessary_escalation`` judge was
validated in HW5 on whole conversations (``analysis/run_judges.py``), behind
a code gate, through the DocETL map in ``analysis/helpers/scale.py``. Its HW5
metrics only describe that setup, so HW8 scoring rebuilds it here: the same
input as ``harbor_adapter.judge_input``, the same DocETL prompt wrapper as
the Harbor verifier (``harbor_adapter.export._hw5_judge_py``), and a strict
Pass/Fail parser.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from harbor_adapter.judge_input import HW5_JUDGE_INPUTS, gate_passes, hw5_judge_text


class MalformedVerdict(ValueError):
    """The judge returned something other than exactly Pass or Fail."""


def uses_hw5_input(mode: str) -> bool:
    return mode in HW5_JUDGE_INPUTS


def world_date(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'world_asof'").fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"meta.world_asof missing from {db_path}")
    return str(row[0])


def _decode(row: dict[str, Any]) -> str:
    critique = row.get("critique")
    if not isinstance(critique, str) or not critique.strip():
        raise MalformedVerdict("judge result needs a critique")
    verdict = row.get("result")
    if verdict not in ("Pass", "Fail"):
        raise MalformedVerdict(f"judge result must be Pass or Fail, got {verdict!r}")
    return verdict.lower()


def _run_docetl(prompt_text: str, model: str, content: str) -> dict[str, Any]:
    from docetl.api import Dataset, MapOp, Pipeline, PipelineOutput, PipelineStep

    with tempfile.TemporaryDirectory(prefix="cartwheel-judge-") as directory:
        root = Path(directory)
        input_path = root / "input.json"
        output_path = root / "output.json"
        input_path.write_text(json.dumps([{"trace_id": "current", "content": content}]))
        operation = MapOp(
            name="classify_failure_mode",
            type="map",
            model=model,
            prompt=(
                prompt_text
                + "\n\n--- Trace to evaluate ---\n"
                + "{{ input.content }}\n\n"
                + "First write a critique of the trace against the criterion. "
                + "Use specific evidence from the provided trace. Then return result "
                + "as exactly Pass when the named failure is absent, or Fail when present."
            ),
            output={"schema": {"critique": "string", "result": "string"}},
        )
        pipeline = Pipeline(
            name="cartwheel_judge",
            datasets={"traces": Dataset(type="file", path=str(input_path))},
            operations=[operation],
            steps=[
                PipelineStep(
                    name="classify", input="traces", operations=["classify_failure_mode"]
                )
            ],
            output=PipelineOutput(
                type="file", path=str(output_path), intermediate_dir=str(root)
            ),
        )
        pipeline.run()
        rows = json.loads(output_path.read_text())
    if len(rows) != 1:
        raise MalformedVerdict("judge returned an unexpected number of results")
    return rows[0]


def judge_case(
    mode: str,
    judge: dict[str, Any],
    transcript: dict[str, Any],
    case_input: dict[str, Any],
    db_path: Path,
) -> tuple[str, str]:
    """Return ("pass" | "fail", reason) for one HW5-input judge on one run."""
    from agent.agent import LITELLM_COURSE_MODELS

    gate_tool = HW5_JUDGE_INPUTS[mode]["gate_tool"]
    if gate_passes(transcript, gate_tool):
        return "pass", f"Code gate: no {gate_tool} call, so no judge call."
    content = hw5_judge_text(transcript, case_input, world_date(db_path))
    model = LITELLM_COURSE_MODELS.get(judge["model"], judge["model"])
    row = _run_docetl(judge["prompt_text"], model, content)
    verdict = _decode(row)
    return verdict, f"{row['result']}: {row['critique']}"
