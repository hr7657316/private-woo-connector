"""MCP server exposing the WooCommerce read primitives as tools.

This is the only module that imports ``mcp``. Any MCP-capable host - Claude Desktop/Code,
Codex CLI, Gemini CLI, Cursor, an OpenAI Agents SDK or pydantic-ai script - launches
``woo-mcp`` over stdio (or connects over Streamable HTTP) and gets the same nine tools.

Run:  ``woo-mcp``  or  ``woo-mcp --transport streamable-http --port 8765``
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from woo_connector import resources
from woo_connector.client import WooClient
from woo_connector.config import Settings
from woo_connector.errors import WooError

log = logging.getLogger("woo_connector")

INSTRUCTIONS = """\
Read-only access to one WooCommerce store: orders and products/inventory.
Money values are strings in the store currency (see each order's `currency`).
Dates are ISO-8601 in UTC. Lists are paginated: check `has_more` and pass `page` to continue.
Nothing here can modify the store - there are no create/update/delete tools.
Start with `list_order_statuses` to learn which statuses exist and how many orders are in each.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

server = MCPServer("woocommerce", version="0.1.0", instructions=INSTRUCTIONS)

# -- client lifecycle ---------------------------------------------------------------------------

_client: WooClient | None = None


async def get_client() -> WooClient:
    """Lazily build the client so a misconfigured env fails on first tool call with a clear message."""
    global _client
    if _client is None:
        try:
            _client = WooClient(Settings())
        except ValidationError as exc:
            missing = ", ".join(str(e["loc"][0]).upper() for e in exc.errors())
            raise ToolError(f"connector is not configured: {missing}. Copy .env.example to .env or export the WOO_* variables.") from exc
    return _client


async def reset_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


T = TypeVar("T")


async def _call(fn: Callable[..., Awaitable[T]], **kwargs: Any) -> T:
    """Run a primitive and translate connector errors into ToolErrors the model can act on."""
    woo = await get_client()
    try:
        return await fn(woo, **kwargs)
    except WooError as exc:
        raise ToolError(str(exc)) from exc


def _dump(result: Any) -> Any:
    return result.model_dump() if hasattr(result, "model_dump") else result


# -- orders -----------------------------------------------------------------------------------

Pagination = Annotated[int, Field(ge=1, description="1-based page number")]
PerPage = Annotated[int, Field(ge=1, le=100, description="items per page (max 100)")]


@server.tool(annotations=READ_ONLY)
async def list_orders(
    status: Annotated[
        str | None,
        Field(description="Filter by status: pending, processing, on-hold, completed, cancelled, refunded, failed (or any)"),
    ] = None,
    after: Annotated[str | None, Field(description="Created on/after this date or ISO datetime, e.g. 2026-10-01")] = None,
    before: Annotated[str | None, Field(description="Created on/before this date or ISO datetime")] = None,
    customer_id: Annotated[int | None, Field(description="Only orders by this customer id")] = None,
    page: Pagination = 1,
    per_page: PerPage = 20,
) -> dict[str, Any]:
    """List orders newest-first, with optional status / date-range / customer filters. Returns trimmed
    summaries (id, number, status, total, customer, line items). Use get_order for everything else."""
    return _dump(
        await _call(
            resources.list_orders,
            status=status,
            after=after,
            before=before,
            customer_id=customer_id,
            page=page,
            per_page=per_page,
        )
    )


@server.tool(annotations=READ_ONLY)
async def get_order(
    order_id: Annotated[int, Field(description="Numeric order id")],
    verbose: Annotated[bool, Field(description="true = raw WooCommerce payload (large); false = summary")] = False,
) -> dict[str, Any]:
    """Fetch one order by id. The summary has customer, totals, payment method, shipping city and line items."""
    return _dump(await _call(resources.get_order, order_id=order_id, verbose=verbose))


@server.tool(annotations=READ_ONLY)
async def search_orders(
    query: Annotated[str, Field(min_length=1, description="Order number, customer name, email, or product name")],
    page: Pagination = 1,
    per_page: PerPage = 20,
) -> dict[str, Any]:
    """Free-text search across orders (number, billing/shipping name, email, item names). WooCommerce matches
    first and last name separately, so a full name is automatically retried as its first word; prefer the
    customer's email or order number when you have it."""
    return _dump(await _call(resources.search_orders, query=query, page=page, per_page=per_page))


@server.tool(annotations=READ_ONLY)
async def list_order_statuses() -> list[dict[str, Any]]:
    """Every order status the store knows, with the number of orders currently in each. Good first call."""
    return [s.model_dump() for s in await _call(resources.order_status_totals)]


# -- products / inventory -------------------------------------------------------------------


@server.tool(annotations=READ_ONLY)
async def list_products(
    status: Annotated[str | None, Field(description="publish, draft, pending, private (default: all)")] = None,
    stock_status: Annotated[str | None, Field(description="instock, outofstock, onbackorder")] = None,
    category: Annotated[int | None, Field(description="Category id")] = None,
    product_type: Annotated[str | None, Field(description="simple, variable, grouped, external")] = None,
    sku: Annotated[str | None, Field(description="Exact SKU")] = None,
    page: Pagination = 1,
    per_page: PerPage = 20,
) -> dict[str, Any]:
    """List products with price, stock status and tracked quantity. Variable products list their variation ids."""
    return _dump(
        await _call(
            resources.list_products,
            status=status,
            stock_status=stock_status,
            category=category,
            product_type=product_type,
            sku=sku,
            page=page,
            per_page=per_page,
        )
    )


@server.tool(annotations=READ_ONLY)
async def get_product(
    product_id: Annotated[int, Field(description="Numeric product or variation id")],
    verbose: Annotated[bool, Field(description="true = raw WooCommerce payload")] = False,
) -> dict[str, Any]:
    """Fetch one product (or variation) by id."""
    return _dump(await _call(resources.get_product, product_id=product_id, verbose=verbose))


@server.tool(annotations=READ_ONLY)
async def search_products(
    query: Annotated[str, Field(min_length=1, description="Words from the product name, description or SKU")],
    page: Pagination = 1,
    per_page: PerPage = 20,
) -> dict[str, Any]:
    """Free-text product search."""
    return _dump(await _call(resources.search_products, query=query, page=page, per_page=per_page))


@server.tool(annotations=READ_ONLY)
async def get_stock(
    product_id: Annotated[int | None, Field(description="Product or variation id")] = None,
    sku: Annotated[str | None, Field(description="Exact SKU (used when product_id is not given)")] = None,
) -> dict[str, Any]:
    """Current stock for one product or variation: tracked?, quantity, status, low-stock threshold, backorders."""
    return _dump(await _call(resources.get_stock, product_id=product_id, sku=sku))


@server.tool(annotations=READ_ONLY)
async def list_low_stock(
    threshold: Annotated[int, Field(ge=0, description="Report items with quantity <= this")] = 5,
    limit: Annotated[int, Field(ge=1, le=200, description="Max items to return")] = 50,
) -> list[dict[str, Any]]:
    """Products and variations whose tracked quantity is at or below the threshold, lowest first.
    Scans the catalogue client-side (up to 1000 products), so it is slower than the other tools."""
    return [s.model_dump() for s in await _call(resources.list_low_stock, threshold=threshold, limit=limit)]


# -- entry point ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="woo-mcp", description="WooCommerce read-only MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    # stdout is the MCP channel on stdio; everything else must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings()
    except ValidationError as exc:
        missing = ", ".join(str(e["loc"][0]).upper() for e in exc.errors())
        sys.exit(f"woo-mcp: missing settings: {missing}. Copy .env.example to .env or export the WOO_* variables.")
    log.info("store=%s auth=%s rps=%s transport=%s", settings.woo_base_url, settings.woo_auth, settings.woo_rps, args.transport)

    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
