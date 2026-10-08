import base64
import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from woo_connector.auth import BasicAuth, OAuth1Auth, select_auth, signature_base_string
from woo_connector.errors import ConfigError


def run_flow(auth: httpx.Auth, request: httpx.Request) -> httpx.Request:
    return next(auth.auth_flow(request))


# -- scheme selection ---------------------------------------------------------------------


def test_auto_picks_basic_for_https():
    assert isinstance(select_auth("https://shop.example.com", "ck", "cs"), BasicAuth)


def test_auto_picks_oauth1_for_http():
    assert isinstance(select_auth("http://localhost:8080", "ck", "cs"), OAuth1Auth)


@pytest.mark.parametrize(("mode", "cls"), [("basic", BasicAuth), ("oauth1", OAuth1Auth)])
def test_explicit_mode_overrides_scheme(mode, cls):
    assert isinstance(select_auth("http://localhost:8080", "ck", "cs", mode), cls)
    assert isinstance(select_auth("https://shop.example.com", "ck", "cs", mode), cls)


def test_missing_credentials_is_a_config_error():
    with pytest.raises(ConfigError, match="WOO_CONSUMER_KEY"):
        select_auth("https://shop.example.com", "", "cs")


# -- basic --------------------------------------------------------------------------------


def test_basic_sets_authorization_header():
    req = run_flow(BasicAuth("ck_abc", "cs_xyz"), httpx.Request("GET", "https://shop.example.com/wp-json/wc/v3/orders"))
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"ck_abc:cs_xyz").decode()
    assert "oauth_signature" not in str(req.url)


# -- oauth1 -------------------------------------------------------------------------------

URL = httpx.URL("http://localhost:8080/wp-json/wc/v3/orders?per_page=5&search=rahul sharma")
PARAMS = {
    "per_page": "5",
    "search": "rahul sharma",
    "oauth_consumer_key": "ck_test",
    "oauth_nonce": "abc",
    "oauth_signature_method": "HMAC-SHA256",
    "oauth_timestamp": "1700000000",
}


def test_signature_base_string_matches_woocommerce_algorithm():
    """Pins the exact string WC_REST_Authentication::check_oauth_signature rebuilds:
    params sorted by key, each `k=v` pair double-encoded, joined by a literal %26,
    base URI without the query, HTTP method upper-cased.
    The live-store integration test proves this against real WooCommerce."""
    expected = (
        "GET"
        "&http%3A%2F%2Flocalhost%3A8080%2Fwp-json%2Fwc%2Fv3%2Forders"
        "&oauth_consumer_key%3Dck_test"
        "%26oauth_nonce%3Dabc"
        "%26oauth_signature_method%3DHMAC-SHA256"
        "%26oauth_timestamp%3D1700000000"
        "%26per_page%3D5"
        "%26search%3Drahul%2520sharma"
    )
    assert signature_base_string("get", URL, PARAMS) == expected


def test_oauth1_flow_adds_signed_query_params():
    auth = OAuth1Auth("ck_test", "cs_test", nonce=lambda: "abc", timestamp=lambda: 1700000000)
    req = run_flow(auth, httpx.Request("GET", URL))

    query = {k: v[0] for k, v in parse_qs(urlparse(str(req.url)).query).items()}
    assert query["per_page"] == "5"
    assert query["search"] == "rahul sharma"
    assert query["oauth_consumer_key"] == "ck_test"
    assert query["oauth_nonce"] == "abc"
    assert query["oauth_signature_method"] == "HMAC-SHA256"
    assert query["oauth_timestamp"] == "1700000000"

    base = signature_base_string("GET", URL, PARAMS)
    # key = consumer_secret + "&" (empty OAuth token secret), as WooCommerce computes it
    expected_sig = base64.b64encode(hmac.new(b"cs_test&", base.encode(), hashlib.sha256).digest()).decode()
    assert query["oauth_signature"] == expected_sig
    assert "Authorization" not in req.headers


def test_oauth1_signature_changes_with_params_and_secret():
    auth = OAuth1Auth("ck_test", "cs_test", nonce=lambda: "abc", timestamp=lambda: 1)
    other_secret = OAuth1Auth("ck_test", "cs_other", nonce=lambda: "abc", timestamp=lambda: 1)
    sig = lambda a, u: parse_qs(urlparse(str(run_flow(a, httpx.Request("GET", u)).url)).query)["oauth_signature"][0]

    a = sig(auth, "http://localhost:8080/wp-json/wc/v3/orders?page=1")
    assert a == sig(auth, "http://localhost:8080/wp-json/wc/v3/orders?page=1")  # deterministic
    assert a != sig(auth, "http://localhost:8080/wp-json/wc/v3/orders?page=2")
    assert a != sig(other_secret, "http://localhost:8080/wp-json/wc/v3/orders?page=1")


def test_oauth1_uses_fresh_nonce_and_timestamp_by_default():
    auth = OAuth1Auth("ck_test", "cs_test")
    nonces = {
        parse_qs(urlparse(str(run_flow(auth, httpx.Request("GET", URL)).url)).query)["oauth_nonce"][0]
        for _ in range(3)
    }
    assert len(nonces) == 3
