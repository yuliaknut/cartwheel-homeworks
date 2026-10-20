# HW8 notes: unnecessary escalation

Working notes for the video and the record. Interpretations are the
student's; numbers come from the committed result files named in each line.
Written through Part F and the extra gpt-5.5 run.

## Chronology

- **Models** (`optimize/config.json`, price date 2026-10-14): development
  claude-haiku-5-5; comparison gpt-6.1-sol, claude-opus-5-5,
  claude-haiku-5-5; GEPA reflection claude-opus-5-5.
- **Pre-baseline fix (applies to every model).** The model check found
  claude-opus-5-5 refusing the Cartwheel prompt outright (stop reason
  `refusal`, category reasoning_extraction) and LiteLLM returning an empty
  reply. The trigger was the line "You MUST explain your reasoning in plain
  text before every tool call"; reworded to "Before each tool call, tell the
  user in one short sentence what you are about to check and why." A silent
  run passed every case (no ticket means the judge gate passes; the check
  cases only forbid patterns), so `replay/__main__.py` now fails a run with
  an empty final reply (`empty_reply`). Both changes were made before the
  split so they are part of the starting version.
- **Part A.** Failure mode `unnecessary_escalation` (ESC-5), prevalence 0.18
  = 45 of 250 HW3 conversations by human label; those traces were produced
  by gpt-5.5. Examples support-0054, 0127, 0169. Stated risks up front: an
  optimizer could score 100% by never escalating (e-007, e-008 on the
  development split and e-003, e-009, e-010 on the test split are
  justified-ticket cases that the scorer passes when no ticket is opened),
  and the development cases might carry no escalation risk at all.
- **Part B.** Starting version da22501 on Haiku: 0.90. The one failure was
  e-008, a justified ticket the frozen judge called Fail. Ruling: offering a
  ticket and asking the user is not a failure; only an unprompted ticket on a
  settled case counts.
- **Part C.** Prompt rewrite of the Escalation section (1.00), tool
  description for `escalate_to_human` (0.90), and the world date injected
  into the session context (1.00). Every score movement was e-008's judge
  verdict on the same ticket. All three kept on behavior, not score: the
  date injection removed the agent's "what is today's date?" questions on
  e-001 and gave a clean ESC-5 reply.
