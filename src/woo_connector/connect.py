"""``woo-connect`` - obtain REST API keys through WooCommerce's built-in consent flow (``wc-auth``).

This is how a merchant connects a store without ever seeing a key:

1. We build an authorize URL on the store (``/wc-auth/v1/authorize``) naming the app, the scope
   (``read``), an opaque ``user_id`` we generate, a ``return_url`` for the browser and a
   ``callback_url`` for the keys.
2. The merchant opens it, logs in to wp-admin if needed, and clicks **Approve**.
3. WooCommerce creates a key pair with that scope and **POSTs it server-to-server** to
   ``callback_url`` (JSON: ``consumer_key``, ``consumer_secret``, ``key_permissions``, ``user_id``),
   then redirects the browser to ``return_url?success=1``.
4. We verify the ``user_id`` matches the one we issued, write the keys to ``.env`` and exit.

WooCommerce insists ``callback_url`` is HTTPS, so this CLI serves the callback on a self-signed
certificate. Against the Docker store the callback host is ``host.docker.internal``, which the
store's dev-only mu-plugin allows (``docker/seed/mu-plugins/``). For a real store, the callback
must be a public HTTPS endpoint you host - the request/response shapes are identical.

Run:  uv run woo-connect                      # Docker store defaults
      uv run woo-connect --store https://shop.example.com --callback-host my-public-host.example.com
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import secrets
import ssl
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

APP_NAME = "woo-connector (read-only agent access)"
ENV_KEYS = ("WOO_BASE_URL", "WOO_CONSUMER_KEY", "WOO_CONSUMER_SECRET")


def authorize_url(store: str, *, app_name: str, user_id: str, return_url: str, callback_url: str, scope: str = "read") -> str:
    """The link the merchant clicks. ``scope`` is read | write | read_write - we only ever ask for read."""
    query = urlencode(
        {"app_name": app_name, "scope": scope, "user_id": user_id, "return_url": return_url, "callback_url": callback_url}
    )
    return f"{store.rstrip('/')}/wc-auth/v1/authorize?{query}"


def write_env(env_path: Path, values: dict[str, str]) -> None:
    """Replace or append ``KEY=value`` lines, keeping everything else in the file (API keys, comments) intact."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    env_path.write_text("\n".join(lines).rstrip("\n") + "\n")


class Exchange:
    """Shared state between the two listeners and the main thread."""

    def __init__(self, expected_user_id: str) -> None:
        self.expected_user_id = expected_user_id
        self.keys: dict | None = None
        self.done = threading.Event()
        self.rejected: str | None = None


