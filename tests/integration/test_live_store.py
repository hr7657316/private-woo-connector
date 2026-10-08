"""End-to-end tests against the seeded Docker store (docker/docker-compose.yml).

They are skipped automatically when http://localhost:8080 is not answering, so `uv run pytest`
stays green on a laptop without Docker while still proving the real thing when the store is up.
This is also where the OAuth1 signing is proven against real WooCommerce: the unit test pins
the algorithm, this test shows the store accepts it - and rejects a wrong secret.
"""

from __future__ import annotations

import httpx
import pytest

from woo_connector import AuthError, Settings, WooClient, resources

STORE = "http://localhost:8080"
DEMO_KEY = "ck_0123456789abcdef0123456789abcdef01234567"
DEMO_SECRET = "cs_fedcba9876543210fedcba9876543210fedcba98"


def store_is_up() -> bool:
    try:
        return httpx.get(f"{STORE}/wp-json/wc/v3", timeout=2).status_code in (200, 401)
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not store_is_up(), reason="Docker WooCommerce store is not running on :8080"),
]


def live_settings(**overrides) -> Settings:
    values = dict(
        woo_base_url=STORE,
        woo_consumer_key=DEMO_KEY,
        woo_consumer_secret=DEMO_SECRET,
        woo_rps=20,
        woo_max_retries=1,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
async def woo():
    async with WooClient(live_settings()) as client:
        yield client


async def test_oauth1_signature_is_accepted_by_woocommerce(woo):
    totals = await resources.order_status_totals(woo)
    assert {t.slug for t in totals} >= {"processing", "on-hold", "completed"}


async def test_wrong_secret_is_rejected():
    """Proves the signature is actually verified server-side (not silently ignored)."""
    async with WooClient(live_settings(woo_consumer_secret="cs_wrong")) as woo:
        with pytest.raises(AuthError, match="OAuth1"):
            await resources.order_status_totals(woo)


async def test_basic_auth_is_refused_on_plain_http():
    """Documents why auto mode picks OAuth1 for http:// stores."""
    async with WooClient(live_settings(woo_auth="basic")) as woo:
        with pytest.raises(AuthError):
            await resources.order_status_totals(woo)


async def test_seeded_orders_by_status(woo):
    on_hold = await resources.list_orders(woo, status="on-hold")
    assert on_hold.total == 3
    assert {o.payment_method for o in on_hold.items} == {"Direct bank transfer"}
    assert all(o.currency == "INR" for o in on_hold.items)


async def test_search_and_get_order_roundtrip(woo):
    hits = await resources.search_orders(woo, "priya.nair@example.com")
    assert hits.total == 3
    order = await resources.get_order(woo, hits.items[0].id)
    assert order.customer.email == "priya.nair@example.com"
    assert order.shipping_city == "Kochi"
    assert order.line_items and all(li.sku for li in order.line_items)
    raw = await resources.get_order(woo, hits.items[0].id, verbose=True)
    assert raw["id"] == order.id and "meta_data" in raw


async def test_date_window_filter(woo):
    recent = await resources.list_orders(woo, after="2000-01-01", per_page=100)
    assert recent.total == 20


async def test_stock_lookups(woo):
    cold_brew = await resources.get_stock(woo, sku="CB-1L")
    assert (cold_brew.manage_stock, cold_brew.stock_quantity, cold_brew.stock_status) == (True, 5, "instock")

    honey = await resources.get_stock(woo, sku="SWT-HNY-350")
    assert honey.manage_stock is False and honey.stock_quantity is None

    red = await resources.get_stock(woo, sku="KIT-TMB-RED")
    assert red.type == "variation" and red.stock_quantity == 1


async def test_low_stock_scan_covers_products_and_variations(woo):
    low = await resources.list_low_stock(woo, threshold=5)
    skus = {s.sku for s in low}
    assert {"TEA-DRJ-100", "CB-1L", "KIT-KLD-6", "TEA-NLG-100", "KIT-STR-BR", "KIT-TMB-RED", "KIT-TMB-GRN"} <= skus
    assert "SWT-HNY-350" not in skus  # untracked stock is not "low"
    assert [s.stock_quantity for s in low] == sorted(s.stock_quantity for s in low)


async def test_out_of_stock_products(woo):
    oos = await resources.list_products(woo, stock_status="outofstock")
    assert {p.sku for p in oos.items} >= {"TEA-NLG-100", "KIT-STR-BR"}


async def test_customers(woo):
    everyone = await resources.list_customers(woo, per_page=50)
    assert everyone.total == 8
    priya = await resources.search_customers(woo, "priya")
    assert [c.email for c in priya.items] == ["priya.nair@example.com"]
    one = await resources.get_customer(woo, priya.items[0].id)
    assert (one.name, one.city, one.is_paying_customer) == ("Priya Nair", "Kochi", True)


async def test_pagination_meta(woo):
    page1 = await resources.list_products(woo, per_page=4)
    assert page1.total_pages >= 4 and page1.has_more
    page2 = await resources.list_products(woo, per_page=4, page=2)
    assert {p.id for p in page1.items}.isdisjoint({p.id for p in page2.items})
