"""HTTP client — federation-license-authenticated calls to mainframe.

Single primitive: X-Federation-License header carries the operator's
FEDERATION_LICENSE_KEY (Mode 3 in core/federation_auth.py:84-140).
"""
from __future__ import annotations

import sys
import uuid
from typing import Any, Dict, Optional

import httpx

from . import __version__

# The global --timeout and --verbose (CB-286: both were accepted and used nowhere). The main callback sets them once
# per invocation; every HTTP call the CLI makes reads them here. timeout None keeps each call's own default.
SETTINGS: Dict[str, Any] = {"timeout": None, "verbose": 0}


def timeout_or(default: float) -> float:
    """--timeout when given, else the call's own default."""
    t = SETTINGS.get("timeout")
    return float(t) if t else float(default)


def event_hooks(verbose: Optional[int] = None) -> Dict[str, Any]:
    """With --verbose, one stderr line per HTTP call: method, URL and status. Never a header or a body (the licence
    key and the API keys travel in headers)."""
    if not (SETTINGS.get("verbose") if verbose is None else verbose):
        return {}

    def _log(response: httpx.Response) -> None:
        print(f"HTTP {response.request.method} {response.request.url} -> {response.status_code}",
              file=sys.stderr, flush=True)

    return {"response": [_log]}


class FederationClient:
    """Thin wrapper around httpx for federation-license-authenticated calls."""

    def __init__(
        self,
        mainframe_url: str,
        license_key: Optional[str],
        timeout: float = 30.0,
        verbose: Optional[int] = None,
    ):
        self.mainframe_url = mainframe_url.rstrip("/")
        self.license_key = license_key
        self.timeout = timeout
        self.verbose = SETTINGS.get("verbose", 0) if verbose is None else verbose
        self._client: Optional[httpx.Client] = None

    def __enter__(self) -> "FederationClient":
        # --timeout bounds every phase, the connect included; without it the connect keeps its own 5 s
        connect = float(SETTINGS["timeout"]) if SETTINGS.get("timeout") else 5.0
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=connect),
            verify=True,
            follow_redirects=False,
            headers={"User-Agent": f"tp-operator/{__version__}"},
            event_hooks=event_hooks(self.verbose),
        )
        return self

    def __exit__(self, *exc) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.license_key:
            h["X-Federation-License"] = self.license_key
        if extra:
            h.update(extra)
        return h

    def get(self, path: str, extra_headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        assert self._client is not None
        return self._client.get(self.mainframe_url + path, headers=self._headers(extra_headers))

    def post(
        self,
        path: str,
        json: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> httpx.Response:
        assert self._client is not None
        h = self._headers(extra_headers)
        if idempotency_key:
            h["X-Idempotency-Key"] = idempotency_key
        return self._client.post(self.mainframe_url + path, json=json, headers=h)


def fresh_idempotency_key(prefix: str = "tpop") -> str:
    """Generate a 32-char idempotency key with a clear prefix for forensics."""
    return f"{prefix}-{uuid.uuid4().hex}"[:48]
