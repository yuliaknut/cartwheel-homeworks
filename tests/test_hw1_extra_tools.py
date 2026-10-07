"""Contract tests for the student-added Homework 1 tool: get_product.

Kept separate from tests/test_hw_holes.py so the instructor-supplied
contract tests stay untouched.
"""

from __future__ import annotations

import sqlite3

from agent import agent as agent_module
from agent import tools
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_get_product_names_the_item_behind_an_order(world: dict) -> None:
    conn = sqlite3.connect(world["db"])
    try:
        product_id, title, store_id = conn.execute(
            "SELECT p.id, p.title, p.store_id FROM orders o JOIN products p ON p.id = o.product_id "
            "WHERE o.id = 4127"
        ).fetchone()
        store_name = conn.execute(
            "SELECT name FROM stores WHERE id = ?", (store_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    result = tools.get_product(SHOPPER_1, product_id)
    assert result["ok"] is True
    product = result["product"]
    assert product["product_id"] == product_id
    assert product["title"] == title
    assert product["store_id"] == store_id
    assert product["store_name"] == store_name
    assert isinstance(product["price_usd"], float)
    assert set(product) == {
        "product_id", "store_id", "store_name", "title", "description", "category", "price_usd",
    }


def test_get_product_is_public_to_every_role(world: dict) -> None:
    for ctx in (SHOPPER_1, MERCHANT_STORE_2, SUPPORT):
        assert tools.get_product(ctx, 1)["ok"] is True


def test_get_product_unknown_id_is_not_found(world: dict) -> None:
    missing = tools.get_product(SHOPPER_1, 999_999)
    assert missing["ok"] is False
    assert missing["error"] == "not_found"
    assert "999999" in missing["reason"]


def test_order_payloads_carry_the_product_title(world: dict) -> None:
    """HW2 follow-up: list_my_orders and get_order name the item, so one
    listing no longer costs one get_product call per order."""
    conn = sqlite3.connect(world["db"])
    try:
        titles = dict(conn.execute("SELECT id, title FROM products").fetchall())
    finally:
        conn.close()

    listing = tools.list_my_orders(SHOPPER_1)
    assert listing["ok"] is True and listing["orders"]
    for order in listing["orders"]:
        assert order["product_title"] == titles[order["product_id"]]

    single = agent_module.get_order_logic(SHOPPER_1, 4127)
    assert single["ok"] is True
    assert single["order"]["product_title"] == titles[single["order"]["product_id"]]


def test_get_product_is_registered_for_every_role() -> None:
    for role, registered in agent_module.TOOLS_BY_ROLE.items():
        names = [tool.name for tool in registered]
        assert "get_product" in names, f"get_product missing for role {role!r}"
