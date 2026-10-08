model     groq:openai/gpt-oss-120b
question  Which orders are on hold, and what is their combined total?

→ list_order_statuses({})
← list_order_statuses: [{"slug": "pending", "name": "Pending payment", "total": 1}, {"slug": "processing", "name": "Processing", "total": 6}, {"slug": "on-hold", "name": "On hold", "t… (443 chars)
→ list_orders({"page": 1, "per_page": 100, "status": "on-hold"})
← list_orders: {"items": [{"id": 46, "number": "46", "status": "on-hold", "currency": "INR", "total": "1646.00", "subtotal_discount": "0.00", "shipping_total": "49.00", "total… (1994 chars)

answer
**On‑hold orders**

| Order # | Total (INR) |
|---------|-------------|
| #46 | 1,646.00 |
| #44 | 3,047.00 |
| #42 | 1,547.00 |

**Combined total:** **6,240.00 INR**.

usage     3 model request(s), 4416 in / 291 out tokens
