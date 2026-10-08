"""The wc-auth consent flow, minus the browser: we play WooCommerce and POST keys to the listener."""

import socket
import ssl
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from woo_connector import connect


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_authorize_url_matches_woocommerce_contract():
    url = connect.authorize_url(
        "https://shop.example.com/",
        app_name="My App",
        user_id="abc123",
        return_url="http://localhost:8787/done",
        callback_url="https://me.example.com:8788/callback",
    )
    parsed = urlparse(url)
    assert parsed.path == "/wc-auth/v1/authorize"
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q == {
        "app_name": "My App",
        "scope": "read",
        "user_id": "abc123",
        "return_url": "http://localhost:8787/done",
        "callback_url": "https://me.example.com:8788/callback",
    }


def test_write_env_replaces_and_preserves(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# keep me\nWOO_BASE_URL=http://old\nGROQ_API_KEY=gsk_x\nWOO_RPS=5\n")
    connect.write_env(env, {"WOO_BASE_URL": "https://new", "WOO_CONSUMER_KEY": "ck_1", "WOO_CONSUMER_SECRET": "cs_1"})
    assert env.read_text() == "# keep me\nWOO_BASE_URL=https://new\nGROQ_API_KEY=gsk_x\nWOO_RPS=5\nWOO_CONSUMER_KEY=ck_1\nWOO_CONSUMER_SECRET=cs_1\n"


@pytest.fixture
def listeners():
    exchange = connect.Exchange(expected_user_id="issued-id")
    http_port, https_port = free_port(), free_port()
    servers = connect.serve(exchange, http_port=http_port, https_port=https_port, callback_host="localhost")
    # Verify TLS against the exact certificate the listener generated - no verify=False.
    client = httpx.Client(verify=ssl.create_default_context(cafile=servers.cert_path), timeout=5)
    yield exchange, http_port, https_port, client
    client.close()
    servers.shutdown()


def test_callback_over_tls_delivers_keys(listeners):
    exchange, _, https_port, client = listeners
    payload = {"key_id": 7, "user_id": "issued-id", "consumer_key": "ck_new", "consumer_secret": "cs_new", "key_permissions": "read"}
    r = client.post(f"https://localhost:{https_port}/callback", json=payload)
    assert r.status_code == 200
    assert exchange.done.is_set() and exchange.keys == payload


def test_callback_with_foreign_user_id_is_rejected(listeners):
    exchange, _, https_port, client = listeners
    r = client.post(
        f"https://localhost:{https_port}/callback",
        json={"user_id": "someone-else", "consumer_key": "ck", "consumer_secret": "cs"},
    )
    assert r.status_code == 403
    assert exchange.keys is None and not exchange.done.is_set()
    assert "unexpected user_id" in exchange.rejected


def test_return_page_reports_decline(listeners):
    exchange, http_port, _, client = listeners
    r = client.get(f"http://localhost:{http_port}/done?success=0&user_id=issued-id")
    assert r.status_code == 200 and "Not connected" in r.text
    assert exchange.done.is_set() and exchange.keys is None
    assert "declined" in exchange.rejected
