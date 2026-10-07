# Review summary

Homework 4. One hundred and four Cartwheel conversations reviewed by hand, eight binary
failure modes, and 832 present-or-absent judgments written to Langfuse.

## The reviewed sample

One hundred and four distinct conversations. The first hundred were selected in four batches
by four different methods, so that no single sampling bias governs the set; a fifth batch of
four was added afterwards for Homework 5 and is marked as such.

| batch | n | method | why |
| --- | --- | --- | --- |
| b1-uniform | 15 | uniform random | coverage of the common case |
| b1-cluster | 15 | k-means representatives, 8 clusters over 5 trace features | coverage of the distinct conversation shapes |
| b2-store-override | 28 | complete slice, `applicable_policy = store_override` | every trace where an override failure is possible |
| b3-escalation-depth | 25 | bag-of-words neighbours of `support-0127` | more instances of a confirmed failure |
| b4-uniform | 17 | uniform random | saturation check |
| b5-escalation-hw5 | 4 | targeted search of the unreviewed traces | reach Homework 5's 30-label minimum for one mode |

Composition: 68 shopper, 22 merchant, 14 support. 68 coverage and 36 challenge scenarios.
Ten of the eleven intents in the store appear; only `dispute` is absent, and it has three
traces store-wide. By difficulty, 82 well specified, 8 false premise, 8 boundary, 3 missing
information, 2 correction across turns, 1 ambiguous.

The first hundred are the review proper. The final four were retrieved by a search for
escalations that no requirement in `SPEC.md` section 5 calls for, and were read in full
before being accepted, but they were chosen for one mode and should not be read as part of
the unbiased sample.

The sample is deliberately not representative. Batch 2 took every store-override trace in
the store, batch 1's cluster half over-sampled rare conversation shapes, and batch 3 was
retrieved for resembling a known failure. That is the point of the four methods, and it is
why the numbers below are sample fractions.

One retraction is recorded in the manifest. `b2-difficulty`, a 30-trace stratification
across the `difficulty` dimension, was replaced by the complete store-override slice after
the lecture's method was compared with the handout's. The retracted batch is kept under
`retracted_batches` rather than deleted.

## Open coding

154 open codes across 84 traces; 20 traces had no failure observed. 26 of the codes were
recorded with a one-click shortcut for `internal_detail_exposed` once that mode was settled
after batch 2, and carry `source: "shortcut"` so they stay distinguishable from the notes
typed out by hand. No scenario was flagged as defective.

## Final taxonomy and sample fractions

Counts are out of the 104 reviewed traces. They are sample fractions, not prevalence
estimates: the sampling above deliberately changed the composition of the set. Homework 5
estimates prevalence over the complete Module 1 store with a validated judge.

| failure mode | present | sample fraction | evaluator | requirement |
| --- | --- | --- | --- | --- |
| `internal_detail_exposed` | 64 | 64 of 104 | code check | RESP-1 |
| `unnecessary_escalation` | 30 | 30 of 104 | LLM judge | ESC-5 |
| `threshold_misapplied` | 23 | 23 of 104 | code check | ESC-1, ESC-5 |
| `irrelevant_policy_detail` | 22 | 22 of 104 | LLM judge | RESP-1 |
| `dispute_window_not_applied` | 11 | 11 of 104 | code check | ESC-5 |
| `date_interval_error` | 10 | 10 of 104 | LLM judge | RESP-3 |
| `store_override_missed` | 8 | 8 of 104 | code check | RESP-6 |
| `data_quality_surfaced` | 2 | 2 of 104 | LLM judge | RESP-3 |

`store_override_missed` shows most clearly why these cannot be read as rates. Every trace in
the store where the failure is possible is already in the sample, so 8 of 104 reviewed is
close to the whole population of such traces rather than 8 per cent of conversations.

Two modes are recorded but not submitted. `tone_inappropriate` has four traces and is
addressed by a prompt change rather than evaluation. `internal_field_exposed` was merged into
`internal_detail_exposed`, since one requirement covers both surfaces.

