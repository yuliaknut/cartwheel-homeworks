"""Judge inputs that match what a Homework 5 judge was validated on.

The course formatter (``replay.rollout.judge_trace_text``) prints tool calls
without their names and has no session header. The ``unnecessary_escalation``
judge was validated in HW5 on inputs from ``analysis/run_judges.py``, which
name every tool call and result and open with the user's role, id, and the
world date. Its HW5 metrics only describe that input, so Harbor rebuilds it
here. HW5 also ran the judge behind a code gate: a conversation with no
``escalate_to_human`` call is a Pass without a model call.
"""

from __future__ import annotations

import json
from typing import Any

# Judges with a HW5-specific input. Every other judge keeps the course format.
HW5_JUDGE_INPUTS: dict[str, dict[str, Any]] = {
    "unnecessary_escalation": {"gate_tool": "escalate_to_human"},
}


def _as_json(value: Any) -> str:
    """Render a value like the HW5 store: dicts and lists as sorted JSON.

    A tool result that arrives as a JSON string is parsed first so its keys
    are sorted the same way.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
        if isinstance(value, str):
            return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def session_context(case_input: dict[str, Any], world_date: str) -> str:
    """The HW5 ``session_context`` line for one case."""
    parts = [f"User role: {case_input['role']}", f"User id: {case_input['user_id']}"]
    if case_input.get("store_id"):
        parts.append(f"Store id: {case_input['store_id']}")
    parts.append(f"World date of the conversation: {world_date}")
    return "; ".join(parts)


def _call_lines(call: dict[str, Any]) -> list[str]:
    name = call.get("name")
    return [
        f"tool_call: {name}({_as_json(call.get('args'))})",
        f"tool_result: {name} -> {_as_json(call.get('result'))}",
    ]


def hw5_judge_text(
    transcript: dict[str, Any], case_input: dict[str, Any], world_date: str
) -> str:
    """Format a runtime transcript like ``analysis/run_judges.prepare_inputs``."""
    lines = [f"session_context: {session_context(case_input, world_date)}"]
    for turn in transcript.get("turns", []):
        lines.append(f"user: {turn.get('user', '')}")
        calls = turn.get("tool_calls", [])
        events = turn.get("events")
        if events is None:
            # Transcript from before events were recorded: calls, then reply.
            for call in calls:
                lines.extend(_call_lines(call))
            if turn.get("reply"):
                lines.append(f"assistant: {turn['reply']}")
            continue
        for event in events:
            if "tool_call" in event:
                lines.extend(_call_lines(calls[event["tool_call"]]))
            elif event.get("text"):
                lines.append(f"assistant: {event['text']}")
    return "\n".join(lines)


def gate_passes(transcript: dict[str, Any], tool: str) -> bool:
    """True when the gated tool was never called, so the verdict is Pass."""
    return not any(
        call.get("name") == tool
        for turn in transcript.get("turns", [])
        for call in turn.get("tool_calls", [])
    )
