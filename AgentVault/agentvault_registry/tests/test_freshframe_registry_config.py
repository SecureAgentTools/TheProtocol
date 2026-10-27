"""§FRESHFRAME (2026-09-14) — the public registry-config names this frame's trust domain.

The landing page's SDK snippets used to print `trusted_domains=["agentvault.com", "frame-b.theprotocol.cloud"]`
on every frame; they now print the frame's own trust domain, read from `/api/v1/public/registry-config`
(`trust_domain`, the same value the registry card publishes as `identity.trust_domain`). Structural on
purpose, like test_showcase_gate.py: the route is a closure inside create_app(), so the AST is the honest
reader of what it returns; the field's presence in the wire payload is pinned by the FE unit tests that
carry sandbox-a's and the flagship's real answers as fixtures.
"""
from __future__ import annotations

import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "main.py"
TREE = ast.parse(MAIN.read_text(encoding="utf-8"))


def _route_fn(name: str):
    fns = [n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(fns) == 1, name
    return fns[0]


def _returned_dict_keys(fn) -> dict:
    out = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant):
                    out[k.value] = v
    return out


def test_registry_config_publishes_the_trust_domain_from_the_spire_env():
    keys = _returned_dict_keys(_route_fn("public_registry_config"))
    assert "trust_domain" in keys, sorted(keys)
    src = ast.unparse(keys["trust_domain"])
    assert "SPIRE_TRUST_DOMAIN" in src and ".strip()" in src, src


def test_the_showcase_gate_field_is_still_beside_it():
    """The two fields the landing page reads for its host-awareness must both come from the one route."""
    keys = _returned_dict_keys(_route_fn("public_registry_config"))
    assert "showcase_chat_enabled" in keys and "registry_name" in keys and "local_currency" in keys
