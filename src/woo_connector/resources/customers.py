"""Customer primitives: list / get / search over registered customer accounts.

Guest checkouts are not customers in WooCommerce (``customer_id`` 0 on the order); their details
live only on the order, so "find everyone who bought X" still goes through ``orders``.
"""

from __future__ import annotations

from typing import Any

from woo_connector.client import WooClient
from woo_connector.models import CustomerSummary, Page
from woo_connector.resources.orders import to_page


async def list_customers(
    woo: WooClient,
    *,
    email: str | None = None,
    role: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> Page[CustomerSummary]:
    """Registered customers, optionally by exact email or WordPress role (default: customer)."""
    items, meta = await woo.get_page(
        "customers",
        {"email": email.strip() if email else None, "role": role, "page": page, "per_page": per_page},
    )
    return to_page(items, meta, CustomerSummary)


async def get_customer(woo: WooClient, customer_id: int, *, verbose: bool = False) -> CustomerSummary | dict[str, Any]:
    raw = await woo.get_json(f"customers/{int(customer_id)}")
    return raw if verbose else CustomerSummary.from_wc(raw)


async def search_customers(woo: WooClient, query: str, *, page: int = 1, per_page: int = 20) -> Page[CustomerSummary]:
    """Free-text search over name, username and email (WooCommerce ``search`` on ``/customers``)."""
    items, meta = await woo.get_page("customers", {"search": query.strip(), "page": page, "per_page": per_page})
    return to_page(items, meta, CustomerSummary)
