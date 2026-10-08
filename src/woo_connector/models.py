"""Agent-friendly views of WooCommerce payloads.

A raw WooCommerce order is 2.5-4 KB of JSON (meta_data, tax lines, links, every address field).
An agent answering "which orders are on hold?" needs ~10 of those fields. Every model here has
a ``from_wc`` constructor that keeps what an agent reasons about and drops the rest; callers
that need everything pass ``verbose=True`` to the tools and get the raw dict instead.

Money stays as the string WooCommerce sends (``"1299.00"``) to avoid float rounding; the
currency code travels alongside it.
"""

from __future__ import annotations

import html
import re
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    per_page: int
    total: int = Field(description="total matching items across all pages (from X-WP-Total)")
    total_pages: int
    has_more: bool


class Customer(BaseModel):
    id: int = Field(description="0 for guest checkout")
    name: str
    email: str


class LineItem(BaseModel):
    product_id: int
    variation_id: int = 0
    name: str
    sku: str = ""
    quantity: int
    total: str

    @classmethod
    def from_wc(cls, d: dict[str, Any]) -> LineItem:
        return cls(
            product_id=d.get("product_id", 0),
            variation_id=d.get("variation_id", 0) or 0,
            name=d.get("name", ""),
            sku=d.get("sku") or "",
            quantity=d.get("quantity", 0),
            total=str(d.get("total", "0")),
        )


class OrderSummary(BaseModel):
    id: int
    number: str
    status: str
    currency: str
    total: str
    subtotal_discount: str = Field(description="discount_total as reported by WooCommerce")
    shipping_total: str
    total_tax: str
    date_created: str = Field(description="ISO-8601, UTC (date_created_gmt)")
    date_paid: str | None = None
    payment_method: str
    customer: Customer
    customer_note: str = ""
    shipping_city: str = ""
    shipping_postcode: str = ""
    line_items: list[LineItem]

    @classmethod
    def from_wc(cls, d: dict[str, Any]) -> OrderSummary:
        billing = d.get("billing") or {}
        shipping = d.get("shipping") or {}
        name = " ".join(p for p in (billing.get("first_name"), billing.get("last_name")) if p).strip()
        return cls(
            id=d["id"],
            number=str(d.get("number", d["id"])),
            status=d.get("status", ""),
            currency=d.get("currency", ""),
            total=str(d.get("total", "0")),
            subtotal_discount=str(d.get("discount_total", "0")),
            shipping_total=str(d.get("shipping_total", "0")),
            total_tax=str(d.get("total_tax", "0")),
            date_created=d.get("date_created_gmt") or d.get("date_created") or "",
            date_paid=d.get("date_paid_gmt") or d.get("date_paid"),
            payment_method=d.get("payment_method_title") or d.get("payment_method") or "",
            customer=Customer(id=d.get("customer_id", 0) or 0, name=name, email=billing.get("email") or ""),
            customer_note=d.get("customer_note") or "",
            shipping_city=shipping.get("city") or billing.get("city") or "",
            shipping_postcode=shipping.get("postcode") or billing.get("postcode") or "",
            line_items=[LineItem.from_wc(li) for li in d.get("line_items", [])],
        )


class ProductSummary(BaseModel):
    id: int
    name: str
    sku: str = ""
    type: str = Field(description="simple | variable | grouped | external")
    status: str
    price: str
    regular_price: str
    sale_price: str = ""
    on_sale: bool = False
    stock_status: str = Field(description="instock | outofstock | onbackorder")
    manage_stock: bool
    stock_quantity: int | None = Field(None, description="null when stock is not tracked for this product")
    low_stock_amount: int | None = None
    categories: list[str] = []
    variation_ids: list[int] = []
    permalink: str = ""
    description: str = Field("", description="merchant-written description, HTML stripped, truncated to 300 chars")

    @classmethod
    def from_wc(cls, d: dict[str, Any]) -> ProductSummary:
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            sku=d.get("sku") or "",
            type=d.get("type", "simple"),
            status=d.get("status", ""),
            price=str(d.get("price", "")),
            regular_price=str(d.get("regular_price", "")),
            sale_price=str(d.get("sale_price", "") or ""),
            on_sale=bool(d.get("on_sale", False)),
            stock_status=d.get("stock_status", ""),
            manage_stock=d.get("manage_stock") is True,  # variations may say "parent"
            stock_quantity=d.get("stock_quantity"),
            low_stock_amount=_int_or_none(d.get("low_stock_amount")),
            categories=[c.get("name", "") for c in d.get("categories", [])],
            variation_ids=list(d.get("variations", []) or []),
            permalink=d.get("permalink", ""),
            description=strip_html(d.get("short_description") or d.get("description") or ""),
        )


class StockInfo(BaseModel):
    product_id: int
    name: str
    sku: str = ""
    type: str
    manage_stock: bool
    stock_quantity: int | None
    stock_status: str
    low_stock_amount: int | None = None
    backorders: str = Field("no", description="no | notify | yes")

    @classmethod
    def from_wc(cls, d: dict[str, Any]) -> StockInfo:
        return cls(
            product_id=d["id"],
            name=d.get("name", ""),
            sku=d.get("sku") or "",
            type=d.get("type", "simple"),
            manage_stock=d.get("manage_stock") is True,  # variations may say "parent"
            stock_quantity=d.get("stock_quantity"),
            stock_status=d.get("stock_status", ""),
            low_stock_amount=_int_or_none(d.get("low_stock_amount")),
            backorders=d.get("backorders") or "no",
        )


class CustomerSummary(BaseModel):
    id: int
    name: str
    email: str
    username: str = ""
    role: str = "customer"
    date_created: str = Field("", description="ISO-8601, UTC")
    is_paying_customer: bool = False
    phone: str = ""
    city: str = ""
    country: str = ""

    @classmethod
    def from_wc(cls, d: dict[str, Any]) -> CustomerSummary:
        billing = d.get("billing") or {}
        shipping = d.get("shipping") or {}
        name = " ".join(p for p in (d.get("first_name"), d.get("last_name")) if p).strip() or d.get("username", "")
        return cls(
            id=d["id"],
            name=name,
            email=d.get("email") or billing.get("email") or "",
            username=d.get("username") or "",
            role=d.get("role") or "customer",
            date_created=d.get("date_created_gmt") or d.get("date_created") or "",
            is_paying_customer=bool(d.get("is_paying_customer", False)),
            phone=billing.get("phone") or "",
            city=shipping.get("city") or billing.get("city") or "",
            country=shipping.get("country") or billing.get("country") or "",
        )


class OrderStatusTotal(BaseModel):
    slug: str
    name: str
    total: int


def strip_html(value: str, limit: int = 300) -> str:
    """Product descriptions are merchant-authored HTML - untrusted content. Flatten to plain text."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
