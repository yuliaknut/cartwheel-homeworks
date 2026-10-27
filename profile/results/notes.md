# HW9 notes: reducing cost

Working notes for the record (no video). Interpretations are the student's;
numbers come from the committed result files named in each line, or from
the scratchpad diagnostics where marked. Development cases only; the HW8
test split is spent. Baseline = Homework 8 final run,
`optimize/results/development-final-claude-haiku-5-5-20261020-001937.json`
(cefec04, claude-haiku-5-5): score 1.00, 128,362 input / 12,919 output
tokens, $0.193 per 100 conversations, median latency 11.1 s.

## Part A: where cost comes from

`profile/results/costs.csv`, built by `profile/scripts/costs.py` from the
handout's sources only (HW3 traces, HW5 and HW7 judge runs; the student
chose not to add the HW6/HW8 evaluation reruns).

- Customer conversations (`server/app.py:223`, gpt-5.5, 918 calls): $11.45,
  about 99% of the total. API token counts; 19.5% of input was already
  cached on the starting prompt.
- HW5 judge (`analysis/helpers/scale.py:234`, gpt-4o-mini, 159 real calls
  after excluding code-gated traces): $0.118, estimated tokens.
- HW7 judge (`monitoring/run.py:172`, 30 calls): $0.024, estimated tokens.
- A judge call reads about 3x the input of an agent call; the cost gap is
  the price per token (33x), not the length. The HW8 move to Haiku already
  cut conversation cost about 15x before HW9 started.

## Part B: fewer tokens (reverted)

- Where the tokens go (HW3 export): tool results ~21% of agent input, of
  which `search_help_center` 45%; the fixed system prompt plus tool
  definitions ~53% (~790-840 tokens per call, re-sent on every call).
- Candidates considered: `k` 3 -> 2 (rejected: 26 of 160 `get_policy`
  fetches in HW3 came from rank 3); merging `get_order`/`find_order`
  (rejected for HW9: locked tests in `tests/test_hw_holes.py`, and the
  development cases barely use `find_order`; a narrower follow-up would be
  adding `product_title` to `find_order` so the follow-up `get_order` round
  trip disappears, 13 of 20 HW3 turns).
- Change tried: the snippet became the one body sentence sharing the most
  words with the query (no length cap), instead of the first 300 characters.
  The student chose the uncapped sentence so the escalation rule in
  `cw-escalations` (176 characters, the justified-ticket rule behind HW8
  note 2) is never cut mid-sentence.
- Result (`development-fewer-tokens-claude-haiku-5-5-20261021-155320.json`,
  b6212c6): score 1.00, input 166,732 (+30%), output 13,909, $0.236 per 100
  (+22%), median latency 8.9 s.
- Diagnosis (scratchpad, one run per configuration, same day): old snippets
  38 model calls, 5 `get_policy`, 119,147 input; new snippets 48 calls, 12
  `get_policy`, 155,993 input (+31%). Five cases (e-001, e-004, e-008,
  e-012, e-013) each gained one to three model calls and one to two
  `get_policy` fetches. With one sentence the agent fetched the full policy
  instead of answering from the snippet; each fetch is a round trip that
  re-sends the whole conversation. Both diagnostic runs scored 0.90 from
  the same e-008 judge Fail (HW8 note 1), unrelated to the change.
- Latency fell in both runs with the new snippets (11.1 -> 8.9 s; 8.5 ->
  7.3 s) despite more calls. Unexplained; one run per case, recorded as a
  correlation only.
- Decision: revert (e2a30ca). The handout's latency clause would allow a
  keep, but the change raised cost in two runs for a known reason.
- Lesson: fewer tokens per tool result is not fewer tokens per
  conversation. Text the agent actually reads from is cheaper to leave in
  than to make the agent fetch.

## Part C: prompt order for caching (reverted)

- Model: gpt-6.1-sol (cached input $0.10/M already in `optimize/config.json`
  since HW8). Change: `## Session context` moved to the end of
  `SYSTEM_PROMPT_TEMPLATE`, wording unchanged (9c7e7ab).
- `cache-before` (`development-cache-before-gpt-6.1-sol-20261026-130224.json`,
  prompt 4bec38652cf5): score 0.90, 58,055 input, cached_fraction 0.689,
  $0.719 per 100, median latency 15.5 s.
- `cache-after` (`development-cache-after-gpt-6.1-sol-20261026-133807.json`,
  prompt 82e683dfd42d): score 0.90, 52,913 input, cached_fraction 0.691,
  $0.640 per 100 (-11%), median latency 10.1 s. Both runs failed only
  e-008, the HW8 note 1 toss.
- Caching did not measurably improve (+0.2 points). Most of each
  conversation was already cached before the change: every later call in a
  conversation repeats the previous request, so only first calls could
  gain, a ceiling of roughly 4,500 tokens over ten cases. Why first calls
  did not gain more is not established (the runner keeps run totals, not
  per-call usage); the cost drop came from shorter conversations, not from
  cached tokens.
- e-007 (merchant, order 8001 delivered before it shipped; the case says a
  ticket is justified) opened a ticket before and not after. Rerun three
  times per order (scratchpad wrapper, same prompts): before 3/3 tickets,
  after 0/3 (one run offered a ticket). Repeatable on this case and model;
  one case on sol, not the Haiku development model, and the cause is
  unknown. This is HW8 note 2's under-escalation, made worse.
