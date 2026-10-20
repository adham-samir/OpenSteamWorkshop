"""Minimal HTTP layer over http.client.

Note: Valve's community limiter fingerprints urllib.request's implicit
headers (Connection/Accept-Encoding set) and returns instant 429s for them,
while plain http.client requests pass. So we speak HTTP directly.
"""

from __future__ import annotations

import gzip
import http.client as httpc
import json
import ssl
import time
import urllib.parse

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class NetError(RuntimeError):
    pass


class RateLimited(NetError):
    """Server responded 429/503 even after backoff — retry later."""


def urljoin(base: str, **params: object) -> str:
    """Append params (skip empty values) to a URL as a query string."""
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in ("", None)})
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{q}"


class Http:
    """Tiny keep-alive HTTP client for store.steampowered.com / steamcommunity.com."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._conn: httpc.HTTPConnection | None = None
        self._host: str | None = None

    def _connection(self, host: str) -> httpc.HTTPConnection:
        if self._conn is None or self._host != host:
            self._conn = httpc.HTTPSConnection(host, timeout=self.timeout)
            self._host = host
        return self._conn

    def request(self, url: str, headers: dict | None = None) -> bytes:
        delays = [0.8, 2.5, 6.0, 15.0]
        last_err: Exception | None = None
        for attempt in range(len(delays) + 1):
            try:
                return self._once(url, headers or {})
            except NetError as e:
                msg = str(e)
                retriable = any(m in msg for m in ("HTTP 429", "HTTP 502", "HTTP 503", "HTTP 500", "Connection"))
                if not retriable:
                    raise
                last_err = e
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    self._conn = None
        raise RateLimited(str(last_err))

    def _once(self, url: str, headers: dict) -> bytes:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        if not host:
            raise NetError(f"bad url {url!r}")
        if parts.scheme != "https":
            raise NetError(f"only https is supported: {url!r}")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        # NOTE: header set kept deliberately minimal — Valve's community limiter
        # fingerprints the long `Accept: text/html,…` value and answers 429.
        h = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "Host": host,
        }
        h.update(headers)
        try:
            conn = self._connection(host)
            conn.request("GET", path, headers=h)
            resp = conn.getresponse()
            status = resp.status
            data = resp.read()
        except (httpc.HTTPException, ConnectionError, OSError, TimeoutError, ssl.SSLError) as e:
            self._conn = None
            raise NetError(f"connection error for {url!r}: {e!r}") from e

        if status in (301, 302, 303, 307, 308):
            loc = resp.getheader("Location") or ""
            self._conn = None
            return self.request(loc, headers)
        if status != 200:
            if status == 429:
                self._conn = None
            raise NetError(f"HTTP {status} for {url!r}")
        if resp.getheader("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except OSError as e:
                raise NetError(f"bad gzip for {url!r}") from e
        return data

    def text(self, url: str, **kw) -> str:
        return self.request(url).decode("utf-8", errors="replace")

    def json(self, url: str, **kw):
        return json.loads(self.text(url))


http = Http()
