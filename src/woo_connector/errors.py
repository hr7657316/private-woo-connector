"""Typed errors. Every message is written so an agent (or a human) knows what to do next."""


class WooError(Exception):
    """Base class for anything the connector raises on purpose."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        hint: str | None = None,
    ) -> None:
        self.message = message
        self.status = status
        self.code = code
        self.hint = hint
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = [self.message]
        meta = ", ".join(p for p in (f"HTTP {self.status}" if self.status else "", self.code or "") if p)
        if meta:
            parts.append(f"({meta})")
        if self.hint:
            parts.append(f"Hint: {self.hint}")
        return " ".join(parts)


class ConfigError(WooError):
    """Missing or inconsistent settings."""


class AuthError(WooError):
    """401/403 - the store rejected the credentials or the key lacks permission."""


class NotFoundError(WooError):
    """404 - no such order/product, or no such REST route."""


class BadRequestError(WooError):
    """400 - WooCommerce rejected a parameter (e.g. an unknown order status)."""


class RateLimitedError(WooError):
    """429 that persisted after all retries."""


class UpstreamError(WooError):
    """5xx, network failure, or a non-JSON body - the store itself is unhealthy."""
