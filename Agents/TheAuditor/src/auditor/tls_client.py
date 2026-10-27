"""§MTLSHOPS T2 (S4, 2026-09-15): the auditor's HTTP read of a frame's supply audit, TLS by scheme.

A solo auditor reads its own frame's store through the store's mTLS sidecar (nginx-event-store) with its own SVID: that route
has no auth dependency and the sidecar verifies the certificate, so no store key is needed (agentvault2-85, measured).
https verifies the server against AUDITOR_TLS_CA with the hostname checked, and presents AUDITOR_TLS_CERT/AUDITOR_TLS_KEY
when they are set. The context is built for each read, so a rotated SVID or bundle is picked up at the next audit. http is
unchanged (the host auditor's slots). X-Internal-Key travels only when a key is set.
"""
import ssl
from typing import Optional

import httpx


def client_kwargs(url: str, cert: str = "", key: str = "", ca: str = "") -> dict:
    """httpx.AsyncClient keyword arguments for one read of `url`: nothing for http; for https a default context (hostname
    checked, certificate required) on `ca` (the system roots when empty) that presents `cert`/`key` when `cert` is set."""
    if not url.lower().startswith("https://"):
        return {}
    ctx = ssl.create_default_context(cafile=ca or None)
    if cert:
        ctx.load_cert_chain(cert, key or None)
    return {"verify": ctx}


NOT_READ_NO_KEY = ("not read: this extra slot carries no store key, is not a public read, and this auditor presents no "
                   "certificate of its own; an extra slot never inherits this host's key")


def live_read_plan(frame: dict, default_key: str, cert: str = "", key: str = "", ca: str = "") -> dict:
    """§MTLSHOPS (a) (2026-09-15, his decision; agentvault2-85's rules): what one live read of a slot may send.

    - A built-in frame's URL and key come from this host's own env: its key, else `default_key` (unchanged).
    - A public read (`public_read`, the frame's public supply audit) sends no key and no certificate, on the system roots.
    - An extra slot with its own key sends exactly that key.
    - An extra slot without a key is read over https only while this auditor has its own certificate configured (the kit
      auditor's slot: its store's gateway verifies that certificate, no key travels).
    - Any other extra slot is not read, and says why: an extra slot never inherits this host's key.
    Returns {"read", "store_key", "cert", "key", "ca", "skipped"}."""
    def plan(read, store_key=None, c="", k="", a="", skipped=""):
        return {"read": read, "store_key": store_key, "cert": c, "key": k, "ca": a, "skipped": skipped}
    if frame.get("builtin"):
        return plan(True, frame.get("key") or default_key or None, cert, key, ca)
    if frame.get("public_read"):
        return plan(True)
    if frame.get("key"):
        return plan(True, frame["key"], cert, key, ca)
    if str(frame.get("url") or "").lower().startswith("https://") and cert:
        return plan(True, None, cert, key, ca)
    return plan(False, skipped=NOT_READ_NO_KEY)


def read_headers(store_key: Optional[str]) -> dict:
    return {"X-Internal-Key": store_key} if store_key else {}


async def read_supply_audit(url: str, store_key: Optional[str], *, cert: str = "", key: str = "", ca: str = "",
                            timeout: float = 30.0) -> dict:
    """GET <url>/api/v1/projections/supply-audit and return its JSON; raises on a transport error or a non-2xx answer."""
    async with httpx.AsyncClient(timeout=timeout, **client_kwargs(url, cert, key, ca)) as client:
        resp = await client.get(f"{url}/api/v1/projections/supply-audit", headers=read_headers(store_key))
        resp.raise_for_status()
        return resp.json()
