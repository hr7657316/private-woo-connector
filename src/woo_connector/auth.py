"""Request authentication for the WooCommerce REST API.

WooCommerce issues a consumer key/secret pair per "REST API key". How that pair is presented
depends on the transport:

* **HTTPS** - plain HTTP Basic auth (``Authorization: Basic base64(ck:cs)``).
* **HTTP**  - WooCommerce refuses Basic auth on unencrypted connections and requires the request
  to be signed with one-legged OAuth 1.0a (HMAC-SHA256), with the OAuth fields sent as query
  parameters. This is what ``WC_REST_Authentication::check_oauth_signature`` verifies.

Both are implemented as ``httpx.Auth`` flows so the rest of the connector never thinks about it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Generator
from typing import Literal
from urllib.parse import quote

import httpx

from woo_connector.errors import ConfigError

AuthMode = Literal["auto", "basic", "oauth1"]


def rfc3986(value: object) -> str:
    """Percent-encode like WooCommerce's ``wc_rest_urlencode_rfc3986()`` (PHP ``rawurlencode`` with ``~`` kept)."""
    return quote(str(value), safe="~")


class BasicAuth(httpx.Auth):
    """HTTP Basic auth - the right choice for every HTTPS store."""

    def __init__(self, consumer_key: str, consumer_secret: str) -> None:
        token = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        self._header = f"Basic {token}"

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = self._header
        yield request


class OAuth1Auth(httpx.Auth):
    """One-legged OAuth 1.0a signing exactly as WooCommerce verifies it.

    The signature base string WooCommerce rebuilds server-side is::

        METHOD & rawurlencode(scheme://host[:port]/path) & <normalised params>

    where the params (query params + oauth_* fields, sorted by key) are each encoded as
    ``rfc3986(rfc3986(key) + "=" + rfc3986(value))`` and joined with a literal ``%26``.
    The double encoding (``%`` -> ``%25``) is a WooCommerce quirk, not an OAuth 1.0a rule.
    The HMAC key is ``consumer_secret + "&"`` (standard OAuth 1.0a with an empty token secret).
    Verified against WooCommerce 11.2's ``WC_REST_Authentication`` by the integration tests.

    Because the host/port are part of what is signed, ``WOO_BASE_URL`` must equal the
    WordPress home URL character for character.
    """

    requires_request_body = False

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        *,
        nonce: Callable[[], str] | None = None,
        timestamp: Callable[[], int] | None = None,
    ) -> None:
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        # Injectable for deterministic tests; production uses fresh values per request
        # (WooCommerce stores the last nonces per key and rejects replays).
        self._nonce = nonce or (lambda: secrets.token_hex(16))
        self._timestamp = timestamp or (lambda: int(time.time()))

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        oauth_params = {
            "oauth_consumer_key": self._consumer_key,
            "oauth_nonce": self._nonce(),
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(self._timestamp()),
        }
        all_params = {**dict(request.url.params.items()), **oauth_params}
        base_string = signature_base_string(request.method, request.url, all_params)
        oauth_params["oauth_signature"] = self.sign(base_string)
        request.url = request.url.copy_merge_params(oauth_params)
        yield request

    def sign(self, base_string: str) -> str:
        # OAuth 1.0a key = consumer_secret & token_secret; WooCommerce has no token secret, so the
        # key is the consumer secret followed by a bare "&" (WC_REST_Authentication::check_oauth_signature).
        key = f"{self._consumer_secret}&".encode()
        digest = hmac.new(key, base_string.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()


def signature_base_string(method: str, url: httpx.URL, params: dict[str, str]) -> str:
    """Build the string WooCommerce signs. Exposed so tests can pin the exact algorithm."""
    base_uri = str(url.copy_with(query=None, fragment=None))
    normalised = [rfc3986(f"{rfc3986(k)}={rfc3986(v)}") for k, v in sorted(params.items())]
    return f"{method.upper()}&{rfc3986(base_uri)}&{'%26'.join(normalised)}"


def select_auth(base_url: str, consumer_key: str, consumer_secret: str, mode: AuthMode = "auto") -> httpx.Auth:
    """Pick the scheme WooCommerce will accept for this base URL (or honour an explicit override)."""
    if not consumer_key or not consumer_secret:
        raise ConfigError(
            "WooCommerce credentials are missing",
            hint="set WOO_CONSUMER_KEY and WOO_CONSUMER_SECRET (WooCommerce > Settings > Advanced > REST API)",
        )
    if mode == "auto":
        mode = "basic" if base_url.startswith("https://") else "oauth1"
    if mode == "basic":
        return BasicAuth(consumer_key, consumer_secret)
    if mode == "oauth1":
        return OAuth1Auth(consumer_key, consumer_secret)
    raise ConfigError(f"unknown WOO_AUTH mode {mode!r}", hint="use auto, basic or oauth1")
