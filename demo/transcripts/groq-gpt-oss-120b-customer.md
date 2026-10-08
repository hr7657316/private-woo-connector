model     groq:openai/gpt-oss-120b
question  Find all orders from Priya Nair. Which one is still being processed, what did she buy in it, and is that item in stock?

→ search_orders({"page": 1, "per_page": 20, "query": "Priya Nair"})
← search_orders: {"items": [{"id": 45, "number": "45", "status": "processing", "currency": "INR", "total": "1347.00", "subtotal_discount": "0.00", "shipping_total": "49.00", "to… (2090 chars)
→ get_stock({"sku": "TEA-DRJ-100"})
← get_stock: {"product_id": 11, "name": "Darjeeling First Flush 100g", "sku": "TEA-DRJ-100", "type": "simple", "manage_stock": true, "stock_quantity": 3, "stock_status": "in… (210 chars)
→ get_stock({"sku": "KIT-KLD-6"})
← get_stock: {"product_id": 17, "name": "Kulhad Cups (set of 6)", "sku": "KIT-KLD-6", "type": "simple", "manage_stock": true, "stock_quantity": 2, "stock_status": "instock",… (203 chars)

answer
**Orders for Priya Nair**

| Order # | Status      | Items (SKU) |
|--------|------------|--------------|
| **45** | processing | Darjeeling First Flush 100g **(TEA-DRJ-100)**, Kulhad Cups (set of 6) **(KIT‑KLD‑6)** |
| 34     | completed  | Cold Brew Coffee Concentrate 1L **(CB‑1L)** |
| 28     | completed  | Assam Breakfast Tea 250g **(TEA‑ASM‑250)**, Kulhad Cups (set of 6) **(KIT‑KLD‑6)** |

**Processing order:** **#45**  
**What she bought in it:**  

* Darjeeling First Flush 100g – SKU **TEA‑DRJ‑100** – stock 3 (in stock)  
* Kulhad Cups (set of 6) – SKU **KIT‑KLD‑6** – stock 2 (in stock)

Both items in the processing order are currently **in stock**.

usage     4 model request(s), 7052 in / 798 out tokens
