import httpx
import pytest
import respx

from woo_connector import resources
from woo_connector.client import WooClient
from woo_connector.errors import BadRequestError, NotFoundError
from woo_connector.resources.orders import datetime_bound, normalize_status

API = "https://shop.example.com/wp-json/wc/v3"
JSON = {"Content-Type": "application/json"}


def ok(payload, **headers):
    return httpx.Response(200, json=payload, headers={**JSON, **headers})


@pytest.fixture
async def woo(settings):
    async with WooClient(settings) as client:
        yield client


# -- helpers --------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["on-hold", "On Hold", "on_hold", "wc-on-hold", " ON-HOLD "])
def test_normalize_status_accepts_human_spellings(raw):
    assert normalize_status(raw) == "on-hold"


def test_datetime_bound_expands_bare_dates():
    assert datetime_bound("2026-10-01") == "2026-10-01T00:00:00"
    assert datetime_bound("2026-10-01", end=True) == "2026-10-01T23:59:59"
    assert datetime_bound("2026-10-01T10:00:00") == "2026-10-01T10:00:00"
    assert datetime_bound(None) is None


# -- orders ---------------------------------------------------------------------------------


@respx.mock
async def test_list_orders_maps_filters_and_trims(woo, sample_order):
    route = respx.get(f"{API}/orders").mock(return_value=ok([sample_order], **{"X-WP-Total": "1", "X-WP-TotalPages": "1"}))
    page = await resources.list_orders(woo, status="On Hold", after="2026-10-01", customer_id=7, per_page=5)
    params = route.calls.last.request.url.params
    assert params["status"] == "on-hold"
    assert params["after"] == "2026-10-01T00:00:00"
    assert params["customer"] == "7"
    assert "before" not in params
    assert page.total == 1 and page.has_more is False
    assert page.items[0].customer.name == "Priya Nair"


@respx.mock
async def test_get_order_verbose_returns_raw(woo, sample_order):
    respx.get(f"{API}/orders/1042").mock(return_value=ok(sample_order))
    summary = await resources.get_order(woo, 1042)
    raw = await resources.get_order(woo, 1042, verbose=True)
    assert summary.id == 1042 and "meta_data" not in summary.model_dump()
    assert raw["meta_data"]


@respx.mock
async def test_search_orders_passes_query(woo, sample_order):
    route = respx.get(f"{API}/orders").mock(return_value=ok([sample_order]))
    await resources.search_orders(woo, "  priya ")
    assert route.calls.last.request.url.params["search"] == "priya"


@respx.mock
async def test_search_orders_full_name_falls_back_to_first_word(woo, sample_order):
    """WooCommerce matches first/last name separately, so 'Priya Nair' finds nothing; retry with 'Priya'."""
    route = respx.get(f"{API}/orders")
    route.side_effect = [
        ok([], **{"X-WP-Total": "0", "X-WP-TotalPages": "0"}),
        ok([sample_order], **{"X-WP-Total": "1", "X-WP-TotalPages": "1"}),
    ]
    page = await resources.search_orders(woo, "Priya Nair")
    assert [c.request.url.params["search"] for c in route.calls] == ["Priya Nair", "Priya"]
    assert page.total == 1 and page.items[0].customer.name == "Priya Nair"


@respx.mock
async def test_search_orders_single_word_does_not_retry(woo):
    route = respx.get(f"{API}/orders").mock(return_value=ok([], **{"X-WP-Total": "0", "X-WP-TotalPages": "0"}))
    page = await resources.search_orders(woo, "nobody")
    assert route.call_count == 1 and page.total == 0


@respx.mock
async def test_order_status_totals(woo):
    respx.get(f"{API}/reports/orders/totals").mock(
        return_value=ok([{"slug": "on-hold", "name": "On hold", "total": 3}, {"slug": "completed", "name": "Completed", "total": 12}])
    )
    totals = await resources.order_status_totals(woo)
    assert [(t.slug, t.total) for t in totals] == [("on-hold", 3), ("completed", 12)]


# -- products -------------------------------------------------------------------------------


@respx.mock
async def test_list_products_maps_filters(woo, sample_product):
    route = respx.get(f"{API}/products").mock(return_value=ok([sample_product]))
    page = await resources.list_products(woo, stock_status="instock", product_type="simple", category=3)
    params = route.calls.last.request.url.params
    assert params["stock_status"] == "instock"
    assert params["type"] == "simple"
    assert params["category"] == "3"
    assert page.items[0].sku == "CB-1L"