- **Part D.** GEPA with `--max-runs 60`: 52 charged runs, 7 reflection
  rounds, 0 proposals accepted (six tied the parent on the minibatch, one
  lost on a judge Fail on e-007's justified ticket); best candidate = the
  seed. Improve loop closed at the baseline under the skill's "score cannot
  improve further" condition with no candidate charged. Student's
  `optimize/program.md` written afterwards as the optional exercise. Adapter
  guard added so a GEPA proposal cannot drop `{world_date}`.
- **Part E.** Final = the three Part C changes, commit cefec04, method
  manual. Confirmation run 1.00 with no ticket on any escalation case,
  including e-008 for the first time: this 1.00 is the no-escalation gate
  passing both justified cases, not judge luck.
- **Part F.** Frontier on the test split (e-002, e-003, e-009, e-010,
  e-015; one run each): starting version on gpt-6.1-sol 0.80 ($0.90 per 100
  conversations, dominated), on claude-opus-5-5 1.00 ($7.56, dominated), on
  claude-haiku-5-5 0.80 ($0.24, frontier); final version on claude-haiku-5-5
  1.00 ($0.30, frontier). Per case: sol opened an unprompted ticket on e-002
  (an order-status question; the target failure); Opus opened none on
  e-002/e-003 and the justified ones on e-009/e-010; starting Haiku opened a
  duplicate ticket on top of the queued e-003 refund (judge Fail); final
  Haiku queued the e-003 refund with no ticket (fixed) but opened NO ticket
  on e-009 (account closure, offered one) or e-010 (sparking lamp, offered a
  refund), both justified and both passed by the no-escalation gate.
- **Extra run, outside the handout** (student's request): final version on
  gpt-5.5, the model Cartwheel ran on in HW3 to HW7, three rollouts per test
  case through `python -m replay`. e-002 3/3 no ticket (HW6 baseline on the
  starting code: 1/5); e-003 3/3 refund queued, no duplicate ticket (HW6:
  1/5); e-009 3/3 ticket opened (HW6: 5/5); e-010 2/3 ticket opened, one run
  issued a refund instead (HW6: 5/5); e-015 3/3. Summary in
  `optimize/results/extra-final-gpt-5.5.json`.

## Note 1: this failure mode was a poor target for automated search

The search methods need two things: a development score that fails, and a
signal they can trust. This setup had neither.

- Haiku never opened an unprompted ticket on a settled development case in
  86 runs (Parts B to E). The failure that gave the 0.18 prevalence came
  from gpt-5.5, and the Part A model check reproduced it on gpt-6.1-sol
  (e-001 ticket). On the development model the base rate was zero before any
  change.
- The scorer passes a never-escalating agent, so "fewer tickets" and "fewer
  unnecessary tickets" are indistinguishable from the score alone.
- The frozen HW5 judge (`unnecessary_escalation-v2`, kept at v2 after v3
  declined, under the handout's three-iteration limit) returns Pass or Fail
  at random on the same justified ticket: e-008 Fail 3 / Pass 4, e-007 Fail
  1 / Pass 1 across identical behavior. HW5 measured one verdict per labeled
  trace and could not see this within-trace variance. Its only HW8 effect is
  to cap the development score at "0.90 or 1.00 depending on the toss".

GEPA therefore spent its budget proposing reasonable, off-target edits
(friendlier status wording, "never show the policy id", citing policies by
title) and selecting the seed. The general lesson: choose a failure mode
whose base rate on the development model is high enough to measure, and
check the scorer's blind spots before pointing an optimizer at it.

## Note 2: the fixes work where the failure lives, and the prompt layer over-corrected

On gpt-5.5, the model that produced the 0.18 prevalence, the final
configuration removed the unnecessary tickets on both target test cases
(e-002 and e-003 went from 1/5 to 3/3) and kept the justified account-change
ticket (e-009, 3/3). Three rollouts per case, so directional, but the
baseline rates were 0.2 and the final rates 1.0 on the same cases.

The cost of the rewrite shows on the justified cases. The starting prompt
said "Account changes of any kind go to a human: call escalate_to_human
rather than refusing them" and "when you are unsure... escalate". The final
prompt says "only for" three categories and "everything you can settle from
the help center and the order record, you settle yourself". Haiku took that
literally on the test split: it found an account policy and declined e-009,
and treated the sparking lamp in e-010 as a refund; gpt-5.5 slipped once on
e-010. The development split showed the drift early (e-007 offering a ticket
instead of opening one), read under the "offering is fine" ruling. A user
asking to delete their data, or reporting a fire hazard, is where that
ruling stops holding. Of the three layers, the world-date injection is the
one that generalizes by construction (it changes what the model sees, not
how it is told to behave); the prompt wording is a hypothesis about one
model's reading and needs justified-ticket cases next to the target cases
before it is tightened again.

The frontier cannot see any of this: the 0.80 to 1.00 on Haiku is one real
fix (e-003) plus two gated passes on justified cases. The final configuration
stays as saved, per the handout; the regression is recorded here for the
next test set.

## Note 3: the model change alone moved the development score from 0.64 to 0.90

Same starting code, different model, same ten development cases:

| | gpt-5.5, HW6 baseline (5 trials per case) | claude-haiku-5-5, HW8 Part B (1 run per case) |
|---|---|---|
| e-001, e-004, e-006 (settled; a ticket is the failure) | 0/5, 0/5, 0/5; every failure an unprompted "exception request" ticket | pass, pass, pass; no ticket |
| e-007 (justified) | 5/5 | pass (offered, no ticket) |
| e-008 (justified) | 2/5; all five opened the ticket, judge split 2/3 | fail (ticket, judge Fail) |
| e-011 to e-016 (check cases) | 5/5 each | pass each |
| development pass rate | 32/50 = 0.64 | 9/10 = 0.90 |

The entire gain sits on the three target cases. Caveats: HW6 ran through
the Harbor adapter (same judge input, gate and checks; parity verified
offline), 5 trials against 1, and the pre-baseline narration rewording sits
between the two code states. Part F repeats the comparison on the test split
with gpt-6.1-sol, claude-opus-5-5 and claude-haiku-5-5 (configurations 1 to
3): sol 0.80 (unnecessary ticket on e-002), Opus 1.00, Haiku 0.80
(duplicate ticket on e-003). Haiku's starting-version failure on the test
split is a different shape from sol's: a ticket on top of a queued refund
rather than a ticket instead of a settled answer.

## Costs

Every paid run is itemised in the course progress notes. HW8 total through
Part E: about $0.67 (Part A checks and diagnostics ~$0.17, Parts B to C
~$0.08, GEPA smoke $0.05, GEPA search $0.35, Part E $0.02). Part F frontier $0.46 (Opus $0.38 of it). Extra gpt-5.5 run
$1.15 at an assumed $5 / $0.50 cached / $30 per million (the estimate was
$0.80; gpt-5.5 used about twice the tokens per run of the HW6 pilot). HW8
total about $2.29.
