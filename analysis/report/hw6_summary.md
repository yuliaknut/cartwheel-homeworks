# Homework 6 summary

Fifteen evaluation cases from two Homework 4 failure modes, run five times each in fresh Harbor
containers, classified from their baseline, and gated in GitHub Actions on pull request #1 of
`yuliaknut/cartwheel-homeworks`. Agent model `gpt-5.5` throughout; the only judge is the frozen
HW5 judge `unnecessary_escalation-v2` on `gpt-4o-mini`.

## Result

| Deliverable | Where | Outcome |
| --- | --- | --- |
| 15 cases, 2 modes | `eval_cases/cases.jsonl` | 9 `unnecessary_escalation`, 6 `internal_detail_exposed` |
| Baseline, 5 runs each | `.harbor/jobs/hw6-baseline-e-003`, `hw6-baseline-rest` (local) | 6 capability, 9 regression; 0 infrastructure errors in 75 trials |
| pass@k, pass^k, CI rule | `tests/eval/passk.py` | the three handout tests pass |
| CI workflow | `.github/workflows/evals.yml` | every case five times, summary and artifact kept with `if: always()` |
| Two CI runs, one PR | `ci-runs.json` | regression run blocked the selected case; revert run restored it but was blocked by judge noise |
| 15-run capability analysis | `eval_results/e-003-15.json` | pass@1 0.40 at n = 5, 10 and 15 |

## The cases

| Case | Mode | Based on | Kind | Baseline |
| --- | --- | --- | --- | ---: |
| e-001 | unnecessary_escalation | support-0054, refund past both windows | capability | 0.0 |
| e-002 | unnecessary_escalation | support-0028, past-window non-receipt | capability | 0.2 |
| e-003 | unnecessary_escalation | support-0045, ticket beside a queued refund | capability | 0.2 |
| e-004 | unnecessary_escalation | support-0127, merchant past Juniper's 14-day window | capability | 0.0 |
| e-006 | unnecessary_escalation | support-0169, cancel a shipped order | capability | 0.0 |
| e-007 | unnecessary_escalation | support-0184, broken record (justified ticket) | regression | 1.0 |
| e-008 | unnecessary_escalation | support-0195, negative listed price (justified) | capability | 0.4 |
| e-009 | unnecessary_escalation | support-0252, close account (justified) | regression | 1.0 |
| e-010 | unnecessary_escalation | support-0257, sparking lamp (justified) | regression | 1.0 |
| e-011 | internal_detail_exposed | support-0083, `cw-` policy id | regression | 1.0 |
| e-012 | internal_detail_exposed | support-0087, `store-…-policy` id | regression | 1.0 |
| e-013 | internal_detail_exposed | support-0162, `refund_eligible` field | regression | 1.0 |
| e-014 | internal_detail_exposed | support-0093, store id | regression | 1.0 |
| e-015 | internal_detail_exposed | support-0138, talk about an id (edge, expected pass) | regression | 1.0 |
| e-016 | internal_detail_exposed | support-0196, raw code value on broken data (edge) | regression | 1.0 |

e-005 (support-0131) was dropped as a near-twin of e-006: same situation, same correct answer,
only the role and request differed. The numbering gap is deliberate.

Escalation sources were filtered to train/dev conversations with an `escalate_to_human` call,
where the frozen v2 judge agreed with the human label and which were not examples inside the judge
prompt. Every case expects judge `pass`: a case states the correct behavior, the source label only
predicts the baseline. Internal-detail cases cover one of each observed leak type plus two edge
cases, scored by three `reply_not_matches` rules: no underscore-separated word, no policy id
(`cw-…`, `store-…-policy`), no "<word> id <number>" other than order, refund, ticket, product,
request or listing ids.

## Groundwork the handout did not spell out

- **Judge input.** The supplied adapter dropped tool names, the session header and the code gate,
  so the HW5 metrics would not have described the HW6 judge. `harbor_adapter/judge_input.py`
  rebuilds the HW5 input; 134 of 134 HW5 inputs re-render byte-identical, and the live input in
  the pilot matched. The verdict parser is strict as in HW5: a malformed verdict raises and the
  trial has no reward.
- **Judge reasoning kept.** The verifier now prints the judge's critique and verdict into
  `verifier/test-stdout.txt`. Prompt, model, input and parser are unchanged.
- **The second mode changed.** `threshold_misapplied` was the first choice. Reviewing its
  labels showed the mode is about the threshold being invoked where it is irrelevant, which depends
  on the user's request and on earlier failures (support-0246: refund requested, never issued).
  That is a relevance judgment, not an exact fact, so it was dropped for a code check. Its
  definition was still revised and the related labels updated.
- **Prompt fix before the baseline.** `internal_detail_exposed` leaked every time the agent cited
  a policy because the system prompt said "Cite the policy id (for example cw-returns)". The line
  was replaced (cite public titles; no raw field names, codes or internal ids) before any baseline
  run, so these cases are regression guards. Prompt version `e52639f98fc0`.
- **Course scripts.** `summary.py` and `analysis.py` read `trial_results` from the job's
  `result.json`; Harbor 0.21 to 0.24 never write it to disk (each trial has its own file). One
  loader now reads the per-trial files in `finished_at` order; the course's tests are untouched and
  one test with the real layout was added. A classmate's repo patched the same bug unreported.