def make_handler(exchange: Exchange) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # keep stdout clean
            pass

        def _reply(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 - http.server naming
            if urlparse(self.path).path != "/callback":
                return self._reply(404, "not found", "text/plain")
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._reply(400, "invalid json", "text/plain")
            if payload.get("user_id") != exchange.expected_user_id:
                exchange.rejected = "callback carried an unexpected user_id (not the one we issued) - ignored"
                return self._reply(403, "unexpected user_id", "text/plain")
            if not payload.get("consumer_key") or not payload.get("consumer_secret"):
                return self._reply(400, "missing keys", "text/plain")
            exchange.keys = payload
            exchange.done.set()
            self._reply(200, "ok", "text/plain")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/done":
                ok = parse_qs(parsed.query).get("success", ["0"])[0] == "1"
                if not ok:
                    exchange.rejected = exchange.rejected or "merchant declined the authorization"
                    exchange.done.set()
                title = "Connected" if ok else "Not connected"
                msg = (
                    "WooCommerce has sent the read-only API keys to woo-connect. You can close this tab."
                    if ok
                    else "The authorization was declined or failed. Close this tab and run woo-connect again."
                )
                return self._reply(200, f"<!doctype html><title>{title}</title><h1>{title}</h1><p>{msg}</p>")
            self._reply(404, "not found", "text/plain")

    return Handler


def self_signed_context(hostname: str) -> tuple[ssl.SSLContext, Path]:
    """A throw-away certificate for the callback listener (WooCommerce requires https://).

    Returns the server context and the PEM certificate path, so a caller that wants to verify
    the listener (tests, a tunnel) can pin the exact cert instead of disabling verification.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    sans: list[x509.GeneralName] = [x509.DNSName(hostname), x509.DNSName("localhost")]
    try:
        sans.append(x509.IPAddress(ipaddress.ip_address(hostname)))
    except ValueError:
        pass
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )
    tmp = Path(tempfile.mkdtemp(prefix="woo-connect-"))
    (tmp / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp / "key.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp / "cert.pem", tmp / "key.pem")
    return context, tmp / "cert.pem"


class Listeners:
    """The two servers plus the certificate the TLS one presents."""

    def __init__(self, plain: ThreadingHTTPServer, secure: ThreadingHTTPServer, cert_path: Path) -> None:
        self.plain, self.secure, self.cert_path = plain, secure, cert_path

    def shutdown(self) -> None:
        self.plain.shutdown()
        self.secure.shutdown()


def serve(exchange: Exchange, *, http_port: int, https_port: int, callback_host: str) -> Listeners:
    handler = make_handler(exchange)
    plain = ThreadingHTTPServer(("0.0.0.0", http_port), handler)
    secure = ThreadingHTTPServer(("0.0.0.0", https_port), handler)
    context, cert_path = self_signed_context(callback_host)
    secure.socket = context.wrap_socket(secure.socket, server_side=True)
    for server in (plain, secure):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return Listeners(plain, secure, cert_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="woo-connect", description="Connect a WooCommerce store via its consent flow")
    parser.add_argument("--store", default="http://localhost:8080", help="store home URL (default: the Docker demo store)")
    parser.add_argument("--callback-host", default="host.docker.internal", help="hostname the STORE uses to reach this machine")
    parser.add_argument("--http-port", type=int, default=8787, help="return_url listener (browser)")
    parser.add_argument("--https-port", type=int, default=8788, help="callback_url listener (store -> us, TLS)")
    parser.add_argument("--env", default=".env", help="file to write WOO_* into")
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for the merchant")
    parser.add_argument("--no-browser", action="store_true", help="print the URL instead of opening it")
    args = parser.parse_args(argv)

    user_id = secrets.token_urlsafe(16)
    url = authorize_url(
        args.store,
        app_name=APP_NAME,
        user_id=user_id,
        return_url=f"http://localhost:{args.http_port}/done",
        callback_url=f"https://{args.callback_host}:{args.https_port}/callback",
    )
    exchange = Exchange(user_id)
    listeners = serve(exchange, http_port=args.http_port, https_port=args.https_port, callback_host=args.callback_host)

    print(f"Listening for WooCommerce on https://{args.callback_host}:{args.https_port}/callback (self-signed)")
    print("Open this link, sign in to the store if asked, and click Approve:\n")
    print(f"  {url}\n")
    if not args.no_browser:
        webbrowser.open(url)

    try:
        if not exchange.done.wait(timeout=args.timeout):
            print("Timed out waiting for the merchant to approve.", file=sys.stderr)
            return 2
    finally:
        listeners.shutdown()

    if exchange.keys is None:
        print(f"Not connected: {exchange.rejected}", file=sys.stderr)
        return 1

    keys = exchange.keys
    write_env(
        Path(args.env),
        {"WOO_BASE_URL": args.store.rstrip("/"), "WOO_CONSUMER_KEY": keys["consumer_key"], "WOO_CONSUMER_SECRET": keys["consumer_secret"]},
    )
    print(f"Connected. Key …{keys['consumer_key'][-7:]} with permissions={keys.get('key_permissions')} written to {args.env}.")
    print("Try:  uv run scripts/smoke.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
