"""Read primitives. Each function takes a ``WooClient`` and returns models from ``woo_connector.models``.

They are plain async functions on purpose: the MCP layer, the smoke script and the tests all
call the same code, and a second tool (Unicommerce, Zoho...) would add a sibling module here.
"""

from woo_connector.resources.customers import get_customer, list_customers, search_customers
from woo_connector.resources.orders import get_order, list_orders, order_status_totals, search_orders
from woo_connector.resources.products import (
    get_product,
    get_stock,
    list_low_stock,
    list_products,
    search_products,
)

__all__ = [
    "get_customer",
    "get_order",
    "get_product",
    "get_stock",
    "list_customers",
    "list_low_stock",
    "list_orders",
    "list_products",
    "order_status_totals",
    "search_customers",
    "search_orders",
    "search_products",
]
