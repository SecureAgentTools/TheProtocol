"""§OPDIST — the spine probe asks the address the app itself uses, and presents the certificate the hop demands.

Measured on lantern 2026-09-16: its PUBLIC status page read `outage` with "Lantern Cooperative TEG: down" and
"Event Store: down" while both were healthy. The probe composed `http://<slug>-teg:8080/health` and
`http://<slug>-event-store:8200/health` from the registry's slug, and a T3 frame exposes neither to its registry —
its TEG sits behind `<slug>-nginx-teg:8443` and its store behind its own mTLS gateway. With the registry's own
SVID, `${TEG_LAYER_URL}/health` and `${EVENT_STORE_URL}/health` answer 200.

A probe's source is a property of what it measures, not of what runs it. The file already stated that rule three
lines below, for OPA; these two tiles did not follow it.

Structural, because the probe cannot be called without an app: the sovereign branch is parsed, and the control is
that both tests go RED against the pre-fix source via OPDIST_SRC.
"""
from __future__ import annotations

import ast
import os
import pathlib

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")


def _main_src() -> str:
    path = _SRC / "main.py"
    if not path.is_file():
        path = _SRC.parent / "main.py"
    return path.read_text(encoding="utf-8")


def _spine_urls(src: str):
    """Every url expression in the sovereign frame's own service list."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        if "name" not in keys or "url" not in keys:
            continue
        pairs = dict(zip(keys, node.values))
        name, url = ast.unparse(pairs["name"]), ast.unparse(pairs["url"])
        if "_label" in name:                      # the sovereign branch names its tiles from the frame's label
            out.append((name, url))
    return out


def test_the_teg_and_store_tiles_use_the_configured_urls():
    tiles = dict(_spine_urls(_main_src()))
    teg = next(u for n, u in tiles.items() if "TEG" in n)
    store = next(u for n, u in tiles.items() if "Event Store" in n)
    assert "_teg_base" in teg, f"the TEG tile still composes its address: {teg}"
    assert "_es_base" in store, f"the store tile still composes its address: {store}"
    # and the slug form must survive as the FALLBACK, or Frame A and the older frames lose their tiles
    assert "-teg:8080" in teg and "-event-store:8200" in store, "the pre-T3 addresses must remain as fallbacks"


def test_the_bases_come_from_the_variables_the_app_reads():
    src = _main_src()
    assert '_teg_base = (_os_sh.environ.get("TEG_LAYER_URL")' in src, "the TEG base must be TEG_LAYER_URL"
    assert '_es_base = (_os_sh.environ.get("EVENT_STORE_URL")' in src, "the store base must be EVENT_STORE_URL"
    # the certificate half, from this morning, must stay: on a T3 frame every internal hop demands a client cert
    assert "from .es_ssl_helper import get_httpx_verify as _spine_verify" in src
    assert "verify=_spine_verify()" in src
