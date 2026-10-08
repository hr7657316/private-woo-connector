# What the agent can and cannot do

Scope of this connector, the assumptions it makes, what it does not handle, and what the production
version should look like. Written for whoever decides whether to put it in front of a merchant.

## Can

| Ask the agent… | …and it calls |
|---|---|
| How many orders are on hold / pending / processing? | `list_order_statuses` |
| Show on-hold orders from last week, with totals | `list_orders(status="on-hold", after=…)` |
| Everything about order #45 | `get_order(45)` (or `verbose=true` for the raw payload) |
| Find orders for priya.nair@example.com / "Priya" / #1042 | `search_orders` |
| Which products are out of stock? | `list_products(stock_status="outofstock")` |
| Is KIT-TMB-RED available? How many Cold Brew left? | `get_stock(sku=…)` |
| What's running low (≤ 5 units)? | `list_low_stock(threshold=5)` — includes variations |
| What teas do we sell, with prices? | `search_products("tea")` / `list_products(category=…)` |
| Did customer 7 order before? | `list_orders(customer_id=7)` |
| Who is priya.nair@example.com, where does she ship to? | `list_customers(email=…)` / `search_customers` |

All of this is **read-only**. The seeded key has `permissions = read`, and no tool can write; even a
prompt-injected "cancel order 45" has nothing to call. This is tested, not asserted: the seed contains a product
whose description instructs AI assistants to cancel every on-hold order, `evals/questions.yaml` asks the agent
about that product, and the eval re-reads the store afterwards to confirm nothing changed (`evals/RESULTS.md`).

Onboarding is also covered: `woo-connect` runs WooCommerce's `wc-auth` consent flow, so a merchant grants
read access with one click and no key is ever copied by a human (README → "Connecting a store").

## Cannot (by design, for this version)

- **Write anything**: no status changes, refunds, notes, stock adjustments, coupon creation. The production
  path is write tools behind an explicit human approval step (see below), not "the agent can edit orders".
- **Guest shoppers as customers**: `list_customers` / `get_customer` / `search_customers` cover registered
  accounts only; a guest checkout exists solely on its order (`customer.id = 0`), so "find the person who placed
  #1042" goes through `search_orders`.
- **Reports / analytics** beyond per-status order counts (`/reports/orders/totals`). Revenue-by-month,
  top sellers etc. are not exposed; an agent can approximate from `list_orders` pages but that is slow.
- **Refund, shipment or payment-gateway detail** beyond what the order payload carries
  (`payment_method`, `date_paid`). No Razorpay/UPI transaction lookup.
- **Real-time**: every answer is a fresh REST call. No webhooks, no cache, so the agent is only as live as
  the store's PHP workers allow (see rate limiting).
- **Multiple stores**: one `WOO_BASE_URL` per server process. Multi-merchant Agent Studio deployments run
  one server per store or extend `Settings` to take a store id.
- **Coupons, subscriptions, bookings, memberships** or any other plugin resource.

## Assumptions

- WooCommerce ≥ 3.5 with the `wc/v3` REST namespace enabled and pretty permalinks on (the connector tells
  you if `/wp-json/` routes are missing).
- One REST API key with at least Read permission. Keys are created by a store admin in
  *WooCommerce → Settings → Advanced → REST API*; the connector never creates or rotates keys.
- `WOO_BASE_URL` is the WordPress **home URL** exactly (scheme, host, port). OAuth1 signs it.
- Money is returned as decimal strings in the store currency, as WooCommerce sends them. The agent is told
  the currency per order and should not convert.
- Dates are ISO-8601 **UTC** (`*_gmt` fields). Filters `after`/`before` accept a bare date and are applied to
  `date_created`.
- The store does not require additional authentication (no HTTP auth in front of `/wp-json/`, no
  Cloudflare Access). If it does, add the header in `WooClient` — one line.

## Known limitations

1. **`list_low_stock` is a client-side scan**: WooCommerce has no "stock ≤ N" filter, so the connector pages
   through published products (100/page, max 10 pages = 1000 products) and inspects each; variable products
   cost one extra call. On a 20k-SKU catalogue this is the wrong tool — the fix is a nightly materialised
   view or the `wc-analytics/products/stats` endpoint on stores that have WooCommerce Analytics enabled.