- The score cannot see it, and here it points the wrong way: the
  `unnecessary_escalation` judge failed 2 of the 3 justified before-tickets
  ("the contradiction in the order record itself does not alone trigger
  the need for a human ticket"), while the no-ticket runs pass through the
  code gate. Before scored 0.33 on e-007, after 1.00. Part of the -11% cost
  is the missing tickets themselves (fewer calls, no judge call).
- Decision: revert (790f6ca). The handout's keep rule (score did not drop)
  was met, but the student's rule that HW9 must not make note 2 worse
  overrides it, and the caching gain the change was for did not appear.
- Lesson: a cost change that removes a step the agent should take looks
  like a saving. Check the justified-ticket cases by behaviour, not by
  score, when the judge only looks for unnecessary tickets.

## Part D: model cascade on the unnecessary_escalation judge (rejected)

- Oracle: `unnecessary_escalation-v2` (gpt-4o-mini), saved verdicts reused.
  Proxy: claude-haiku-5-5, same judge prompt and trailing instruction, plus
  one confidence line and a JSON format line (the oracle got its schema
  from DocETL; the proxy is called directly through LiteLLM). Code-gated
  traces (no ticket) keep the gate's Pass and never reach either model, so
  agreement is computed over model-judged traces only: 28 dev, 27 test.
  Code: `cascade/run_proxy.py`.
- Criteria, set by the student before any proxy run (framing B): oracle
  agreement >= 0.90 on judged traces (at most 2 of 28 dev, 2 of 27 test)
  AND label agreement no lower than the oracle's own on the same traces
  (dev 19/28, test 21/27); threshold = lowest meeting both on dev, fixed
  for test. The oracle's judged-only agreement with the labels (0.68 dev,
  0.78 test) was computed after M was chosen and set the floor.
- Dev sweep (`cascade/results/thresholds.csv`): lowest qualifying
  threshold 0.90 (oracle 26/28, labels 21/28, proxy share 0.57,
  $1.40 per 1,000 verdicts against $0.74 for the oracle alone). Every
  threshold cost more than the oracle alone: Haiku reads ~6,800 input and
  writes ~820 output tokens per verdict against gpt-4o-mini's ~4,200 and
  ~190 (Part A estimate).
- Test check at 0.90 (`cascade/results/check.json`): oracle agreement
  24/27 = 0.889, 3 disagreements, below the minimum by one; labels 24/27
  (floor met); proxy share 0.74; $1.24 per 1,000. Traces 1-17 were
  transcribed from the console of a first run that stopped at trace 18
  without saving (Haiku omitted the confidence field twice); each test
  trace kept its first usable draw (recorded in `proxy-test.json`).
- Decision: reject (student). As expected, a cascade is a poor fit here:
  it assumes a cheap proxy approximating a trusted, expensive oracle, and
  here the proxy costs more and the oracle is the weaker judge. Raising the
  threshold bought oracle agreement by handing correct Haiku verdicts to a
  wrong oracle (dev label agreement fell from 1.00 at 0.50 to 0.75 at
  0.90). The test failure was three disagreements, all of them traces
  where Haiku matched the label.
- Finding, outside Part D's question: Haiku alone matched the student's
  labels on every judged trace, 28/28 dev and 27/27 test; the oracle
  matched 19/28 and 21/27. Dev was used to iterate the v2 prompt in HW5;
  test was not, which makes the test half the cleaner evidence. 55 traces
  from the gpt-5.5 agent (HW3), not from Haiku-agent traffic. Replacing
  the judge is a judge-validation question (HW5); the HW7 monitoring
  numbers came from gpt-4o-mini and were never measured against Haiku.
  Combined with Part C's e-007 verdicts, the oracle looks least reliable on
  justified tickets.
- Hindsight (student): the model choices across HW5, HW8 and HW9 would
  have been different with the full homework path visible; HW9's
  constraints (an OpenAI model for caching, a proxy cheaper than the HW5
  judge) were set by earlier choices.

## Part E: frontier and the configuration to use

- `profile/results/frontier.csv`, built by `profile/scripts/frontier.py`
  from the four saved development results: HW8 final, `fewer-tokens`,
  `cache-before`, `cache-after`. Part B's two diagnostic reruns are left
  out by the student's choice (scratch instrumented reruns of
  configurations already in the table). `write_pass_5` is empty in every
  row: the development split has no write cases.
- Frontier: HW8 final alone (score 1.00, $0.193 per 100). `fewer-tokens`
  is dominated on cost at the same score; both gpt-6.1-sol runs are
  dominated on score and cost.
- Choice (student): the HW8 final configuration, cefec04 on
  claude-haiku-5-5, unchanged. Both HW9 changes were reverted for
  measured reasons, and its known weakness (HW8 note 2) is documented.
- Caveats: one run per case; the 0.90 vs 1.00 gap is e-008 alone (HW8
  note 1); the score cannot see under-escalation on justified tickets
  (Part C, e-007), so a score with justified-ticket checks could reorder
  the table.

## Costs

Itemised in the course progress log. Part B: `fewer-tokens` $0.0236;
diagnosis ~$0.042 (two agent runs plus two judge calls). Part C:
`cache-before` ~$0.074, `cache-after` ~$0.066, e-007 reruns ~$0.024.
Part D: dev proxy ~$0.036 (including a stopped first attempt and a
debug call), test proxy ~$0.031. HW9 total so far about $0.30.