`data_quality_surfaced` ships with two confirmed positives rather than the three the handout
asks for. A search of all 250 traces established there is no third: of 15 catalogue-defect
scenarios, 6 users had already raised the defect themselves, 4 are merchants or support staff
asking about data they own, and 3 were handled correctly or concealed the defect instead of
surfacing it. The shortfall follows from two deliberate narrowings, not from a weak search.

## New modes in the final batch

Batch 4, 17 uniformly sampled traces, produced **no new consequential failure mode**.

Its six open codes resolved as: two confirmed `dispute_window_not_applied`, which had been
discovered late in batch 3 and had only one supporting note until then; one recorded a
shortcoming of the tools rather than the agent; one was an insufficiency with no requirement
behind it; and two were new patterns with a single instance each, "answered a different
question than the one asked" and "acted without confirming intent", each of which pairs with
one earlier trace and so falls below the three-trace minimum.

Two candidate patterns at two traces each is not "several new modes", so the taxonomy is
treated as stable and no further batch was reviewed.

The two confirmations matter more than the absences. `dispute_window_not_applied` was found
late, from a single note, inside a batch retrieved for a different mode. Two independent
instances in a uniform draw are what establish it as real rather than an artifact of where
the depth search happened to look.

## A taxonomy revision

`store_override_missed` was rewritten twice, and the second rewrite is the one worth
recording, because the method produced it rather than a reading of the spec.

It began as `store_override_not_checked`: *the agent states a return or refund window without
having retrieved the store's own policy page*. A process criterion. Testing close negatives
against it broke it twice.

First, four candidates were proposed and all four rejected. `support-0087` had the store's
page arrive in help-center results but never fetched it; `support-0038`, `0039` and `0079`
concerned stores with no policy page at all, where there is nothing to retrieve. The
reviewer ruled that checking is a binary act, which removed the ambiguity those four probed.

Then the framing itself failed. A process criterion over-fires: it would require a check on
every policy-shaped request and would fail a reply that reaches the right answer without
quoting a number. `support-0247` is that case, four words long, correct, and present under
the old wording. Meanwhile an outcome criterion under-fires, and contradicted the coding of
`support-0130`, where the agent quoted 30 days without checking and happened to be right.

The mode is now *the agent applies or cites the platform policy while a store override
governs the order*. `support-0130` becomes a close negative, since Paper Lantern Press has no
override and the platform window is the governing one. Nine of the original ten positives
survive.

The rewrite is grounded in a measurement rather than a judgment. Across all 20 stores, a
help-center query naming the store returns that store's policy page at rank 1 with a BM25
score of 10.2 to 15.2 when an override exists, and returns the platform documents at 2.07 or
below when none does. There is no overlap, so the absence of a store page from that search is
conclusive, and the cheap fix is a prompt change: put the store's name in the query. None of
the ten failing traces did.

Its known limit is recorded with it. The mode cannot distinguish an agent that checks from
one that always assumes the platform default, because on the 218 of 250 traces whose stores
have no override the two produce identical replies.

`unnecessary_escalation` was widened twice by the same mechanism, each time while testing a
close negative: once for a duplicate ticket on a case that already had one (`support-0100`),
and once for a ticket opened alongside a refund `issue_refund` had already queued
(`support-0211`).

## Specification revisions

Recorded in `analysis/report/spec_revisions.md` as they were found, and applied to `SPEC.md`
after labelling. Each is listed there with the annotation that motivated it.

| requirement | change | motivating annotation |
| --- | --- | --- |
| SCOPE-2 | product-usage advice is out of scope even for an item bought on Cartwheel | `support-0102` |
| ESC-1 | a queued refund is already with a human; no ticket alongside it | `support-0211`, `support-0046` |
| ESC-5 (new) | only ESC-1 to ESC-4 escalate; no duplicate tickets; no escalation once both windows have closed | `support-0100`, `support-0051` |
| RESP-1 | public title in user-facing text; no raw field names; user-actionable ids allowed | `support-0015` and 28 others |
| RESP-3 | rewritten around record ownership and who raised the defect | `support-0191`, `support-0192` |
| RESP-5 | covers commenting on the request, and directing rather than suggesting | `support-0246`, `support-0158` |
| RESP-6 (new) | establish the governing window by searching with the store's name | `support-0127` and 8 others |
| RESP-7 (new) | do not offer a capability the platform lacks, such as ticket urgency | `support-0100` |

