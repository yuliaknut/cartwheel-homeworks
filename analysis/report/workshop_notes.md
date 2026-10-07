# Raindrop Workshop notes

Part C, attempted and only partly completed. Workshop was installed and wired, five
fresh runs were captured, but Workshop could not deliver the tool-level detail the
part is built around. What follows is what was set up, what the runs showed, and why
the execution-level inspection did not happen.

## Setup

Raindrop 0.1.21, installed locally, daemon on `http://localhost:5899`. No account and
no cloud connection.

Instrumentation is additive and lives in `observability/raindrop_workshop.py`.
`observability/instrument.py` was not modified: Langfuse remains the canonical trace
store, and its OpenTelemetry tracer provider is untouched. Verified by comparing the
global provider object before and after Raindrop initialises — the same object, with
its span processors intact.

The Raindrop client is configured `api_key=None`, `tracing_enabled=False`,
`auto_instrument=False`, so it registers no tracer provider, installs no Traceloop
instrumentors alongside the OpenLLMetry OpenAI Agents instrumentor, and sends nothing
off the machine. One `begin`/`finish` pair wraps `Runner.run` in
`server/app.py:post_message`, which is one conversation turn and therefore the same
unit as a Langfuse trace. `agent/agent.py` reports each tool call through
`track_tool_event`.

## Runs inspected

Five scenarios, chosen before looking at outcomes to cover three roles and six of the
nine tools. Every Workshop run carries its Langfuse `trace_id` in metadata, so the two
stores join on it.

The Workshop run id and the Langfuse trace id are the same value, because the run is
stamped with the trace id of the turn that produced it.

| scenario | role | intent | run id / trace id |
| --- | --- | --- | --- |
| support-0032 | shopper | refund | `d2c03f11f3d73bc05e013f6b55c6e2af` |
| support-0088 | shopper | product_search | `e4f04de4a641e1ec204884eb7efb3b08` |
| support-0132 | merchant | policy_question | `6cb6021ab686dcc1e0f561010d6cb4a8` |
| support-0142 | merchant | cancellation | `a90077d0b8c8420efbc780338ae8a2f6` |
| support-0173 | support | find_order_by_description | `34cdbdaf5b8596b71701902740d9fced` |

An earlier pass of the same five failed with `429 insufficient_quota`. The cause was
not an empty account: `load_env()` uses `os.environ.setdefault`, so an exhausted key
exported from the shell took precedence over the current key in `.env`. Those five
error runs are also in the Workshop database and are not part of this analysis.

## Why the execution-level inspection did not happen

Workshop captured the interaction envelope for each run — user input, final reply,
model, role, prompt version, scenario id, Langfuse trace id, git commit — and one LLM
span. It captured no tool spans.

The cause is in the SDK rather than the configuration. `Interaction.track_tool` begins:

    if not st._tracing_enabled:
        return

and `_configure` force-disables tracing when no write key is present:

    if not st.write_key:
        st._tracing_enabled = False
        st._bypass_otel_for_tools = False
        return

So tool spans require a Raindrop cloud write key. A local-only installation, which the
handout says is sufficient, cannot show tool calls. Enabling tracing was tested and
does not disturb Langfuse — the provider is preserved — so the wiring is correct and
would work unchanged with a key.

This makes Workshop strictly less informative here than the two stores already in use:
Langfuse holds full tool spans through OpenLLMetry, and the Homework 4 review interface
renders narration, tool calls, tool results, and retrieved policies grouped by session.
Part C was therefore stopped rather than completed through a workaround.

## Candidate observations from the five runs

These come from the replies Workshop captured, not from tool-level analysis.

**`internal_detail_exposed` reproduced in fresh runs.** Three of the five replies put
internal representation in front of the user, independently of the 100 reviewed traces:

- support-0173: `**Refund eligible:** No`
- support-0032: `**Refund eligibility:** The order record currently shows it as **refund-eligible**`
- support-0088: `Product ID: **90**`, `Product ID: **96**`

Three of five is consistent with the sample fraction in the reviewed set, and is worth
recording because these runs were selected for tool coverage rather than for this mode.

**No new candidate failure mode appeared.** The remaining replies were accurate.
support-0142 is a false-premise case handled correctly: the merchant implied order 1532
still needed fulfilling, and the agent established it was already cancelled. The store,
product, and status it reported all check out against the database.

## Uncertainty

`Product ID: 90` in support-0088 may not belong in `internal_detail_exposed`. The mode
covers internal representation reaching the reply, and `refund_eligible` is clearly a
schema field. A product identifier is different: shoppers routinely see product ids on
commerce sites, and `get_product` takes one as an argument, so quoting it may be helping
the user rather than leaking an internal handle. The alternative explanation is that the
boundary should distinguish identifiers a user can act on from field names they cannot.
This was not resolved, and the mode's boundary currently does not address it.