@respx.mock
async def test_get_stock_by_sku_uses_products_filter(woo, sample_product):
    route = respx.get(f"{API}/products").mock(return_value=ok([sample_product]))
    stock = await resources.get_stock(woo, sku="CB-1L")
    assert route.calls.last.request.url.params["sku"] == "CB-1L"
    assert stock.stock_quantity == 3


@respx.mock
async def test_get_stock_unknown_sku_is_not_found(woo):
    respx.get(f"{API}/products").mock(return_value=ok([]))
    with pytest.raises(NotFoundError, match="SKU"):
        await resources.get_stock(woo, sku="NOPE")


async def test_get_stock_requires_an_identifier(woo):
    with pytest.raises(BadRequestError):
        await resources.get_stock(woo)


@respx.mock
async def test_list_low_stock_scans_products_and_variations(woo, sample_product):
    low = {**sample_product, "id": 11, "stock_quantity": 2}
    fine = {**sample_product, "id": 12, "sku": "OK", "stock_quantity": 40}
    untracked = {**sample_product, "id": 13, "sku": "UNT", "manage_stock": False, "stock_quantity": None}
    variable = {**sample_product, "id": 20, "sku": "TOTE", "type": "variable", "manage_stock": False, "stock_quantity": None, "name": "Tote Bag"}
    respx.get(f"{API}/products").mock(return_value=ok([low, fine, untracked, variable], **{"X-WP-TotalPages": "1"}))
    respx.get(f"{API}/products/20/variations").mock(
        return_value=ok(
            [
                {"id": 21, "sku": "TOTE-RED", "manage_stock": True, "stock_quantity": 0, "stock_status": "outofstock", "attributes": [{"name": "Colour", "option": "Red"}]},
                {"id": 22, "sku": "TOTE-BLU", "manage_stock": "parent", "stock_quantity": None, "stock_status": "instock", "attributes": [{"name": "Colour", "option": "Blue"}]},
            ]
        )
    )
    items = await resources.list_low_stock(woo, threshold=5)
    assert [(s.product_id, s.stock_quantity, s.name) for s in items] == [
        (21, 0, "Tote Bag (Red)"),
        (11, 2, "Cold Brew Coffee 1L"),
    ]
    assert items[0].type == "variation"


# -- customers ------------------------------------------------------------------------------

CUSTOMER = {
    "id": 7,
    "date_created": "2026-09-01T10:00:00",
    "date_created_gmt": "2026-09-01T04:30:00",
    "email": "priya.nair@example.com",
    "first_name": "Priya",
    "last_name": "Nair",
    "role": "customer",
    "username": "priya",
    "is_paying_customer": True,
    "billing": {"city": "Kochi", "phone": "9800000001", "country": "IN"},
    "shipping": {"city": "Kochi", "country": "IN"},
    "avatar_url": "https://example.com/a.png",
    "meta_data": [],
}


@respx.mock
async def test_list_customers_by_email(woo):
    route = respx.get(f"{API}/customers").mock(return_value=ok([CUSTOMER], **{"X-WP-Total": "1", "X-WP-TotalPages": "1"}))
    page = await resources.list_customers(woo, email=" priya.nair@example.com ")
    assert route.calls.last.request.url.params["email"] == "priya.nair@example.com"
    customer = page.items[0]
    assert (customer.name, customer.phone, customer.city, customer.is_paying_customer) == ("Priya Nair", "9800000001", "Kochi", True)
    assert customer.date_created == "2026-09-01T04:30:00"
    assert "avatar_url" not in customer.model_dump()


@respx.mock
async def test_get_customer_and_search(woo):
    respx.get(f"{API}/customers/7").mock(return_value=ok(CUSTOMER))
    route = respx.get(f"{API}/customers").mock(return_value=ok([CUSTOMER]))
    assert (await resources.get_customer(woo, 7)).email == "priya.nair@example.com"
    assert (await resources.get_customer(woo, 7, verbose=True))["username"] == "priya"
    await resources.search_customers(woo, "nair")
    assert route.calls.last.request.url.params["search"] == "nair"


@respx.mock
async def test_list_low_stock_respects_limit(woo, sample_product):
    products = [{**sample_product, "id": i, "stock_quantity": 1} for i in range(1, 6)]
    respx.get(f"{API}/products").mock(return_value=ok(products, **{"X-WP-TotalPages": "1"}))
    assert len(await resources.list_low_stock(woo, threshold=5, limit=2)) == 2