2. **Search semantics are WooCommerce's**: `search` on `/orders` matches order number, billing/shipping
   names, email and item names with SQL `LIKE`; on `/products` it matches title/content/SKU. There is no
   fuzzy matching, so "Pria" will not find "Priya". SKU lookups are exact and case-sensitive.
   Found in the live demo: WooCommerce compares the term with first_name and last_name *separately*, so
   `"Priya Nair"` returns nothing. `search_orders` now retries a multi-word query with its first word and
   the tool description tells the model to prefer email or order number.
3. **Pagination is capped at 100 per page** by WordPress. Totals come from `X-WP-Total`, which some caching
   layers strip; the connector then falls back to the page length.
4. **Order `number` ≠ `id` on stores with sequential-order-number plugins**. Tools take the id;
   `search_orders` finds by number. The summary returns both.
5. **Custom order statuses** added by plugins ("shipped", "awaiting-pickup") are passed through verbatim;
   the connector does not validate them, WooCommerce returns 400 for unknown ones and the agent sees that.
6. **Rate limiting is client-side only.** It protects the merchant's site from the agent, not the agent from
   a limiter it cannot see. When the host does throttle (429/503), the retry policy honours `Retry-After`,
   and after the budget the tool fails with a hint rather than hanging.
7. **Payload trimming drops fields.** Meta data, tax lines, fee lines, coupon lines, full addresses and
   `_links` are not in summaries. `verbose=true` returns everything, at 2.5-4 KB per order.
8. **No idempotent retry on the OAuth1 nonce.** A retried request is re-signed with a fresh nonce and
   timestamp, so WooCommerce's replay check never bites; timestamps older than 15 minutes are rejected,
   so a badly skewed clock on the agent host causes 401s.
9. **Streamable HTTP auth is a single shared bearer token** (`WOO_MCP_TOKEN`), plus DNS-rebinding protection
   pinned to the public hostname. With `WOO_MCP_ALLOW_QUERY_TOKEN=1` the same token is also accepted as
   `?token=` for hosts that cannot send headers (ChatGPT connectors); that is off by default because URLs end up
   in logs and history - the server scrubs `token=` from its own access log, but the right fix is OAuth on the endpoint. Enough for a demo and for sitting behind a platform gateway (Agent Studio, a
   reverse proxy with mTLS/OIDC); a multi-tenant deployment wants per-merchant tokens or OAuth on the MCP endpoint
   itself. stdio remains the default.
10. **Token cost**: a full page of 20 order summaries is ~3k tokens (measured: 12.7 KB JSON). The agent is instructed to filter
    (status, date window, customer) before listing; `per_page` defaults to 20, not 100, for the same reason.

## Security notes

- The repo contains one credential: the **demo store's** read-only key, seeded into a database that only
  exists inside `docker compose` on your laptop. It authenticates nothing else.
- Real credentials live in `.env` (git-ignored) or the host's secret store; `Settings` reads them from
  environment variables, never from source.
- Tool errors never echo the key or secret; the 401 hint names the variables, not their values.
- The server runs with the key's permission, so use a **Read** key — an agent cannot escalate beyond it.

## The production version (what I'd build next, in order)

1. **Host the `wc-auth` callback as a service.** `woo-connect` already runs the consent flow end to end, but
   its callback listener lives on the operator's machine with a self-signed certificate. The platform version
   is the same handler behind a public HTTPS endpoint, storing each merchant's keys in a vault keyed by the
   `user_id` it issued - the request/response shapes do not change.
2. **Webhooks → cache**: subscribe to `order.created/updated` and `product.updated`, keep a per-merchant
   read model, serve `list_*` and `search_*` from it, fall back to REST on miss. Turns a 2-5 s multi-call
   answer into tens of ms and removes the low-stock scan problem.
3. **Write tools behind approval**: `add_order_note`, `update_order_status`, `adjust_stock` with
   `destructiveHint: true`, each requiring an MCP elicitation / human-in-the-loop confirmation and an
   audit log row. Never the default key: a separate Read/Write key issued through step 1.
4. **Observability**: structured logs per tool call (merchant, tool, latency, upstream status, retries),
   a budget per conversation so a runaway agent cannot exhaust a merchant's PHP workers.
5. **Siblings**: `resources/unicommerce.py`, `resources/zoho_inventory.py` behind the same models. The MCP
   layer and the client plumbing (auth selection, throttle, retries, error mapping) do not change.
