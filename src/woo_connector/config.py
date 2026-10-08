"""Connector settings, loaded from environment variables or a ``.env`` file."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["auto", "basic", "oauth1"]


class Settings(BaseSettings):
    """Everything the connector needs to talk to one WooCommerce store.

    All fields are read from ``WOO_*`` environment variables (case-insensitive).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    woo_base_url: str = Field(
        description=(
            "Store home URL, e.g. https://shop.example.com. For OAuth1 (HTTP stores) this must match "
            "the WordPress 'Site Address' exactly - host and port are part of the signature."
        )
    )
    woo_consumer_key: str = Field(description="REST API consumer key (ck_...)")
    woo_consumer_secret: SecretStr = Field(description="REST API consumer secret (cs_...)")
    woo_auth: AuthMode = Field(
        "auto",
        description="auto = Basic over https, OAuth1 over http (WooCommerce rejects Basic on plain http)",
    )
    woo_api_version: str = Field("wc/v3", description="REST namespace; wc/v3 is current")

    woo_rps: float = Field(5.0, gt=0, description="Sustained requests per second the client allows itself")
    woo_burst: int = Field(10, ge=1, description="Token-bucket capacity (short bursts above the rps)")
    woo_timeout: float = Field(15.0, gt=0, description="Per-request timeout in seconds")
    woo_max_retries: int = Field(4, ge=0, description="Retries on 429 / 5xx / network errors (GETs only)")
    woo_max_calls_per_session: int = Field(
        0, ge=0, description="Tool calls one MCP server process may make before refusing (0 = unlimited); caps runaway agents"
    )

    @field_validator("woo_base_url")
    @classmethod
    def _normalise_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("WOO_BASE_URL must start with http:// or https://")
        return value

    @property
    def api_root(self) -> str:
        """Base URL every REST path is resolved against (trailing slash matters for httpx)."""
        return f"{self.woo_base_url}/wp-json/{self.woo_api_version}/"

    @property
    def is_https(self) -> bool:
        return self.woo_base_url.startswith("https://")
