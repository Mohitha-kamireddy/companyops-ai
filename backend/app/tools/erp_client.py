"""A small client for MiniERP's JSON API, built on the standard library.

MiniERP's API uses the same session cookie as its web UI, so this client logs in with
POST /login first and keeps the cookie. If a request comes back 401 (session gone, e.g.
the ERP restarted) it logs in once more and retries. One client = one session; do not
share an instance across threads.
"""
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


class ERPError(Exception):
    """The ERP answered, but not with what we expected."""


class ERPAuthError(ERPError):
    """Login was rejected."""


class ERPUnavailable(ERPError):
    """The ERP could not be reached (connection refused, timeout, ...)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Don't follow redirects: a successful login answers 302, and following it would
    fetch /dashboard, which MiniERP counts as a browser action for that session."""

    def redirect_request(self, *args, **kwargs):
        return None


class ERPClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 5.0):
        if not base_url.lower().startswith(("http://", "https://")):
            # urllib would also happily open file:// URLs; refuse anything but HTTP(S).
            raise ValueError("ERP base URL must start with http:// or https://")
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), _NoRedirect())
        self._logged_in = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get_json(self, path: str) -> Any:
        """GET a JSON API path (e.g. '/api/bills') and return the parsed body."""
        if not self._logged_in:
            self._login()
        status, body = self._send("GET", path)
        if status == 401:  # session was dropped; log in once more and retry
            self._login()
            status, body = self._send("GET", path)
        if status != 200:
            raise ERPError(f"GET {path} returned HTTP {status}")
        try:
            return json.loads(body)
        except ValueError:
            raise ERPError(f"GET {path} did not return valid JSON") from None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _login(self) -> None:
        form = urllib.parse.urlencode({"username": self._username, "password": self._password}).encode()
        status, _ = self._send("POST", "/login", data=form)
        if status == 302:  # MiniERP redirects to /dashboard on success
            self._logged_in = True
            return
        self._logged_in = False
        if status == 401:
            raise ERPAuthError("ERP rejected the configured username/password")
        raise ERPError(f"login returned unexpected HTTP {status}")

    def _send(self, method: str, path: str, data: bytes | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:  # a real HTTP answer with a non-2xx status
            try:
                return exc.code, exc.read()
            finally:
                exc.close()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", exc)
            raise ERPUnavailable(f"could not reach the ERP at {self.base_url}: {reason}") from None
