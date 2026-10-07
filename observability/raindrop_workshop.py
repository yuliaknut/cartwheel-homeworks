"""Raindrop Workshop tracing, alongside Langfuse (Homework 4, Part C).

Workshop is a local trace debugger used to inspect model and tool activity at
a finer grain than the review interface shows. It is additive: Langfuse stays
the canonical store for every Cartwheel trace, score, and annotation.

The isolation that makes that safe is in :func:`setup_workshop`:

  * ``api_key=None``      cloud telemetry is skipped; events go only to the
                          local daemon, so nothing leaves the machine.
  * ``tracing_enabled=False``
                          Raindrop registers no OpenTelemetry tracer provider,
                          so it cannot contend with the one Langfuse installs
                          in ``observability.instrument.setup_tracing``.
  * ``auto_instrument=False``
                          no Traceloop auto-instrumentation, so it cannot
                          compete with the OpenLLMetry OpenAI Agents
                          instrumentor, which runs with
                          ``replace_existing_processors=True``.

Manual ``begin``/``finish`` works regardless of those three settings, so the
interaction envelope is captured. ``track_tool_event`` does not: the SDK
force-disables tracing when no write key is present, and ``track_tool`` returns
early without it, so tool spans need a Raindrop cloud key. The calls are kept
because they are correct and would work unchanged with one. See
``analysis/report/workshop_notes.md``.

Everything here is a no-op when the Workshop daemon is not running, so normal
runs are unaffected.
"""

from __future__ import annotations

import contextvars
import logging
import os
import socket
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("cartwheel.workshop")

DEFAULT_URL = "http://localhost:5899/v1/"
_enabled = False

# The turn currently being served, so a tool wrapper deep inside Runner.run can
# attach its call to the right interaction. A ContextVar follows asyncio tasks;
# _last_turn is the fallback for a tool dispatched onto a worker thread, which
# is safe here because the scenario runner plays one turn at a time.
_current_turn: contextvars.ContextVar[Any] = contextvars.ContextVar("cartwheel_workshop_turn", default=None)
_last_turn: Any = None


def _daemon_is_up(url: str, timeout: float = 0.4) -> bool:
    """TCP probe, so a missing Workshop costs a few milliseconds, not a hang."""
    parsed = urlparse(url)
    host, port = parsed.hostname or "localhost", parsed.port or 5899
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def setup_workshop() -> bool:
    """Send this process's interactions to the local Workshop daemon.

    Returns False and changes nothing when the daemon is not reachable, so the
    server and the scenario runner behave identically with Workshop stopped.
    """
    global _enabled
    if _enabled:
        return True
    url = os.environ.get("RAINDROP_LOCAL_DEBUGGER", DEFAULT_URL).strip() or DEFAULT_URL
    if not _daemon_is_up(url):
        log.info("Raindrop Workshop is not running at %s; Workshop tracing is off", url)
        return False
    try:
        import raindrop.analytics as raindrop

        raindrop.init(
            api_key=None,          # local only; never contacts api.raindrop.ai
            tracing_enabled=False,  # no OTel provider: Langfuse keeps the global one
            auto_instrument=False,  # no Traceloop instrumentors alongside OpenLLMetry
            # Inert without a write key, kept because it is the correct setting
            # if one is ever added: it posts tool spans straight to the Workshop
            # daemon rather than through an OTEL pipeline Langfuse owns.
            # track_tool() is a no-op in local-only mode regardless, because
            # _configure force-disables tracing when write_key is None. See
            # analysis/report/workshop_notes.md.
            bypass_otel_for_tools=True,
            local_workshop_url=url,
        )
    except Exception as exc:  # pragma: no cover - never break a run over a debugger
        log.warning("Raindrop Workshop init failed (%s); continuing without it", exc)
        return False
    _enabled = True
    log.info("Raindrop Workshop tracing enabled; mirroring interactions to %s", url)
    return True


def begin_turn(
    *,
    user_id: str,
    session_id: str,
    message: str,
    properties: dict[str, Any] | None = None,
    model: str | None = None,
) -> Any | None:
    """Open one Workshop interaction for one conversation turn, or None."""
    if not _enabled:
        return None
    try:
        import raindrop.analytics as raindrop

        turn = raindrop.begin(
            user_id=user_id,
            event="cartwheel.session_message",
            convo_id=session_id,
            input=message,
            model=model,
            properties=properties or {},
        )
    except Exception as exc:  # pragma: no cover
        log.warning("Workshop begin failed (%s)", exc)
        return None
    global _last_turn
    _current_turn.set(turn)
    _last_turn = turn
    return turn


def track_tool_event(
    name: str, tool_input: Any = None, tool_output: Any = None, duration_ms: float | None = None
) -> None:
    """Attach one tool call to the turn in flight.

    Called from the two places every Cartwheel tool already reports through,
    so Workshop shows the tool sequence rather than only the final reply.
    Silent when Workshop is off or no turn is open, which is the case for the
    CLI and for unit tests.
    """
    if not _enabled:
        return
    turn = _current_turn.get() or _last_turn
    if turn is None:
        return
    try:
        err = None
        if isinstance(tool_output, dict) and tool_output.get("ok") is False:
            err = str(tool_output.get("error") or "error")
        turn.track_tool(
            name=name,
            input=tool_input,
            output=tool_output,
            duration_ms=duration_ms,
            error=err,
        )
    except Exception as exc:  # pragma: no cover
        log.warning("Workshop track_tool failed for %s (%s)", name, exc)


def finish_turn(interaction: Any | None, output: str) -> None:
    """Close a Workshop interaction. Safe to call with None."""
    global _last_turn
    if interaction is None:
        return
    try:
        interaction.finish(output=output)
    except Exception as exc:  # pragma: no cover
        log.warning("Workshop finish failed (%s)", exc)
    finally:
        _current_turn.set(None)
        _last_turn = None


def flush() -> None:
    """Push buffered interactions. Short-lived processes should call this."""
    if not _enabled:
        return
    try:
        import raindrop.analytics as raindrop

        raindrop.flush()
    except Exception as exc:  # pragma: no cover
        log.warning("Workshop flush failed (%s)", exc)
