"""Order primitives: list / get / search, plus per-status totals."""

from __future__ import annotations

from typing import Any

from woo_connector.client import WooClient
from woo_connector.models import OrderStatusTotal, OrderSummary, Page

# Core statuses WooCommerce ships with. Plugins add more (e.g. "shipped"); we pass unknown
# values through and let the store answer with a 400 rather than guess.
KNOWN_STATUSES = (
    "any",
    "pending",
    "processing",
    "on-hold",
    "completed",
    "cancelled",
    "refunded",
    "failed",
    "draft",
    "trash",
)


def normalize_status(status: str) -> str:
    """Accept the spellings humans and LLMs use: ``On Hold``, ``on_hold``, ``wc-on-hold`` -> ``on-hold``."""
    return status.strip().lower().replace("_", "-").replace(" ", "-").removeprefix("wc-")


def datetime_bound(value: str | None, *, end: bool = False) -> str | None:
    """WooCommerce wants ISO-8601 datetimes; let callers pass a bare date."""
    if not value:
        return None
    value = value.strip()
    if len(value) == 10:  # YYYY-MM-DD
        return f"{value}T23:59:59" if end else f"{value}T00:00:00"
    return value


def to_page(items: list[dict[str, Any]], meta: Any, model: type) -> Page:
    return Page(
        items=[model.from_wc(i) for i in items],
        page=meta.page,
        per_page=meta.per_page,
        total=meta.total,
        total_pages=meta.total_pages,
        has_more=meta.has_more,
    )


async def list_orders(
    woo: WooClient,
    *,
    status: str | None = None,
    after: str | None = None,
    before: str | None = None,
    customer_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> Page[OrderSummary]:
    """Orders newest-first, optionally filtered by status, creation window and customer."""
    items, meta = await woo.get_page(
        "orders",
        {
            "status": normalize_status(status) if status else None,
            "after": datetime_bound(after),
            "before": datetime_bound(before, end=True),
            "customer": customer_id,
            "page": page,
            "per_page": per_page,
        },
    )
    return to_page(items, meta, OrderSummary)


async def get_order(woo: WooClient, order_id: int, *, verbose: bool = False) -> OrderSummary | dict[str, Any]:
    """One order by numeric id (the id, not the display number - they usually coincide)."""
    raw = await woo.get_json(f"orders/{int(order_id)}")
    return raw if verbose else OrderSummary.from_wc(raw)


async def search_orders(woo: WooClient, query: str, *, page: int = 1, per_page: int = 20) -> Page[OrderSummary]:
    """Free-text search. WooCommerce matches order number, billing/shipping name, email, and
    line-item names (behaviour of the ``search`` parameter on ``/orders``).

    WooCommerce compares the term against first_name and last_name *separately*, so a full name
    ("Priya Nair") matches nothing. When a multi-word query finds nothing we retry with the first
    word, which is what a human would do next; the caller can narrow by email if it is too broad.
    """
    query = query.strip()
    items, meta = await woo.get_page("orders", {"search": query, "page": page, "per_page": per_page})
    if meta.total == 0 and " " in query:
        first_word = query.split()[0]
        items, meta = await woo.get_page("orders", {"search": first_word, "page": page, "per_page": per_page})
    return to_page(items, meta, OrderSummary)


async def order_status_totals(woo: WooClient) -> list[OrderStatusTotal]:
    """How many orders sit in each status (``/reports/orders/totals``) - also the list of valid statuses."""
    rows = await woo.get_json("reports/orders/totals")
    return [OrderStatusTotal(slug=r["slug"], name=r.get("name", r["slug"]), total=int(r.get("total", 0))) for r in rows]
