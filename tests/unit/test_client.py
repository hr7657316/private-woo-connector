import httpx
import pytest
import respx

from woo_connector.client import WooClient
from woo_connector.errors import AuthError, BadRequestError, NotFoundError, UpstreamError

from tests.conftest import make_settings

API = "https://shop.example.com/wp-json/wc/v3"


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeper() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
async def woo(settings, sleeper):
    async with WooClient(settings, sleep=sleeper) as client:
        yield client


# -- happy path -----------------------------------------------------------------------------


@respx.mock
async def test_get_page_reads_wordpress_pagination_headers(woo):
    route = respx.get(f"{API}/orders").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1}, {"id": 2}],
            headers={"X-WP-Total": "57", "X-WP-TotalPages": "29", "Content-Type": "application/json"},
        )
    )
    items, meta = await woo.get_page("orders", {"status": "on-hold", "per_page": 2})
    assert [i["id"] for i in items] == [1, 2]
    assert (meta.page, meta.per_page, meta.total, meta.total_pages, meta.has_more) == (1, 2, 57, 29, True)
    sent = route.calls.last.request
    assert sent.url.params["status"] == "on-hold"
    assert sent.url.params["page"] == "1"
    assert sent.headers["Authorization"].startswith("Basic ")


@respx.mock
async def test_none_params_are_dropped_and_per_page_is_capped(woo):
    route = respx.get(f"{API}/products").mock(return_value=httpx.Response(200, json=[], headers=_json))
    await woo.get_page("products", {"status": None, "sku": "CB-1L", "per_page": 500})
    params = route.calls.last.request.url.params
    assert "status" not in params
    assert params["sku"] == "CB-1L"
    assert params["per_page"] == "100"


@respx.mock
async def test_iter_pages_stops_when_no_more(woo):
    respx.get(f"{API}/products", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json=[{"id": 1}], headers={**_json, "X-WP-TotalPages": "2"})
    )
    respx.get(f"{API}/products", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"id": 2}], headers={**_json, "X-WP-TotalPages": "2"})
    )
    pages = [p async for p in woo.iter_pages("products")]
    assert pages == [[{"id": 1}], [{"id": 2}]]


# -- retries ----------------------------------------------------------------------------


@respx.mock
async def test_429_is_retried_after_retry_after(woo, sleeper):
    route = respx.get(f"{API}/orders/1")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"id": 1}, headers=_json),
    ]
    assert (await woo.get_json("orders/1")) == {"id": 1}
    assert route.call_count == 2
    assert sleeper.calls == [2.0]


@respx.mock
async def test_5xx_exhausts_retries_then_raises_upstream(woo, sleeper):
    route = respx.get(f"{API}/orders").mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(UpstreamError) as exc:
        await woo.get("orders")
    assert route.call_count == 3  # 1 + max_retries(2)
    assert len(sleeper.calls) == 2
    assert exc.value.status == 503


@respx.mock
async def test_network_errors_are_retried(woo, sleeper):
    route = respx.get(f"{API}/orders")
    route.side_effect = [httpx.ConnectTimeout("slow"), httpx.Response(200, json=[], headers=_json)]
    await woo.get("orders")
    assert route.call_count == 2
    assert len(sleeper.calls) == 1


@respx.mock
async def test_network_error_after_budget_has_a_hint(woo):
    respx.get(f"{API}/orders").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UpstreamError, match="WOO_BASE_URL"):
        await woo.get("orders")


# -- error mapping ----------------------------------------------------------------------


@respx.mock
async def test_401_maps_to_auth_error_with_actionable_hint(woo):
    respx.get(f"{API}/orders").mock(
        return_value=httpx.Response(
            401,
            json={"code": "woocommerce_rest_cannot_view", "message": "Sorry, you cannot list resources.", "data": {"status": 401}},
        )
    )
    with pytest.raises(AuthError) as exc:
        await woo.get("orders")
    assert exc.value.code == "woocommerce_rest_cannot_view"
    assert "WOO_CONSUMER_KEY" in str(exc.value)
    assert "Basic" in str(exc.value)


@respx.mock
async def test_401_hint_mentions_oauth1_for_http_stores(sleeper):
    settings = make_settings(woo_base_url="http://localhost:8080")
    respx.get("http://localhost:8080/wp-json/wc/v3/orders").mock(return_value=httpx.Response(401, json={"code": "x"}))
    async with WooClient(settings, sleep=sleeper) as woo:
        with pytest.raises(AuthError, match="OAuth1"):
            await woo.get("orders")


@respx.mock
async def test_404_maps_to_not_found(woo):
    respx.get(f"{API}/orders/999").mock(
        return_value=httpx.Response(404, json={"code": "woocommerce_rest_shop_order_invalid_id", "message": "Invalid ID."})
    )
    with pytest.raises(NotFoundError, match="Invalid ID"):
        await woo.get("orders/999")


@respx.mock
async def test_no_route_404_hints_at_permalinks(woo):
    respx.get(f"{API}/orders").mock(return_value=httpx.Response(404, json={"code": "rest_no_route", "message": "No route"}))
    with pytest.raises(NotFoundError, match="permalinks"):
        await woo.get("orders")


@respx.mock
async def test_400_maps_to_bad_request(woo):
    respx.get(f"{API}/orders").mock(
        return_value=httpx.Response(400, json={"code": "rest_invalid_param", "message": "Invalid parameter(s): status"})
    )
    with pytest.raises(BadRequestError, match="status"):
        await woo.get("orders")


@respx.mock
async def test_html_body_is_an_upstream_error(woo):
    respx.get(f"{API}/orders").mock(return_value=httpx.Response(200, text="<html>maintenance</html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(UpstreamError, match="non-JSON"):
        await woo.get("orders")


_json = {"Content-Type": "application/json"}
