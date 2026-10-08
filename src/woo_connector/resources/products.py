"""Product / inventory primitives: list / get / search, stock lookup, low-stock scan."""

from __future__ import annotations

from typing import Any

from woo_connector.client import WooClient
from woo_connector.errors import BadRequestError, NotFoundError
from woo_connector.models import Page, ProductSummary, StockInfo
from woo_connector.resources.orders import to_page

STOCK_STATUSES = ("instock", "outofstock", "onbackorder")


async def list_products(
    woo: WooClient,
    *,
    status: str | None = None,
    stock_status: str | None = None,
    category: int | None = None,
    product_type: str | None = None,
    sku: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> Page[ProductSummary]:
    items, meta = await woo.get_page(
        "products",
        {
            "status": status,
            "stock_status": stock_status,
            "category": category,
            "type": product_type,
            "sku": sku,
            "page": page,
            "per_page": per_page,
        },
    )
    return to_page(items, meta, ProductSummary)


async def get_product(woo: WooClient, product_id: int, *, verbose: bool = False) -> ProductSummary | dict[str, Any]:
    raw = await woo.get_json(f"products/{int(product_id)}")
    return raw if verbose else ProductSummary.from_wc(raw)


async def search_products(woo: WooClient, query: str, *, page: int = 1, per_page: int = 20) -> Page[ProductSummary]:
    """Free-text search over product name / description / SKU (WooCommerce ``search`` param)."""
    items, meta = await woo.get_page("products", {"search": query.strip(), "page": page, "per_page": per_page})
    return to_page(items, meta, ProductSummary)


async def get_stock(woo: WooClient, *, product_id: int | None = None, sku: str | None = None) -> StockInfo:
    """Stock for one product or variation, looked up by id or by exact SKU."""
    if product_id is not None:
        return StockInfo.from_wc(await woo.get_json(f"products/{int(product_id)}"))
    if sku:
        # The sku filter on /products also matches variation SKUs and returns the variation itself.
        items, _ = await woo.get_page("products", {"sku": sku.strip(), "per_page": 1})
        if not items:
            raise NotFoundError(f"no product with SKU {sku!r}", hint="SKU match is exact and case-sensitive")
        return StockInfo.from_wc(items[0])
    raise BadRequestError("pass product_id or sku")


async def list_low_stock(
    woo: WooClient,
    *,
    threshold: int = 5,
    limit: int = 50,
    max_pages: int = 10,
) -> list[StockInfo]:
    """Products and variations whose tracked stock is at or below ``threshold``.

    WooCommerce has no server-side "low stock" filter, so this walks published products
    (100 per page, at most ``max_pages`` pages) and inspects each one client-side; variable
    products cost one extra call for their variations. Untracked stock is skipped because it
    has no quantity to compare.
    """
    found: list[StockInfo] = []

    def consider(d: dict[str, Any]) -> None:
        if d.get("manage_stock") is True and d.get("stock_quantity") is not None:
            if int(d["stock_quantity"]) <= threshold:
                found.append(StockInfo.from_wc(d))

    async for page in woo.iter_pages("products", {"status": "publish"}, max_pages=max_pages):
        for product in page:
            if len(found) >= limit:
                break
            if product.get("type") == "variable":
                variations = await woo.get_json(f"products/{product['id']}/variations", {"per_page": 100})
                for variation in variations:
                    consider(_variation_as_product(product, variation))
            else:
                consider(product)
        if len(found) >= limit:
            break

    found.sort(key=lambda s: (s.stock_quantity if s.stock_quantity is not None else 0, s.product_id))
    return found[:limit]


def _variation_as_product(parent: dict[str, Any], variation: dict[str, Any]) -> dict[str, Any]:
    """Variations lack ``name``/``type``; borrow the parent's name and attach the chosen options."""
    options = ", ".join(a.get("option", "") for a in variation.get("attributes", []) if a.get("option"))
    name = f"{parent.get('name', '')} ({options})" if options else parent.get("name", "")
    return {**variation, "name": name, "type": "variation"}
