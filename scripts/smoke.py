"""Exercise every primitive against the configured store and print what an agent would see.

Run:  uv run scripts/smoke.py            (reads .env; the Docker store works out of the box)
Exit code is non-zero if any call fails, so this doubles as a post-deploy check.
"""

from __future__ import annotations

import asyncio
import sys
import time

from woo_connector import Settings, WooClient, resources
from woo_connector.errors import WooError
from woo_connector.models import Page


def money(value: str, currency: str) -> str:
    return f"{currency} {value}"


async def run() -> int:
    settings = Settings()
    print(f"store      {settings.woo_base_url}")
    print(f"auth       {'basic' if settings.is_https else 'oauth1'} (mode={settings.woo_auth})")
    print(f"throttle   {settings.woo_rps} rps, burst {settings.woo_burst}, retries {settings.woo_max_retries}\n")

    failures = 0
    async with WooClient(settings) as woo:
        for title, call in [
            ("list_order_statuses", lambda: resources.order_status_totals(woo)),
            ("list_orders(status=on-hold)", lambda: resources.list_orders(woo, status="on-hold", per_page=5)),
            ("search_orders('priya')", lambda: resources.search_orders(woo, "priya", per_page=5)),
            ("list_products(stock_status=outofstock)", lambda: resources.list_products(woo, stock_status="outofstock")),
            ("search_products('tea')", lambda: resources.search_products(woo, "tea", per_page=5)),
            ("get_stock(sku=CB-1L)", lambda: resources.get_stock(woo, sku="CB-1L")),
            ("list_low_stock(threshold=5)", lambda: resources.list_low_stock(woo, threshold=5)),
        ]:
            started = time.perf_counter()
            try:
                result = await call()
            except WooError as exc:
                failures += 1
                print(f"FAIL  {title}\n      {exc}\n")
                continue
            elapsed = (time.perf_counter() - started) * 1000
            print(f"OK    {title}  ({elapsed:.0f} ms)")
            render(result)
            print()

        # Follow a search hit into get_order / get_product so the by-id paths run too.
        try:
            hit = (await resources.search_orders(woo, "priya", per_page=1)).items
            if hit:
                order = await resources.get_order(woo, hit[0].id)
                print(f"OK    get_order({hit[0].id})")
                render(order)
                print()
            product = await resources.get_product(woo, (await resources.list_products(woo, per_page=1)).items[0].id)
            print(f"OK    get_product({product.id})")
            render(product)
            print()
        except WooError as exc:
            failures += 1
            print(f"FAIL  get_order/get_product\n      {exc}\n")

    print("all good" if not failures else f"{failures} call(s) failed")
    return 1 if failures else 0


def render(result: object) -> None:
    if isinstance(result, Page):
        print(f"      page {result.page}/{result.total_pages}, {result.total} total, has_more={result.has_more}")
        items = result.items
    else:
        items = result if isinstance(result, list) else [result]
    for item in items:
        print("      " + line(item))


def line(item: object) -> str:
    cls = type(item).__name__
    if cls == "OrderSummary":
        skus = ", ".join(f"{li.sku}x{li.quantity}" for li in item.line_items)
        return f"#{item.number:<6} {item.status:<10} {money(item.total, item.currency):<12} {item.customer.name:<16} {item.payment_method:<20} [{skus}]"
    if cls == "ProductSummary":
        qty = item.stock_quantity if item.manage_stock else "untracked"
        return f"{item.id:<4} {item.sku:<12} {item.name:<32} {item.price:<6} {item.stock_status:<11} qty={qty}"
    if cls == "StockInfo":
        return f"{item.product_id:<4} {item.sku:<12} {item.name:<36} qty={item.stock_quantity} ({item.stock_status})"
    if cls == "OrderStatusTotal":
        return f"{item.slug:<12} {item.total}"
    return str(item)


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
