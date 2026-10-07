# Homework 5 summary

One LLM judge for `unnecessary_escalation`: does every ticket Cartwheel's agent opens with
`escalate_to_human` need to exist? The final judge is **`unnecessary_escalation-v2`** on
`gpt-4o-mini`, run behind a code gate.

## Result

Final judge, test split, judge-only metrics over the 27 test conversations that contain a ticket
(Pass is the positive class, 95% Wilson intervals):

| | Human Pass | Human Fail |
| --- | ---: | ---: |
| Judge Pass | TP 6 | FP 3 |
| Judge Fail | FN 3 | TN 15 |

- **TPR 0.67 [0.35, 0.88]**: 6 of 9 required tickets recognised.
- **TNR 0.83 [0.61, 0.94]**: 15 of 18 unnecessary tickets caught.
- Class counts: the test split holds 35 Pass and 18 Fail; the judge scored the 27 with a ticket
  (9 Pass, 18 Fail) and the code gate passed the other 26, all correctly.
- Gate plus judge over the whole split: TPR 0.91, TNR 0.83. The TPR is lifted by the 26 Passes
  the gate gets for free and is not a measure of the judge.

**This test score is optimistic.** v2 was chosen after both v1 and v2 had been run on test (see
"How v2 became the judge"). The one result produced exactly by the handout's procedure is v1's:
TPR 0.56 [0.27, 0.81], TNR 0.72 [0.49, 0.88]. Both are kept in `analysis/report/`.

**An unbiased estimate followed.** On a blind held-out set built after v2 was frozen, v2 scored
**TPR 0.93 [0.69, 0.99], TNR 0.86 [0.49, 0.97]** over 21 judged conversations. See "Held-out
evaluation" for how it was built and why it is probably easier than the test split.

## Would I use it

The student's assessment, after reviewing v2's six test disagreements: *"The v2 judge did really
well actually. The surfaced disagreements are pretty arguable for the most part."*

Read against the numbers: on the cases it was built for it agrees with a careful human most of
the time, and where it does not, the cases are ones a second human could also dispute. The
intervals are what limit the claim. With 9 required tickets in test, the true TPR could sit
anywhere from about a third to nearly nine in ten. Suitable for flagging tickets for a human to
look at; not yet established well enough to act on alone, or to estimate a failure rate from
without a wide margin (the correction for judge error divides by TPR + TNR − 1 = 0.50).

The blind held-out result supports the verdict more firmly than the test score could: 13 of 14
required tickets and 6 of 7 unnecessary ones judged correctly on conversations nobody had tuned
against. Read together, the two sets say v2 is reliable on clear-cut escalations and weaker on
genuinely borderline ones, which is where the test split's arguable disagreements sit.

## The failure mode and its labels

The definition and boundary live in `analysis/state/patterns.json`. Part A sharpened them on
traces rather than in the abstract, and four rulings were added: a required ticket filed under a
misstated reason is still required; a package marked delivered that never arrived is a dispute,
so its ticket is required even beside a queued refund; a ticket that only duplicates a refund
review the user asked for is unnecessary; an order still in transit has not gone missing. The
trace citations were then stripped from the boundary so the prompt could be drafted from it
without carrying identifiable traces. One specification gap was recorded in
`spec_revisions.md`: SPEC.md never says what "delivered but not received" is.

**Labels.** HW4 left 30 Fails but only 6 traces where an escalation was justified; 68 of the
Passes were conversations with no ticket at all, which any judge gets right. Two batches fixed
the boundary:

