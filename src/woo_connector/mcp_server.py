"""MCP server exposing the WooCommerce read primitives as tools.

This is the only module that imports ``mcp``. Any MCP-capable host - Claude Desktop/Code,
Codex CLI, Gemini CLI, Cursor, an OpenAI Agents SDK or pydantic-ai script - launches
``woo-mcp`` over stdio (or connects over Streamable HTTP) and gets the same nine tools.

Run:  ``woo-mcp``  or  ``woo-mcp --transport streamable-http --port 8765``
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
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
    global _client, _calls_made
    if _client is not None:
        await _client.aclose()
    _client = None
    _calls_made = 0


T = TypeVar("T")

_calls_made = 0


async def _call(fn: Callable[..., Awaitable[T]], **kwargs: Any) -> T:
    """Run a primitive and translate connector errors into ToolErrors the model can act on.

    Every call emits one structured log line (stderr, JSON) - tool, latency, outcome, upstream status -
    and counts against WOO_MAX_CALLS_PER_SESSION so a looping agent cannot exhaust a merchant's PHP workers.
    """
    global _calls_made
    woo = await get_client()
    budget = woo.settings.woo_max_calls_per_session
    if budget and _calls_made >= budget:
        raise ToolError(
            f"this session's budget of {budget} tool calls is used up; start a new session or raise WOO_MAX_CALLS_PER_SESSION"
        )
    _calls_made += 1
    started = time.perf_counter()
    record: dict[str, Any] = {"event": "tool_call", "tool": fn.__name__, "call": _calls_made}
    try:
        result = await fn(woo, **kwargs)
    except WooError as exc:
        record |= {"ok": False, "status": exc.status, "code": exc.code, "ms": round((time.perf_counter() - started) * 1000)}
        log.info(json.dumps(record))
        raise ToolError(str(exc)) from exc
    record |= {"ok": True, "ms": round((time.perf_counter() - started) * 1000)}
    log.info(json.dumps(record))
    return result


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


# -- customers ------------------------------------------------------------------------------


@server.tool(annotations=READ_ONLY)
async def list_customers(
    email: Annotated[str | None, Field(description="Exact email address")] = None,
    role: Annotated[str | None, Field(description="WordPress role, default customer")] = None,
    page: Pagination = 1,
    per_page: PerPage = 20,
) -> dict[str, Any]:
    """Registered customer accounts (name, email, phone, city, paying?). Guest checkouts are not customers -
    look them up through search_orders instead."""
    return _dump(await _call(resources.list_customers, email=email, role=role, page=page, per_page=per_page))


@server.tool(annotations=READ_ONLY)
async def get_customer(
    customer_id: Annotated[int, Field(description="Numeric customer id (the customer.id on an order)")],
    verbose: Annotated[bool, Field(description="true = raw WooCommerce payload")] = False,
) -> dict[str, Any]:
    """Fetch one registered customer by id."""
    return _dump(await _call(resources.get_customer, customer_id=customer_id, verbose=verbose))


@server.tool(annotations=READ_ONLY)
async def search_customers(
    query: Annotated[str, Field(min_length=1, description="Words from the name, username or email")],
    page: Pagination = 1,
    per_page: PerPage = 20,
) -> dict[str, Any]:
    """Free-text search over registered customers."""
    return _dump(await _call(resources.search_customers, query=query, page=page, per_page=per_page))


# -- entry point ----------------------------------------------------------------------------


def build_http_app(*, allowed_hosts: list[str], bearer_token: str | None):
    """Starlette app for Streamable HTTP: MCP at /mcp, unauthenticated GET /healthz for platform probes.

    ``allowed_hosts`` feeds the SDK's DNS-rebinding protection (``*`` disables it - fine behind a platform
    proxy, never on a bare host). ``bearer_token`` is the one piece of auth the SDK does not do for us: when
    set, every request except /healthz must carry ``Authorization: Bearer <token>``.
    """
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import JSONResponse, PlainTextResponse

    if "*" in allowed_hosts:
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    else:
        # The SDK compares the raw Host header; accept each name with or without a port ("host:*").
        security = TransportSecuritySettings(allowed_hosts=[h for host in allowed_hosts for h in (host, f"{host}:*")])
    inner = server.streamable_http_app(transport_security=security)
    expected_header = f"Bearer {bearer_token}".encode() if bearer_token else None
    expected_query = f"token={bearer_token}".encode() if bearer_token else None

    def authorised(scope) -> bool:
        if expected_header is None:
            return True
        if dict(scope["headers"]).get(b"authorization", b"") == expected_header:
            return True
        # Hosts that cannot send custom headers (ChatGPT connectors offer only OAuth or none) may put the
        # token in the URL instead: https://host/mcp?token=…  Same secret, same check.
        return any(part == expected_query for part in scope.get("query_string", b"").split(b"&"))

    async def app(scope, receive, send):
        if scope["type"] == "http":
            if scope["path"] == "/healthz":
                return await PlainTextResponse("ok")(scope, receive, send)
            if not authorised(scope):
                return await JSONResponse(
                    {"error": "unauthorized", "hint": "send Authorization: Bearer <WOO_MCP_TOKEN> or append ?token=<WOO_MCP_TOKEN>"}, 401
                )(scope, receive, send)
        await inner(scope, receive, send)

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="woo-mcp", description="WooCommerce read-only MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allowed-hosts",
        default="127.0.0.1,localhost",
        help="comma-separated Host values accepted over HTTP (DNS-rebinding protection); '*' disables the check",
    )
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
        return

    import os

    import uvicorn

    token = os.environ.get("WOO_MCP_TOKEN") or None
    hosts = [h.strip() for h in args.allowed_hosts.split(",") if h.strip()]
    log.info("streamable-http on %s:%s path=/mcp auth=%s allowed_hosts=%s", args.host, args.port, "bearer" if token else "none", hosts)
    if not token and args.host not in ("127.0.0.1", "localhost"):
        log.warning("serving on %s without WOO_MCP_TOKEN - anyone who can reach this port can read the store", args.host)
    uvicorn.run(build_http_app(allowed_hosts=hosts, bearer_token=token), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
