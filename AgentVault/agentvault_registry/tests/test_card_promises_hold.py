"""§EXTREACH (agentvault2-5b, 2026-10-14): a registry card promises only what a stranger can use.

The external reachability suite (stack scripts/extreach/extreach.py) reads every card and checks each URL it
advertises for the audience that reads the card. Its first run found three promises nobody outside could use:

- federation.spire_bundle_endpoint fell back to https://<SPIRE_TRUST_DOMAIN>:8443/.well-known/spire-bundle, a path on
  the federation terminator behind a client certificate: 400 for the frame the field is written for (one not yet
  federated). frame-federate.py stopped at step 3 against EU, ASIA and sandbox-b. Where SPIRE_TRUST_DOMAIN kept its
  legacy default the card named https://agentvault.com:8443, a domain we do not own.
- identity.federation_base_url fell back to FEDERATION_BASE_URL, the internal docker name of the stack's own proxy
  (https://nginx-federation:8443 on the two sandbox operators).
- endpoints.agent_card_well_known and endpoints.spire_bundle named relative paths the console answers 404 to.
"""
import ast
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "src" / "agentvault_registry" / "services" / "registry_card_builder.py")


def _helpers():
    """The two helpers, compiled alone from the builder's source (no app import, no database)."""
    import os
    from typing import Optional
    tree = ast.parse(SRC.read_text())
    wanted = {"_spire_bundle_endpoint", "_dialable_from_outside", "federation_base_url"}
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {f.name for f in funcs} == wanted, "the card builder lost a helper"
    ns = {"os": os, "Optional": Optional}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SRC), "exec"), ns)
    return ns


def _bound(key):
    """Every expression the builder binds to dict key `key`."""
    out = []
    for node in ast.walk(ast.parse(SRC.read_text())):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    out.append(v)
    assert out, f"{key} is built nowhere in the card builder"
    return out


def test_the_bundle_endpoint_is_configured_or_absent(monkeypatch):
    f = _helpers()["_spire_bundle_endpoint"]
    monkeypatch.delenv("SPIRE_BUNDLE_ENDPOINT", raising=False)
    assert f() is None, "unset, the card must name no bundle endpoint rather than guess one"
    monkeypatch.setenv("SPIRE_BUNDLE_ENDPOINT", "  ")
    assert f() is None
    monkeypatch.setenv("SPIRE_BUNDLE_ENDPOINT", " https://sandbox-a.theprotocol.cloud:8465/ ")
    assert f() == "https://sandbox-a.theprotocol.cloud:8465/"


def test_no_guessed_bundle_path_and_no_foreign_default():
    for key in ("spire_bundle_endpoint", "spire_bundle"):
        for node in _bound(key):
            assert isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_spire_bundle_endpoint", \
                f"{key} must come from _spire_bundle_endpoint(): {ast.dump(node)[:120]}"
    tree = ast.parse(SRC.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_spire_bundle_endpoint")
    body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) else fn.body
    consts = [c.value for b in body for c in ast.walk(b) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    # The docstring may name the old fallback (it explains why it is gone); the code may not build one.
    assert not any(w in c for c in consts for w in ("spire-bundle", "agentvault.com", ":8443")), consts


def test_an_internal_federation_address_is_not_published():
    f = _helpers()["_dialable_from_outside"]
    for internal in ("https://nginx-federation:8443", "http://eu-nginx-federation:8443", "https://localhost:8443",
                     "https://10.0.0.5:8443", "https://172.16.1.1:8443", "https://127.0.0.1:8443",
                     "https://registry.local:8443", "https://svc.internal:8443", "", None, "not a url"):
        assert f(internal) is None, internal
    for public in ("https://amsterdam.op.theprotocol.cloud:8443", "https://eu.theprotocol.cloud:8443",
                   "https://1.2.3.4:8443"):
        assert f(public) == public, public


def _federation_expr():
    """The expression the card publishes as identity.federation_base_url. Since V0639 (agentvault2-aa's
    fix/settlement-origin-address) the card binds a call to federation_base_url(), the one function core/settlement_origin
    names a settlement's origin by too, so the card and the settlement cannot name two addresses: follow the call to the
    function's single return expression; an inline expression is read as it stands."""
    (node,) = _bound("federation_base_url")
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "federation_base_url":
        assert not node.args and not node.keywords, "federation_base_url() takes nothing: the card asks the one rule"
        tree = ast.parse(SRC.read_text())
        (fn,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "federation_base_url"]
        body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) else fn.body
        assert len(body) == 1 and isinstance(body[0], ast.Return), "federation_base_url() must be one return expression"
        return body[0].value
    return node


def test_the_public_address_still_wins_and_the_fallback_is_filtered():
    node = _federation_expr()
    assert isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
    first, second = node.values
    assert "BILATERAL_PEER_URL" in ast.dump(first)
    for value, name in ((first, "BILATERAL_PEER_URL"), (second, "FEDERATION_BASE_URL")):
        assert isinstance(value, ast.Call) and getattr(value.func, "id", "") == "_dialable_from_outside", \
            f"{name} may reach the card only through _dialable_from_outside"
    assert "FEDERATION_BASE_URL" in ast.dump(second)


def test_the_card_names_only_a_dialable_federation_address(monkeypatch):
    """The bound expression itself, evaluated (2026-10-15): a runner-built frame's template rendered
    BILATERAL_PEER_URL=http://agentvault_registry_test:8000 (the retired sandbox tier), and the card signed it.
    Since V0639 the bound expression is the call federation_base_url(), evaluated here with the function compiled
    from the builder's own source, so the card's value is the function's."""
    (node,) = _bound("federation_base_url")
    expr = compile(ast.fix_missing_locations(ast.Expression(body=node)), str(SRC), "eval")
    ns = _helpers()
    cases = [
        ("http://agentvault_registry_test:8000", "https://nginx-federation:8443", None),
        ("http://agentvault_registry_test:8000", "https://sandbox-a.theprotocol.cloud:8443",
         "https://sandbox-a.theprotocol.cloud:8443"),
        ("https://eu.theprotocol.cloud:8443", "http://eu-nginx-federation:8443", "https://eu.theprotocol.cloud:8443"),
        (None, None, None),
    ]
    for bilateral, internal, want in cases:
        for key, value in (("BILATERAL_PEER_URL", bilateral), ("FEDERATION_BASE_URL", internal)):
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        assert eval(expr, ns) == want, (bilateral, internal)


def test_no_relative_endpoint_the_console_answers_404():
    (node,) = _bound("agent_card_well_known")
    assert isinstance(node, ast.Constant) and node.value is None


def test_the_schema_no_longer_fills_the_dead_paths_back_in():
    src = (SRC.parents[1] / "schemas.py").read_text()
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RegistryCardEndpoints")
    defaults = {t.target.id: t.value for t in cls.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
    for field in ("agent_card_well_known", "spire_bundle"):
        assert isinstance(defaults[field], ast.Constant) and defaults[field].value is None, field
        assert "Optional" in ast.dump(next(t.annotation for t in cls.body if isinstance(t, ast.AnnAssign)
                                           and t.target.id == field)), f"{field} must accept an older card's string"
