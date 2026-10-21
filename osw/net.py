"""Thread-local HTTPS connections, public form POSTs and bounded retries."""

from __future__ import annotations

import gzip
import http.client as httpc
import json
import threading
import urllib.parse

USER_AGENT = "OpenSteamWorkshop/0.1 (desktop Workshop browser)"


class NetError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, transient: bool = False):
        super().__init__(message)
        self.status = status
        self.transient = transient


class RateLimited(NetError):
    """Steam's HTTP service is still unavailable after backoff."""


def urljoin(base: str, **params: object) -> str:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in ("", None)})
    return base + (("&" if "?" in base else "?") + q if q else "")


class Http:
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._local = threading.local()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
        self._local.conn = None

    def _connection(self, host: str, port: int | None = None) -> httpc.HTTPConnection:
        key = (host, port)
        if getattr(self._local, "key", None) != key or getattr(self._local, "conn", None) is None:
            self.close()
            self._local.conn = httpc.HTTPSConnection(host, port=port, timeout=self.timeout)
            self._local.key = key
        return self._local.conn

    def request(
        self,
        url: str,
        headers: dict | None = None,
        *,
        method: str = "GET",
        data: dict | None = None,
        cancel: threading.Event | None = None,
    ) -> bytes:
        method = method.upper()
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        actual_headers = dict(headers or {})
        if data is not None:
            actual_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        delays = (0.8, 2.5, 6.0, 15.0)
        for attempt in range(len(delays) + 1):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Request cancelled")
            try:
                return self._once(url, actual_headers, method=method, body=body, cancel=cancel)
            except NetError as exc:
                if not exc.transient:
                    raise
                self.close()
                if attempt == len(delays):
                    if exc.status in (429, 503):
                        raise RateLimited(str(exc), status=exc.status, transient=True) from exc
                    raise
                if (cancel or threading.Event()).wait(delays[attempt]):
                    raise InterruptedError("Request cancelled") from exc
        raise AssertionError("unreachable")

    def _once(
        self,
        url: str,
        headers: dict,
        *,
        method: str = "GET",
        body: bytes | None = None,
        cancel: threading.Event | None = None,
    ) -> bytes:
        for redirect in range(6):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Request cancelled")
            parts = urllib.parse.urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise NetError("Only HTTPS URLs without embedded credentials are supported")
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Host": parts.netloc}
            h.update(headers)
            try:
                conn = self._connection(parts.hostname, parts.port)
                conn.request(method, path, body=body, headers=h)
                resp = conn.getresponse()
                status, location = resp.status, resp.getheader("Location")
                encoding = resp.getheader("Content-Encoding")
                chunks = []
                while chunk := resp.read(64 * 1024):
                    if cancel is not None and cancel.is_set():
                        self.close()
                        raise InterruptedError("Request cancelled")
                    chunks.append(chunk)
                result = b"".join(chunks)
            except (httpc.HTTPException, OSError) as exc:
                self.close()
                if isinstance(exc, InterruptedError):
                    raise
                raise NetError(f"Connection error for {url}: {exc}", transient=True) from exc
            if status in (301, 302, 303, 307, 308):
                self.close()
                if not location or redirect == 5:
                    raise NetError("Missing redirect location or too many redirects")
                next_url = urllib.parse.urljoin(url, location)
                if urllib.parse.urlsplit(next_url).netloc != parts.netloc:
                    headers = {
                        k: v
                        for k, v in headers.items()
                        if k.lower() not in ("authorization", "cookie", "host")
                    }
                url = next_url
                if status == 303 or (status in (301, 302) and method == "POST"):
                    method, body = "GET", None
                    headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
                continue
            if status != 200:
                self.close()
                raise NetError(
                    f"HTTP {status} for {url}",
                    status=status,
                    transient=status in (429, 500, 502, 503, 504),
                )
            if encoding == "gzip" or result[:2] == b"\x1f\x8b":
                try:
                    result = gzip.decompress(result)
                except (OSError, EOFError) as exc:
                    raise NetError("Invalid compressed response") from exc
            return result
        raise NetError("Too many redirects")

    def text(self, url: str, **kw) -> str:
        return self.request(url, **kw).decode("utf-8", errors="replace")

    def json(self, url: str, **kw):
        try:
            return json.loads(self.text(url, **kw))
        except ValueError as exc:
            raise NetError(f"Invalid JSON response from {url}") from exc


http = Http()
