"""Read-only WooCommerce connector for AI agents.

The package is split into layers that can be used independently:

- ``config``    – settings loaded from the environment / ``.env``
- ``auth``      – HTTP Basic (HTTPS stores) and OAuth 1.0a (HTTP stores) request signing
- ``ratelimit`` – client-side token bucket + retry/back-off policy
- ``client``    – ``WooClient``: a thin async HTTP client that applies the two layers above
- ``models``    – agent-friendly summaries of WooCommerce payloads
- ``resources`` – the list/get/search primitives for orders and products
- ``mcp_server``– exposes the primitives as MCP tools (the only layer that knows about MCP)
"""

from woo_connector.client import WooClient
from woo_connector.config import Settings
from woo_connector.errors import (
    AuthError,
    BadRequestError,
    ConfigError,
    NotFoundError,
    RateLimitedError,
    UpstreamError,
    WooError,
)

__all__ = [
    "AuthError",
    "BadRequestError",
    "ConfigError",
    "NotFoundError",
    "RateLimitedError",
    "Settings",
    "UpstreamError",
    "WooClient",
    "WooError",
]
