# Cartwheel improve loop program

The setup for `.agents/skills/improve-loop/SKILL.md` in Homework 8.

Written by the student as the optional exercise in Part D, after the improve
loop had already been closed under the instructor's version of this file
(commit 2acad7b). The entries in `optimize/results/improve-loop.jsonl` were
made under that version. This version adds what Parts C and D showed was
missing: a keep rule that survives judge noise, a guard against fixing
unnecessary escalation by never escalating, the session-field invariant, and
a budget reserve for the Part F comparison.

## Goal

Reduce `unnecessary_escalation` (requirement ESC-5 in `SPEC.md`), the failure
mode recorded in `optimize/results/target.json`: the agent opens a ticket with
`escalate_to_human` for a case it could settle from the help center and the
order record. Only an unprompted ticket on a settled case counts. Offering a
ticket and asking the user is not a failure. Opening a ticket on a case that
needs one (an account change, a record that contradicts itself, a dispute
with no policy to settle it) is correct and must not be traded away for score.

## Files you may edit

The files in `optimize/allowlist.txt`, one layer per attempt:

- prompt: `SYSTEM_PROMPT_TEMPLATE` in `agent/agent.py`
- tool: a tool description in `agent/agent.py` or tool code in `agent/tools.py`
- harness: `agent/guards.py`, `agent/auth.py`, `agent/config.py`, and the
  context the server injects (`render_system_prompt` in `agent/agent.py`)

Invariants for every attempt:

- the prompt keeps the four injected session fields `{role}`, `{user_id}`,
  `{store_id}`, `{world_date}`; a candidate missing any of them is rejected
  before it is run
- the permission checks in `agent/auth.py`, the confirmation rules, and the
  refund threshold in `agent/guards.py` are never weakened
- the narration line before each tool call stays worded so that
  `claude-opus-5-5` does not refuse the prompt (Part A, paid runs 4 to 6)

## Files you must never edit

`eval_cases/`, `tests/`, `analysis/state/judges/` (the frozen HW5 judge
`unnecessary_escalation-v2`), `optimize/state/` (the split and the budget),
and `replay/` (the scorer; it is not in the grader hash but is treated as
frozen from `optimize.prepare` onward). Never run `optimize.runner --split
test`, `optimize.frontier`, or any test case before the final configuration is
saved in Part E.

## Evaluation

```bash
uv run python -m optimize.runner --split development --candidate <short-name> --search --model claude-haiku-5-5
```

Pass `--model` explicitly: the runner's default comes from the `CARTWHEEL_MODEL`
environment variable, which `.env` still sets to the HW6 model. The command
prints `score` (mean pass rate over the 10 development cases, one run each)
and `write_pass_5` (null here: no development case writes data) and saves the
result to `optimize/results/latest-development.json` and a dated copy. Read
`run_details` for every escalation case, not just the score: `final_reply`,
`failure_modes`, and `judge_reasons`.

## Keep rule

A change is kept only when all four hold:

1. `score` improves over the current best and `write_pass_5` does not drop.
2. The gain survives a second run of the same candidate (10 more charged
   runs). With 10 cases, one case is 0.10, and the frozen judge returns Pass
   or Fail at random on the same justified ticket in e-007 and e-008, so a
   single 0.10 gain is noise until repeated.
3. The gain is not carried by e-007 or e-008 alone. A change whose only
   effect is a different verdict on those two cases is reverted.
4. No under-escalation: on e-007 and e-008 the agent opens a ticket at least
   as often as the current best does, read from `judge_reasons` ("Code gate:
   no escalate_to_human call" means no ticket was opened). A score gain bought
   by never escalating is reverted.

Anything else is reverted to the last kept commit.

## Budget

150 evaluated case runs in total, tracked in
`optimize/state/search_budget.json`; `--search` charges each run and refuses a
run that would exceed the budget. Before the loop starts, reserve 40 runs for
the Part E confirmation run and a rerun of the selected candidate, so the loop
may use at most the remaining allowance minus 40. Each kept change costs 20
runs (the run and its confirmation); each reverted change costs 10.

Stop when two consecutive candidates are reverted, when the loop's allowance
is spent, or when the current best is 1.00 and the remaining variation is the
judge verdict on e-007/e-008 (the score cannot improve further).

## Log

Append one JSON object per attempt to `optimize/results/improve-loop.jsonl`
with `candidate`, `changed_layer`, `changed_files`, `rationale`,
`development_score`, `write_pass_5`, `decision`, `git_commit`, and
`result_file`. For a kept change, also record the confirmation run's score
and result file in `rationale`, and the ticket counts on e-007/e-008 for the
under-escalation check. Record the predicted effect in `rationale` before the
run, so the prediction can be compared with the result.
