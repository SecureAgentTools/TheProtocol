"""§FRAMELIC (2026-09-07, findings row 154) — A SIGNED CARD MUST PUBLISH A DIALABLE ADDRESS.

`identity.federation_base_url` was `os.environ["FEDERATION_BASE_URL"]`, which on every frame and
operator is the INTERNAL docker name of its own federation proxy:

    EU frame  : http://eu-nginx-federation:8443
    amsterdam : https://nginx-federation:8443

Correct for the stack that sets it — the value is used as such for container-to-container dispute
callbacks and the self-echo guard. Wrong the moment it is SIGNED and published, because a card is
read by strangers, and the question they are asking is "where do I dial this peer's federation
endpoint".

MEASURED on the EU/ASIA pair: each frame learned the other's two cloud operators through the
registry-card fan-out, could not get a federation address from the card, stored the :443 console
(`https://shenzhen.op.theprotocol.cloud`), and never synced from them — `last_synced_at` NULL on
all four rows and four `peer_url_misconfigured` drift events, which is exactly the cause the drift
monitor names in its own comment: requests land on the public-cert nginx, which does not do
`ssl_verify_client`, so the registry sees no client identity and answers 401.

Same family as §LOCTRUTH (a globe-legibility city published as a geographic claim) and §FXSTRAND
(a flag whose precondition nothing supplied): one value, two questions, and only one of them true.

`BILATERAL_PEER_URL` is the public mTLS address the standup already validates — it refuses a plain
:443 console — so the card prefers it and keeps the internal value as a fallback.
"""
import ast
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "src" / "agentvault_registry" / "services" / "registry_card_builder.py")
PROV = (pathlib.Path(__file__).resolve().parents[1]
        / "src" / "agentvault_registry" / "services" / "cloud_provisioner.py")


def _federation_value_node():
    """The expression bound to identity.federation_base_url, off the AST. Since V0639 (agentvault2-aa's
    fix/settlement-origin-address) the card binds a call to federation_base_url(), the function core/settlement_origin
    asks too: the call is followed to that function's single return expression."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "federation_base_url":
                    if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "federation_base_url":
                        (fn,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "federation_base_url"]
                        body = (fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)
                                else fn.body)
                        assert len(body) == 1 and isinstance(body[0], ast.Return), "one return expression"
                        return body[0].value
                    return v
    raise AssertionError("federation_base_url not built anywhere in the card builder")


def test_the_card_prefers_the_public_federation_address():
    node = _federation_value_node()
    names = {c.value for c in ast.walk(node)
             if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert "BILATERAL_PEER_URL" in names, (
        "the card must publish the public federation address, not only the internal one")
    assert "FEDERATION_BASE_URL" in names, (
        "the internal value must remain the fallback for stacks that set no public one")


def test_the_public_one_wins():
    """Order matters: a BoolOp `or` chain must reach for the public value FIRST."""
    node = _federation_value_node()
    assert isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or), ast.dump(node)
    first = node.values[0]
    firsts = {c.value for c in ast.walk(first)
              if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert "BILATERAL_PEER_URL" in firsts, "the internal name is still preferred"


def test_every_new_operator_is_given_one():
    """A preference is inert if nothing sets the value — operators had no BILATERAL_PEER_URL."""
    src = PROV.read_text()
    assert "BILATERAL_PEER_URL=" in src, (
        "the provisioner must write the operator's public federation address")
    line = next(l for l in src.splitlines() if "BILATERAL_PEER_URL=" in l)
    # §HELLOFRAME lane 6 (2026-09-18): the value comes from ONE rule (operator_public_urls) rather than a literal
    # naming the network's own suffix, so the operator's OWN public host and the federation port are asserted on
    # the rule's answer for the network's own host, and the write line is asserted to take that answer
    assert "_public['BILATERAL_PEER_URL']" in line, f"must write the derived address: {line.strip()}"
    from agentvault_registry.core.operator_compose import operator_public_urls
    ours = operator_public_urls(safe="shenzhen", suffix="op.theprotocol.cloud")["BILATERAL_PEER_URL"]
    assert ours == "https://shenzhen.op.theprotocol.cloud:8443", ours
