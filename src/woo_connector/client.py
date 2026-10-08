"""``WooClient`` - the one place HTTP happens.

Responsibilities: resolve paths against the store, authenticate, throttle, retry, and turn
WooCommerce's error envelope (``{"code": ..., "message": ..., "data": {"status": ...}}``)
into typed exceptions with actionable hints. Everything above this layer deals in plain dicts.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from woo_connector.auth import select_auth
from woo_connector.config import Settings
from woo_connector.errors import (
    AuthError,
    BadRequestError,
    NotFoundError,
    RateLimitedError,
    UpstreamError,
    WooError,
)
from woo_connector.ratelimit import RetryPolicy, TokenBucket

USER_AGENT = "woo-connector/0.1 (read-only MCP connector)"
MAX_PER_PAGE = 100  # hard cap enforced by the WordPress REST API


@dataclass(frozen=True)
class PageMeta:
    page: int
    per_page: int
    total: int
    total_pages: int

    @property
    def has_more(self) -> bool:
        return self.page < self.total_pages


Params = dict[str, Any]


class WooClient:
    """Async client bound to one store. Use as ``async with WooClient(settings) as woo:``."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._bucket = TokenBucket(settings.woo_rps, settings.woo_burst, sleep=sleep)
        self._retry = RetryPolicy(settings.woo_max_retries)
        self._http = httpx.AsyncClient(
            base_url=settings.api_root,
            auth=select_auth(
                settings.woo_base_url,
                settings.woo_consumer_key,
                settings.woo_consumer_secret.get_secret_value(),
                settings.woo_auth,
            ),
            timeout=settings.woo_timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    async def __aenter__(self) -> WooClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- low level --------------------------------------------------------------------------

    async def get(self, path: str, params: Params | None = None) -> httpx.Response:
        """GET ``path`` (relative to ``/wp-json/wc/v3/``) with throttling and retries."""
        query = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        while True:
            await self._bucket.acquire()
            try:
                response = await self._http.get(path, params=query)
            except httpx.HTTPError as exc:
                if self._retry.should_retry(attempt, None):
                    await self._sleep(self._retry.delay(attempt))
                    attempt += 1
                    continue
                raise UpstreamError(
                    f"could not reach the store: {exc.__class__.__name__}: {exc}",
                    hint="check WOO_BASE_URL and that the store is up; raise WOO_TIMEOUT for slow hosts",
                ) from exc

            if self._retry.should_retry(attempt, response.status_code):
                await self._sleep(self._retry.delay(attempt, response.headers.get("Retry-After")))
                attempt += 1
                continue
            return self._raise_for_status(response)

    async def get_json(self, path: str, params: Params | None = None) -> Any:
        return (await self.get(path, params)).json()

    async def get_page(self, path: str, params: Params | None = None) -> tuple[list[dict[str, Any]], PageMeta]:
        """GET a collection endpoint and read WordPress's pagination headers."""
        query = dict(params or {})
        page = int(query.get("page") or 1)
        per_page = min(int(query.get("per_page") or 10), MAX_PER_PAGE)
        query.update(page=page, per_page=per_page)
        response = await self.get(path, query)
        items = response.json()
        if not isinstance(items, list):
            raise UpstreamError(f"expected a list from {path}, got {type(items).__name__}")
        meta = PageMeta(
            page=page,
            per_page=per_page,
            total=int(response.headers.get("X-WP-Total", len(items))),
            total_pages=int(response.headers.get("X-WP-TotalPages", 1)),
        )
        return items, meta

    async def iter_pages(
        self, path: str, params: Params | None = None, *, per_page: int = MAX_PER_PAGE, max_pages: int = 20
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Walk a collection page by page. ``max_pages`` bounds the cost of client-side scans."""
        page = 1
        while page <= max_pages:
            items, meta = await self.get_page(path, {**(params or {}), "page": page, "per_page": per_page})
            yield items
            if not meta.has_more or not items:
                return
            page += 1

    # -- error mapping ----------------------------------------------------------------------

    def _raise_for_status(self, response: httpx.Response) -> httpx.Response:
        status = response.status_code
        if 200 <= status < 300:
            if "json" not in response.headers.get("Content-Type", ""):
                raise UpstreamError(
                    "store returned a non-JSON body",
                    status=status,
                    hint="WOO_BASE_URL probably does not point at a WordPress site, or a maintenance/WAF page is in the way",
                )
            return response

        code, message = _error_envelope(response)
        kwargs = {"status": status, "code": code}
        if status in (401, 403):
            scheme = "OAuth1" if self.settings.woo_base_url.startswith("http://") else "Basic"
            raise AuthError(
                message or "authentication rejected",
                hint=(
                    f"check WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET and that the key has Read permission; "
                    f"this is an {'HTTP' if scheme == 'OAuth1' else 'HTTPS'} store so {scheme} auth is used "
                    "(for OAuth1 the host:port in WOO_BASE_URL must equal the WordPress home URL)"
                ),
                **kwargs,
            )
        if status == 404:
            hint = None
            if code == "rest_no_route":
                hint = "no such REST route: WooCommerce may be inactive, or pretty permalinks are off"
            raise NotFoundError(message or "not found", hint=hint, **kwargs)
        if status == 429:
            raise RateLimitedError(message or "rate limited by the store", hint="lower WOO_RPS", **kwargs)
        if status == 400:
            raise BadRequestError(message or "bad request", **kwargs)
        if status >= 500:
            raise UpstreamError(message or "store error", **kwargs)
        raise WooError(message or f"unexpected HTTP {status}", **kwargs)


def _error_envelope(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        body = response.json()
    except ValueError:
        return None, response.text[:200] or None
    if isinstance(body, dict):
        return body.get("code"), body.get("message")
    return None, None