| batch | n | what |
| --- | ---: | --- |
| `b6-escalation-boundary` | 29 | every unlabeled trace in the store that called `escalate_to_human` |
| `b7-escalation-generated` | 10 | new scenarios where a ticket is genuinely required (account changes, misdelivery, safety, counterfeit, a merchant's wrong return, a two-turn status-then-phone-change), grounded in unused users and orders, critic-reviewed, approved before the run |

Close variants were deduplicated (`analysis/state/hw5_exclusions.json`): nine conversations on
the same planted broken record or product were excluded, keeping one per group, and labels were
kept. Final eligible set: **134 labels, 88 Pass and 46 Fail; 68 contain a ticket (22 Pass,
46 Fail).** Two HW4 defaults on escalated traces were found wrong and corrected (a refund-review
duplicate, a ticket opened on the agent's own date error), and one label was corrected during
development (an accidental double purchase is a refund request, not a duplicate charge).

## Inputs, gate, split

`analysis/run_judges.py` builds one input per labeled conversation in
`analysis/state/hw5_trace_inputs.json`: the whole conversation, with the tool name written into
each tool message (the course renderer drops it, which would hide which call was the ticket),
and a header with the user's role and the world date (2026-07-01), which the judge needs for any
window question. No labels, notes, scenario plans, or answer keys.

**Code gate.** A conversation with no `escalate_to_human` call is a Pass by definition, so code
decides it and the model is never called. The headline metrics count only the conversations the
model judged; the 26 gated Passes per split would otherwise inflate TPR.

**Split** (`split_labels`, 20/40/40, seed 7), shown as all / with a ticket:

| split | Pass | Fail | with a ticket: Pass / Fail |
| --- | ---: | ---: | --- |
| train | 18 | 9 | 4 / 9 |
| dev | 35 | 19 | 9 / 19 |
| test | 35 | 18 | 9 / 18 |

The split was run once, then re-run before any judge existed after the first draw put two
variants of one broken order on opposite sides of train and test; one of them was excluded.

## How v2 became the judge

| version | split | TP | FN | TN | FP | TPR [95% CI] | TNR [95% CI] |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| v0 | dev | 9 | 0 | 9 | 10 | 1.00 [0.70, 1.00] | 0.47 [0.27, 0.68] |
| v1 | dev | 7 | 2 | 18 | 1 | 0.78 [0.45, 0.94] | 0.95 [0.75, 0.99] |
| v2 | dev | 5 | 4 | 14 | 5 | 0.56 [0.27, 0.81] | 0.74 [0.51, 0.88] |
| v1 | test | 5 | 4 | 13 | 5 | 0.56 [0.27, 0.81] | 0.72 [0.49, 0.88] |
| **v2** | **test** | **6** | **3** | **15** | **3** | **0.67 [0.35, 0.88]** | **0.83 [0.61, 0.94]** |

**v0** (`prompts/unnecessary_escalation-v0.txt`): the definition, a facts sheet that leaves out
two help-centre pages contradicting the specification, and three training examples. It passed
every justified ticket and half of the unnecessary ones. All nine disagreements were the judge
crediting the agent's own story ("the refund needs human review", "the user disputes
eligibility"), plus one rule the prompt had omitted: once both the return and the dispute
windows have closed, nobody can grant a remedy.

**v1** separated evidence from narration (the user's account of events counts, the agent's
reason for a ticket does not), defined a dispute narrowly as a charge problem, reversed the
burden (a ticket is required only if the judge can name the requirement and the facts that
trigger it), added a procedure and two more examples. It caught almost every unnecessary ticket
and missed some justified ones.

**v2** answered v1's three remaining disagreements (a catalogue defect, a merchant's mediation
request, a damaged item read as a dispute) with separate requirements for wrong records and for
merchant–shopper conflicts, and a procedural question grounded in policy rather than tooling:
what does this ticket ask a human to do that the policy assigns to a human? The student rejected
the first framing, "what can a human do that no tool can", because a missing tool also describes
requests the platform does not offer at all, which the agent should decline. On dev, v2 scored
worse than v1.

One process failure belongs in the record. A first v2 draft was run before the student had read
it; its results were deleted at the student's request and the draft set aside, and the v2 above
was rebuilt from v1's evidence alone. The deleted run had been seen, so v2's design cannot be
called fully blind to it.

**Why revising stopped.** Two revisions is the handout's limit, and v2 gave a second reason: its
added rules did not move the cases they targeted and broke cases governed by rules that had not
changed. More detail was making `gpt-4o-mini` less consistent, not more accurate.

**Freezing.** v1 was chosen on dev, frozen and tested once, as the handout prescribes. The first
attempt returned one malformed verdict ("Not found") out of 27; that batch was re-sampled once
with DocETL's cache bypassed, without inspecting any verdict. The student then asked whether the
dev ranking held, and v2 was frozen and tested as an experiment. **It reversed:** v2 beat v1 on
test after losing to it on dev. On review of v2's test disagreements the student chose v2 as the
judge, and v1 is marked superseded.

That reversal is the main lesson. With 9 required tickets per split, a difference of a few traces
between versions is within sampling noise, and v1's dev lead was partly fitted to the very dev
traces its revision was built from. Dev could not rank these versions, and the test score of
whichever version is picked after looking at test stops being an unbiased estimate.

## Held-out evaluation

After HW5, 30 new scenarios were generated to give v2 a test it could not have been chosen on
(`scenarios/hw5_heldout_scenarios.jsonl`, `support-0261` to `support-0290`, batch
`b8-escalation-heldout`). The method followed the HW3 skill: tuples grounded in a fresh seed,
using users and orders no earlier scenario or labeled trace had used (merchants and support
staff excepted, since all of them were already in use); one generator call per conversation; a
critic pass that changed 7; the validator; the student's review of all 30; then a reseed and one
run on `gpt-5.5`.

The design aimed for roughly half warranted escalations (account changes, misdelivery, wrong or
counterfeit items, an unauthorized order, double billing, a safety hazard, a refund that never
arrived, merchant–shopper conflicts) and half unwarranted ones (refunds over $100, refunds past
the platform or store window, cancelling delivered or shipped orders, orders still in transit,
both windows closed, a goodwill refund, a price adjustment and an express-shipping upgrade the
platform does not offer). The set was labeled blind: no judge had seen it, the planned
expectations were removed from the scenario file and kept aside, every scenario carried the same
group and a neutral note, and the batch order was shuffled (seed 8).

| | n | Pass | Fail |
| --- | ---: | ---: | ---: |
| all 30 | 30 | 23 | 7 |
| with a ticket (judged) | 21 | 14 | 7 |
| no ticket (gated) | 9 | 9 | |

The agent escalated less often, or more justifiably, than its HW3 traces suggested, so the Fail
side came out at 7 rather than the planned half.

| | Human Pass | Human Fail |
| --- | ---: | ---: |
| Judge Pass | TP 13 | FP 1 |
| Judge Fail | FN 1 | TN 6 |

TPR 0.93 [0.69, 0.99], TNR 0.86 [0.49, 0.97]. Gate plus judge over all 30: TPR 0.96, TNR 0.86.
One judge output was malformed on the first attempt; that batch was re-sampled once with
DocETL's cache bypassed, without inspecting verdicts, as on the test run. Across test and
held-out, 2 of 48 judge calls returned an unusable verdict on the first attempt.

**What it measures.** This is the first estimate of v2 that no choice depended on, and TPR rests
on 14 required tickets rather than 9. It is also probably an easier set than the test split: the
scenarios were designed around clear categories on fresh, undamaged records, while the test split
came from HW3's planted damaged records, subtle refund cases, and conversations the reviewer
judged arguable. The two results describe different parts of the judge's range rather than
contradicting each other. TNR rests on 7 Fails and its interval is correspondingly wide.

## Limits

- **Small Pass class.** 22 justified tickets in total, 9 per evaluation split. Every TPR here
  has an interval roughly half the scale wide. `validate-evaluator` asks for about 50 per class.
- **Selection on test.** The final judge was chosen with test results in view. The blind
  held-out set gives an unbiased figure, but on a probably easier, more clear-cut distribution,
  and with only 7 Fails.
- **A weak, inconsistent judge model.** `gpt-4o-mini` contradicted its own critique on rules that
  were stated plainly, and returned one malformed verdict in 27. The model is fixed by the
  handout; a stronger model is the first lever outside it.
- **Categories came from the whole pool.** The definition was written from error analysis over
  all labeled traces before the split, so test measures new instances of known situations, not
  situations nobody has seen.
- **The refund-duplicate case is checkable in code.** A ticket opened after `issue_refund`
  returned `queued_for_approval` is one of the commonest failures and needs no model; moving it
  into the gate would leave the judge only the interpretive cases.

## Artifacts

| what | where |
| --- | --- |
| HW5 labels (Pass = 1) | `analysis/state/hw5_labels/unnecessary_escalation.jsonl` |
| exclusions, split, inputs | `analysis/state/hw5_exclusions.json`, `splits.json`, `hw5_trace_inputs.json` |
| prompts | `analysis/prompts/unnecessary_escalation-v0.txt`, `-v1.txt`, `-v2.txt` |
| judge versions, predictions, critiques | `analysis/state/judges/unnecessary_escalation-v*.json` |
| code | `analysis/run_judges.py` (export, inputs, split, dev, freeze, test, heldout; the gate) |
| metrics | `analysis/report/dev-*.json`, `test-unnecessary_escalation-v1.json`, `test-unnecessary_escalation-v2.json`, `heldout-unnecessary_escalation-v2.json` |
| held-out set | `scenarios/hw5_heldout_scenarios.jsonl`, `hw5-heldout-results.jsonl`, `analysis/state/hw5_heldout_inputs.json` |
| review | `analysis/hw5_review/` (page, adapter, decisions per version) |
| generated scenarios | `scenarios/hw5_escalation_scenarios.jsonl`, `hw5-escalation-results.jsonl` |

Recompute the final test metrics from saved predictions, without a model call:

```bash
uv run python -c "
import json; from analysis.run_judges import _confusion, _escalated_ids, _read_json, STATE_DIR
ids = sorted(_escalated_ids(_read_json(STATE_DIR / 'splits.json')['unnecessary_escalation']['test']))
print(_confusion('unnecessary_escalation-v2', ids, 'unnecessary_escalation'))"
```
