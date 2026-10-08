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

All of this is **read-only**. The seeded key has `permissions = read`, and no tool can write; even a
prompt-injected "cancel order 45" has nothing to call.

## Cannot (by design, for this version)

- **Write anything**: no status changes, refunds, notes, stock adjustments, coupon creation. The production
  path is write tools behind an explicit human approval step (see below), not "the agent can edit orders".
- **Customers as a resource**: there is no `list_customers`/`get_customer`. Customer facts arrive attached to
  orders. (A `customers.py` sibling is a 30-minute addition; left out to keep the review surface small.)
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
9. **Streamable HTTP transport has no auth of its own.** It is meant to sit behind the host platform's
   gateway (Agent Studio, a reverse proxy with mTLS/OIDC), not on the public internet. stdio is the default.
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

1. **Merchant onboarding via `wc-auth`** — WooCommerce's built-in consent flow:
   redirect the merchant to `https://store/wc-auth/v1/authorize?app_name=Agent+Studio&scope=read&user_id=<merchant>&return_url=…&callback_url=…`,
   WooCommerce POSTs `consumer_key`/`consumer_secret` to the callback, we store them per merchant in a
   vault. This replaces "paste your key" with a two-click OAuth-like grant and fixes the key-handling
   question for a multi-tenant platform. `auth.py` needs no change: it already handles the resulting key.
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
