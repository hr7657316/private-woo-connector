model     groq:qwen/qwen3.8-27b
question  Which orders are on hold, and what is their combined total?

→ list_order_statuses({})
← list_order_statuses: [{"slug": "pending", "name": "Pending payment", "total": 1}, {"slug": "processing", "name": "Processing", "total": 6}, {"slug": "on-hold", "name": "On hold", "t… (443 chars)
→ list_orders({"status": "on-hold"})
← list_orders: {"items": [{"id": 46, "number": "46", "status": "on-hold", "currency": "INR", "total": "1646.00", "subtotal_discount": "0.00", "shipping_total": "49.00", "total… (1993 chars)

answer
There are 3 on-hold orders, all awaiting direct bank transfer:

| Order | Customer | Total | Items |
|-------|----------|-------|-------|
| #46 | Kabir Singh | ₹1,646.00 | Kit Flask 500ml (KIT-FLK-500) ×1, Filter Coffee 200g (COF-FLT-200) ×2 |
| #44 | Meera Joshi | ₹3,047.00 | Chai Lover Gift Box (GFT-CHAI) ×2 — "Corporate gifting - invoice needed" |
| #42 | Sneha Kulkarni | ₹1,547.00 | Coorg Arabica Beans 500g (COF-ARB-500) ×2 |

**Combined total: ₹6,240.00** (₹6,191.00 in goods + ₹49.00 shipping each)

usage     3 model request(s), 7703 in / 269 out tokens