## The taxonomy, seen from here

`unnecessary_escalation` is a symptom mode (a ticket that should not exist); several other HW4
modes were causes of the same tickets (`dispute_window_not_applied` was a near-subset). Building
cases exposed it: a cause-mode case fails exactly when the symptom case does. Practical split
adopted: monitor the symptom, fix the causes, and pick a second mode whose observable does not
overlap the judge's.

## CI

Two jobs on every pull-request event. **Offline checks** run the repository's tests with no model
calls; six `test_m2_*` tests are deselected because they expect the course's demo state, which
HW4 and HW5 replaced. **Harbor evaluations** install `harbor==0.23.0`, export the classified tasks,
run each five times two at a time (`--n-concurrent 2`, to stay inside the runner's memory),
summarize with `--expected-attempts 5`, and upload `.harbor/jobs/hw6-evals`, both with
`if: always()`. Checkout uses `lfs: false` because the course's LFS patches were never pushed.
`CARTWHEEL_MODEL` is a repository variable; `OPENAI_API_KEY` is a repository secret serving
both the agent and the judge. No job or task file contained the key value (0 of 1,424 scanned).
While the PR is open every push starts a paid run unless its commit says `[skip ci]`.

## Part D

| | Regression run | Revert run |
| --- | --- | --- |
| Commit | `9a92a3c`, old "Cite the policy id" line reinstated | `e2dde30`, exact revert |
| Run | [37833288067](https://github.com/yuliaknut/cartwheel-homeworks/actions/runs/37833288067) | [37839280419](https://github.com/yuliaknut/cartwheel-homeworks/actions/runs/37839280419) |
| e-011 (selected) | 0/5, block | 5/5, pass |
| e-012, e-013 | 0/5, block | 5/5, pass |
| Other blocks | e-010 3/5 + 1 infra | e-007 3/5 |
| Job | failure | failure |

The regression was caught and cleared. Both runs also blocked on a judge-scored regression case
for reasons that were the judge's, not the agent's: in run 1 the judge invented a second
"Refund approval needed" ticket for e-010 and returned one malformed verdict; in run 2 it passed
two and failed two near-identical "verify the timeline for order 8001" tickets in e-007. The
second run's failure was kept as evidence, not rerun.

## Part E

e-003, 15 runs: 6 passed.

| Runs observed | pass@1 | pass@3 | pass@5 | pass@10 | pass@15 |
| --- | ---: | ---: | ---: | ---: | ---: |
| n = 5 | 0.400 | 0.900 | 1.000 | | |
| n = 10 | 0.400 | 0.833 | 0.976 | | |
| n = 15 | 0.400 | 0.815 | 0.958 | 1.000 | 1.000 |

Reading: stable. pass@1 never moves, and pass@3 and pass@5 move 0.018 between 10 and 15 runs
after larger moves between 5 and 10. Stable is not precise: 6 of 15 has a 95% interval of about
0.20 to 0.64. Across every e-003 observation (baseline, both CI runs, these 15) it is 12 of 30.
One of the six passes was a judge false pass (no `issue_refund`, a "Refund review needed"
ticket that v2's own rules call a Fail); by the human standard it is 5 of 15, and that one
evaluator error moves pass@1 further than the extra five runs did.

## Findings

- **A blocking gate needs a near-deterministic evaluator.** The six code-checked cases never
  flickered. The judge-scored regression cases (e-007, e-010) each blocked once on judge error,
  and e-008's 0.4 baseline is mostly judge variance. With nine regression cases, even 99% per-run
  reliability gives 0.99^45 ≈ 0.64 that a CI run is fully green.
- **Evaluator error can outweigh sampling error** (Part E above).
- **Boundary to clarify if the judge is ever revised:** a ticket asking a human to review a broken
  listing, framed as "honor the negative price" (support-0195), and a ticket for an internally
  inconsistent record (support-0184). v2 rules both ways on the same input.
- **For HW8:** the prompt's Escalation section ("an action above your authority (for example a
  refund above the auto-approval threshold), call escalate_to_human") is the likely root of the
  tickets beside queued refunds. After the internal-detail fix, e-014's replies stopped naming
  the store at all ("all listed by the same store"), possibly because search results only carry
  the id.

## Limits

- Cases cover over-escalation only. The gate scores "no escalation" as Pass, so an agent that
  stopped escalating altogether would pass every escalation case; under-escalation was not
  observed in HW4 and is left to error analysis after HW8's changes.
- The internal-detail check reads the final reply only, matches patterns rather than meaning, and
  allows exactly the id kinds listed; an id written out in words would pass.
- Every input replays a conversation reviewed in HW4 or HW6; none were authored. Each
  classification rests on five baseline runs.
- The e-003 pilot ran before the upstream merge; the merge changed only usage accounting.

## Artifacts

`eval_cases/cases.jsonl`, `tests/eval/passk.py`, `.github/workflows/evals.yml`, `ci-runs.json`,
`eval_results/e-003-15.json`; adapter changes in `harbor_adapter/` and `replay/rollout.py`;
revised definitions in `analysis/state/patterns.json`; e-008's five baseline runs as a review page
in `analysis/hw6_review/`. Pull request: https://github.com/yuliaknut/cartwheel-homeworks/pull/1
