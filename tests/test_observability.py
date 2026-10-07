"""Homework 2, Part D: authentication and tool-span attribute tests.

Everything here runs offline: no Langfuse, no Docker, no model key. Span
attributes are checked with an in-memory OpenTelemetry tracer.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent.auth import AuthContext
from observability.instrument import record_tool_result
from server import app as server_app


def _create(user_id: int, role: str) -> dict:
    return server_app.create_session(server_app.SessionCreate(user_id=user_id, role=role))


# ---------------------------------------------------------------------------
# Session creation binds the *stored* identity, never the claimed one.
# ---------------------------------------------------------------------------


def test_create_session_rejects_claimed_role_that_differs_from_database(world: dict) -> None:
    server_app._SESSIONS.clear()
    with pytest.raises(HTTPException) as exc:
        _create(user_id=1, role="merchant")  # user 1 is a shopper
    assert exc.value.status_code == 403
    assert server_app._SESSIONS == {}, "a rejected request must not leave a session behind"


def test_create_session_rejects_unknown_role_and_unknown_user(world: dict) -> None:
    server_app._SESSIONS.clear()
    with pytest.raises(HTTPException) as bad_role:
        _create(user_id=1, role="admin")
    assert bad_role.value.status_code == 400
    with pytest.raises(HTTPException) as no_user:
        _create(user_id=999_999, role="shopper")
    assert no_user.value.status_code == 404
    assert server_app._SESSIONS == {}


# ---------------------------------------------------------------------------
# A token authorizes exactly the session it was issued for.
# ---------------------------------------------------------------------------


def test_token_for_one_session_cannot_authorize_another(world: dict) -> None:
    server_app._SESSIONS.clear()
    first = _create(user_id=1, role="shopper")
    second = _create(user_id=2, role="shopper")

    with pytest.raises(HTTPException) as exc:
        server_app._authorize(second["session_id"], f"Bearer {first['token']}")
    assert exc.value.status_code == 403

    # The same token still authorizes its own session, with the stored identity.
    ctx = server_app._authorize(first["session_id"], f"Bearer {first['token']}")
    assert (ctx.user_id, ctx.role, ctx.store_id) == (1, "shopper", None)


def test_tampered_or_missing_token_is_unauthorized(world: dict) -> None:
    server_app._SESSIONS.clear()
    created = _create(user_id=9002, role="merchant")
    body, _sig = created["token"].rsplit(".", 1)
    with pytest.raises(HTTPException) as tampered:
        server_app._authorize(created["session_id"], f"Bearer {body}.deadbeef")
    assert tampered.value.status_code == 401
    with pytest.raises(HTTPException) as missing:
        server_app._authorize(created["session_id"], None)
    assert missing.value.status_code == 401


# ---------------------------------------------------------------------------
# Part A: identity and permission attributes land on the active tool span.
# ---------------------------------------------------------------------------


def _record_on_span(ctx: AuthContext, result: dict) -> dict:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("execute_tool get_order"):
        record_tool_result(ctx, result)
    (span,) = exporter.get_finished_spans()
    return dict(span.attributes)


def test_tool_span_records_merchant_identity_and_denial() -> None:
    attrs = _record_on_span(
        AuthContext(user_id=9002, role="merchant", store_id=2),
        {"ok": False, "error": "permission_denied", "reason": "not your store"},
    )
    assert attrs["cartwheel.user_role"] == "merchant"
    assert attrs["cartwheel.user_id"] == "9002"  # decimal id as a string
    assert attrs["cartwheel.store_id"] == "2"  # decimal id as a string, merchants only
    assert attrs["cartwheel.permission_denied"] is True
    assert attrs["cartwheel.permission_denied.reason"] == "not your store"


def test_tool_span_records_allowed_shopper_call_without_reason() -> None:
    attrs = _record_on_span(
        AuthContext(user_id=1, role="shopper"),
        {"ok": True, "order": {"order_id": 4127}},
    )
    assert attrs["cartwheel.user_role"] == "shopper"
    assert attrs["cartwheel.user_id"] == "1"
    assert "cartwheel.store_id" not in attrs
    assert attrs["cartwheel.permission_denied"] is False
    assert "cartwheel.permission_denied.reason" not in attrs
