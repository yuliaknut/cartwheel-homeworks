# Homework 7: monitoring `unnecessary_escalation`

The monitor runs the frozen Homework 5 judge `unnecessary_escalation-v2` (gpt-4o-mini, behind the Homework 5 code gate: a conversation with no `escalate_to_human` call passes without a model call) over two runs of the same 50 scenarios on `gpt-5.5`. Settings are in `config.json`: a 20% random sample, risk groups `policy_lookup` and `escalated`, and a threshold of 0.25 chosen before any judge results.

| period | conversations | random flagged | raw | corrected | 95% interval | crossed 0.25 | risk flagged |
|---|---|---|---|---|---|---|---|
| before (HW3 run, prompt `1b6ab97b18c5`) | 50 | 1 of 10 | 0.10 | 0.019 | 0.00 to 0.33 | no | 9 of 28 |
| after (new run, prompt `e52639f98fc0`) | 50 | 1 of 10 | 0.10 | 0.019 | 0.00 to 0.33 | no | 9 of 29 |

Judge failure sensitivity 0.83 and pass specificity 0.91 (HW5 test split, 53 records). Full records: `history.jsonl`; chart: `prevalence.svg`.

## Answers

**1. Did the corrected failure estimate move between the two periods?**
No. The corrected estimate is 0.019 in both periods.

**2. Do the intervals support a conclusion, or is the result uncertain?**
We can't be very confident with this sample: both intervals run from 0.00 to 0.33, and the 0.25 threshold sits inside them. Within that imperfect sample, the two periods are consistent with each other.

**3. What did the risk groups reveal that the random estimate did not?**
The risk groups surfaced 18 flagged conversations against the random sample's one per period. On review, 16 were real unnecessary escalations, and they show a sub-mode we had not accounted for before: when the user asks for data they are not authorized to see, the agent escalates without trying to get clarity first, such as probing for user error or confusion, or asking about intent, including whether the user wants the matter escalated. Examples: `support-0221` and `support-0224`, where `get_order` returned `permission_denied` and the agent called `escalate_to_human`.

Both examples are in the after period only. In the before period the same two scenarios hit the same `permission_denied` and the agent explained the access limit without escalating (`support-0224` also checked the user's own orders). The change coincides with the prompt change between the periods. That is a correlation in two conversations, not an established cause.

The risk groups also exposed a judge blind spot: both flags overturned on review were escalations of data-quality problems, which are always justified (`support-0187` before, `support-0180` after). The before period's only random-sample flag was one of them.

**4. What action should happen if the estimate crosses the threshold?**
Start error analysis on the flagged traces. Confirmed failures become new evaluation cases.

## Notes

- **The before period spans a retry.** The HW3 run stopped when the API credit ran out and was resumed three days later, so no single uninterrupted window holds all 50 scenarios. The before window (2026-09-16 20:55 to 2026-09-19 17:58 UTC) covers both attempts; the monitor drops the 10 traces that never produced a reply, and each scenario counts once. Every trace in both periods used the same agent model.
- **Both periods drew the same random sample.** The sampler's fixed seed and the identical scenario list pick the same 10 scenarios in each period, so the comparison is paired. Some of the agreement in answer 2 follows from that. With live traffic the conversations would differ.
- **The scheduled workflow has never run.** `.github/workflows/monitor.yml` is written for a self-hosted runner because Langfuse runs on my computer, and this repository is public, so I did not leave a runner online. A hosted Langfuse and a GitHub-hosted runner would make the daily schedule live.
- **The dashboard's time axis shows one moment.** Langfuse stamps a score when it is first written and keeps that time on updates, so all scores sit on 2026-10-09 rather than at their conversations' times. New scores from `run.py` carry their conversation's time. The period prevalence score is attached to a Langfuse session (`hw7-monitor-before`, `hw7-monitor-after`) because Langfuse rejects a score with no target.
- **Costs.** Producing the traces: before $2.28, after $2.40 (gpt-5.5, from Langfuse token usage). Judging: before 14 calls about $0.011, after 16 calls about $0.013 (estimated from input token counts). Later runs record measured judge cost in `history.jsonl`.