The handout asks that a missing or ambiguous requirement be recorded before a failure label is
assigned. The recording happened on time, during Parts B and D. The edit to `SPEC.md` came
after labelling, which is out of order. No label changed as a result, because each mode's
definition was already written against the intended requirement; the label counts were
re-derived after the edit and are identical.

`spec_revisions.md` also records seven shortcomings of the tools rather than of the agent,
including that `search_help_center` has no relevance floor and returns three documents at
score 0.000 for a query matching nothing, and that there is no way to report a corrupted
record. These are kept out of the taxonomy because the failure modes describe agent
behaviour.

## Searching for more instances

Three searches, all treating their signal as retrieval rather than as a label.

**`internal_detail_exposed`**, recorded in `suggestions.json`. A filter for internal
identifiers in the final reply returned 8 candidates across 7 traces; 7 were accepted and 1
rejected. Two earlier passes were discarded first: one matched tokens anywhere in the trace
and highlighted hits in tool results the customer never sees, and one included Ticket, Refund
and Product ids, which the reviewer ruled user-facing. That ruling removed 7 candidates
before review and is now part of RESP-1.

**`dispute_window_not_applied`**, recorded as `manual_assignments`. A filter for
`escalate_to_human` on orders delivered more than 60 days ago returned 6, all accepted, taking
the mode from 3 positives to 9.

**`data_quality_surfaced`**, over all 250 traces including the 149 unreviewed. Ten candidates,
all rejected. A full-store negative result, and the basis for the two-positive shortfall.

## Labels

832 trace-mode pairs, every one decided, held in `analysis/state/labels/` as append-only
files and mirrored to Langfuse as one score per pair. Verified by reading the scores back and
comparing them field by field against the local labels: 832 scores, zero mismatches.

Provenance is recorded per label. 150 came from decisions already made in Part D, positives
and accepted close negatives. 305 were computed from deterministic criteria. 226 were absent
because the mode's trigger is impossible on that trace. The remainder were reviewed by hand,
and every trace was read again with all eight labels visible before being marked seen.

## Known limits

- The sample fractions are not prevalence estimates, for the reasons above.
- `store_override_missed` cannot separate an agent that checks from one that guesses the
  platform default, since both produce identical replies on the 218 of 250 traces with no
  override.
- `dispute_window_not_applied`'s defective-record exemption is deterministic only because
  Cartwheel enumerates its planted defects in `data_quality_cases`. In production that
  exemption becomes a judgment.
- Modes co-occur heavily. Five of the eight never fire alone, and `internal_detail_exposed`,
  present on 64 traces, covers every positive of three other modes on its own. That is a
  property of the agent, which usually fails in several ways at once, rather than a defect in
  the taxonomy: the merge test is whether one product change corrects both, and the fixes
  here stay distinct. `threshold_misapplied` was examined closely on this ground and kept.
- Part C was attempted and not completed. Raindrop Workshop was installed and wired without
  disturbing Langfuse, and five runs were captured, but tool spans require a cloud write key,
  so a local installation cannot show the tool calls the part is built around. Recorded in
  `analysis/report/workshop_notes.md`.

## Preparing for Homework 5

Homework 5 needs at least 30 present and 30 absent labels per mode. Absent labels are
comfortable everywhere, at 74 or more. Present labels are the constraint, and only two modes
clear it: `internal_detail_exposed` at 64 and `unnecessary_escalation` at 30, the latter
after the four traces in `b5-escalation-hw5`.

That is arithmetic rather than a gap in the review. A hundred traces and eight modes cannot
yield 30 positives each unless every mode fires on nearly a third of all conversations. The
handout's remedy is to generate scenarios targeting the short modes, which is Homework 5's
work.

Two modes cannot be topped up from the existing store at all. `store_override_missed` can
only occur on the 32 store-override traces, all of which are already reviewed, and
`data_quality_surfaced` has no third positive in 250 traces. Both need generated scenarios
rather than further searching.
