# Pending SPEC.md revisions

Recorded during Homework 4 open coding. The handout separates recording a missing or
ambiguous requirement from revising the specification: record on discovery, revise before
structured labeling. These are applied to `SPEC.md` after batch 4, not before.

## Ambiguous, RESP-1

> Cite the policy identifier for every claim derived from a policy document.

The requirement does not distinguish citing a source from exposing an internal handle, so a
reply reading "under Cartwheel refund policy (cw-refunds)" satisfies it. Seven of the twenty
batch 1 failures are this pattern. The tool result already carries `title` ("Cartwheel refund
policy") beside `policy_id`, so the public name is available at no cost.

Decision needed: require the public title in user-facing text, and keep the identifier for
internal records only.

Evidence: support-0015, 0078, 0129, 0130, 0171, 0207, 0233.

## Revised, RESP-3

Current text requires the agent to state inconsistent information, which makes disclosing a
corrupted catalog value compliant.

> **RESP-3 (revised).** State when required information is missing or inconsistent, rather
> than inventing a value. When the inconsistency is in a record the user owns, their own
> order or a merchant's own store, explain what is inconsistent and escalate. When it is in
> catalog or other shared data, do not surface the affected value; omit the item or ask for
> clarification.

This tightens the product-level data quality cases, whose manifest handling currently says
only "do not present the negative price as a valid offer". It diverges from
`dq-order-missing-delivery-date`, whose expected handling does not call for escalation;
resolve that when revising.

Evidence: support-0191, 0199.

## Gaps, no requirement covers these

**Over-escalation.** ESC-1 through ESC-4 name the cases that always go to a human. Nothing
bounds escalation beyond them, and ESC-4 ("unsure whether policy allows an action") is broad
enough to excuse almost any escalation. Needs a requirement that the agent resolves what it
can from the help center and the order record.
Evidence: support-0078, 0129, 0207.

**Store override not established before a window is quoted.** No requirement obliges the
agent to determine whether a store overrides the platform return window before asserting one.
The rule lives in `cw-store-overrides.md`, a policy document rather than the specification.

The cheap fix is a prompt or specification change rather than new tooling: require the agent to
include the store name in its help-center query. Measured over all 20 stores, a query naming the
store returns that store's policy page at rank 1 with a BM25 score of 10.2 to 15.2 when an
override exists, and returns the platform documents at 2.07 or below when none does. There is no
overlap, so an empty result is a conclusive finding of no override and no extra tool call is
needed. None of the ten failing traces named the store in any query.
Evidence: support-0127, 0128, 0129, 0130, 0209, 0210, 0212, 0213, 0215, 0245.

**Duplicate tickets and unsupported capabilities.** No requirement about opening a second
ticket for an open case, or about offering a capability the system lacks. Cartwheel has one
escalation path and a flat 24 hour SLA; there is no urgency flag on `escalate_to_human` or on
the escalations table.
Evidence: support-0100.

**Delivered but not received.** SPEC.md does not say whether an order marked delivered that
the user never received is a return, a refund, or a dispute, and no help-center page covers
it. In support-0256 the agent's three searches surfaced only `cw-returns`, so it applied the
30-day return window to an item the shopper never had, queued a $444 refund, and opened a
ticket as well. `cw-disputes` already says disputes are handled by a human and pause any
pending refund on the same order, which points to the intended route.

Decision needed: treat non-receipt of an order marked delivered as a dispute, escalated with
the delivery evidence, with no refund issued by the agent; and separate it from an order
still in transit, which is not yet missing.

Tool gap: `search_help_center` does not return `cw-disputes` for non-receipt queries.

Evidence: support-0256; contrast support-0056 (in transit), 0003 and 0005 (marked delivered,
escalated without a refund). Recorded during Homework 5.

## Gaps in the tool contracts

These are shortcomings of the evaluated system rather than agent behaviour, and are recorded
as such so the taxonomy can distinguish them.

**No relevance floor on `search_help_center`.** The contract promises results with scores and
says nothing about relevance, so a query matching no document returns three documents at
score 0.000 with `ok: true`. Absence is indistinguishable from a weak match, and unrelated
policies surface on ordinary queries.
Evidence: support-0039, 0083, 0089, 0199.

**`search_products` rejects an empty query even when filters are present.** The contract
specifies `invalid_argument` for an empty query, so "everything under $25 at this store" has
no expressible form. The tool is compliant; the requirement is the problem.
Evidence: support-0138.

**No store lookup tool.** TOOL-1 through TOOL-9 contain no way to ask whether a store exists.
The only existence signal is the `not_found` error from `search_products`'s optional `store`
filter, which nothing instructs the agent to use.
Evidence: support-0094.

**No wildcard or browse query for `search_products`.** A `"*"` query returns nothing, because
matching is literal substring matching on every whitespace token. There is no way to ask the
catalogue for everything in a store.
Evidence: support-0089, 0199.

**No way to report a corrupted record.** When the agent finds a defective catalogue or order
record it can only tell the user, or open a support ticket addressed to the user's own case.
There is no background channel for reporting a data defect, so the same broken record will
reach the next customer.
Evidence: support-0192.
