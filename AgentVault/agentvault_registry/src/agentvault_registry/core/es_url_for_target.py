"""§TRUSTCHAIN P4.6 (2026-09-12) — ONE rule for "which event store belongs to this target".

§EMITDIAG's finding: a sweep EXECUTES against a target registry, so its events land in the TARGET's
event store; a console driving another frame must derive that store from the target, never keep a
literal of its own. The literal `http://event-store-test:8200` (a tier torn down at §BATCH3) still
sat in six places after that fix. This is the derivation `routers/mcp_tester.py` carried, moved
here so the api-tester, its event verifier and a flow test read the same rule.

An undecidable target yields "" and the caller says NOT MEASURED — it never guesses a host.
"""
from __future__ import annotations

from urllib.parse import urlparse


def es_url_for_target(target_url: str) -> str:
    """`http://<slug>-registry:8000` -> `http://<slug>-event-store:8200`; the legacy sandbox names
    map to their old pairings; anything else -> "" (undecidable, and said so by the caller)."""
    try:
        host = urlparse(target_url or "").hostname or ""
    except Exception:  # noqa: BLE001
        return ""
    if host.endswith("-registry"):
        return f"http://{host[: -len('-registry')]}-event-store:8200"
    if host == "registry-test":                    # legacy sandbox-A pairing (tier torn down)
        return "http://event-store-test:8200"
    if host.startswith("registry-test-"):          # registry-test-b / -c (tier torn down)
        return f"http://event-store-test-{host[len('registry-test-'):]}:8200"
    return ""
