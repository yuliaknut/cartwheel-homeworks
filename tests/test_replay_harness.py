from __future__ import annotations

import pytest

from replay.harness import ReplayInfraError, replay_case, summarize_rollouts
from replay.rollout import _one_check, judge_trace_text


def test_replay_resets_before_each_run_and_retries_only_infrastructure() -> None:
    resets = 0
    calls = 0

    def reset() -> None:
        nonlocal resets
        resets += 1

    def runner() -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ReplayInfraError("temporary service error")
        return {"passed": calls % 2 == 0}

    records = replay_case(runner, reset, n=2, max_infra_retries=1)

    assert resets == 3
    assert calls == 3
    assert [record["rollout"] for record in records] == [0, 1]
    assert [record["passed"] for record in records] == [True, False]


def test_replay_does_not_retry_a_completed_failure() -> None:
    calls = 0

    def runner() -> dict:
        nonlocal calls
        calls += 1
        return {"passed": False}

    records = replay_case(runner, lambda: None, n=2)

    assert calls == 2
    assert len(records) == 2


def test_rollout_summary_is_deterministic() -> None:
    records = [
        {"passed": True, "steps": 2},
        {"passed": False, "failure_modes": ["judge:a"], "steps": 4},
        {
            "passed": False,
            "failure_modes": ["judge:a", "check:b"],
            "steps": 6,
        },
    ]

    first = summarize_rollouts(records, bootstrap_iterations=100, seed=7)
    second = summarize_rollouts(records, bootstrap_iterations=100, seed=7)

    assert first == second
    assert first["failures"] == 2
    assert first["failure_rate"] == pytest.approx(2 / 3)
    assert first["mode_counts"] == {"judge:a": 2, "check:b": 1}
    assert first["steps"] == {"min": 2, "median": 4, "max": 6}


def test_judge_trace_text_uses_the_hw5_normalized_roles() -> None:
    transcript = {
        "turns": [
            {
                "user": "Where is my order?",
                "reply": "It shipped today.",
                "tool_calls": [
                    {
                        "name": "get_order",
                        "args": {"order_id": 42},
                        "result": {"ok": True, "status": "shipped"},
                    }
                ],
            }
        ]
    }

    assert judge_trace_text(transcript).splitlines() == [
        "user: Where is my order?",
        'tool_call: {"order_id": 42}',
        'tool_result: {"ok": true, "status": "shipped"}',
        "assistant: It shipped today.",
    ]


INTERNAL_DETAIL_PATTERNS = [
    r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b",
    r"\bcw-[a-z0-9-]+\b|\bstore-[a-z0-9-]+-policy\b",
    r"\b(?!(?:order|refund|ticket|product|request|listing)\b)[A-Za-z]+[\s_-]*id\b[\s:*#|]*\d+",
]


@pytest.mark.parametrize(
    ("reply", "leaks"),
    [
        ("The order shows refund_eligible: false.", True),
        ("Category: home_and_kitchen", True),
        ("Per cw-refunds, refunds go back to the card.", True),
        ("See store-juniper-home-goods-policy.", True),
        ("I found several organizers, all from store ID 20:", True),
        ("- **Store ID:** 1", True),
        ("Ticket ID: 152. Refund ID: 575. Order ID: 2885. Product ID: 553.", False),
        ("The store lookup needs the name rather than the numeric store id, so I'll retry.", False),
        ("Per the Cartwheel refund policy, this order is not eligible for a refund.", False),
        ("- **Status:** Auto-approved", False),
    ],
)
def test_reply_not_matches_flags_internal_details(reply: str, leaks: bool) -> None:
    transcript = {"final_reply": reply, "turns": []}
    results = [
        _one_check({"check": "reply_not_matches", "pattern": p}, transcript, None)[0]
        for p in INTERNAL_DETAIL_PATTERNS
    ]
    assert (not all(results)) is leaks
