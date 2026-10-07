# Interface comparison

Review interface: `analysis/review_app/` (`index.html`, `server.py`,
`load_traces.py`, `select_batch.py`), served with `uv run python -m
analysis.review_app.server`. Built on the reference (`analysis/ui/index.html`,
`analysis/server.py`) and the Homework 3 page.

## Retained from the reference interface

The annotation model. An open code is made by selecting the text carrying a
failure and typing a free-form note, which appears as a card in the right
column linked to the highlight.

## Changed after inspecting the traces

Personalized ergonomics. The trace layout was changed so that narration is
nested with its tool calls under the user message and the reply is prominent;
retrieved policy references are now listed as separate blocks under the
tool-call result for readability; a color-coded review tracker was added to
the top bar to show the review state of each trace and speed up navigation
between traces.

## Limitation remaining

The interface assumes one reviewer on one machine. Notes are saved by
replacing the whole file and the poll never re-reads them, so reviewing from a
second device, or even a second tab, means two clients silently overwriting
each other.
