"""§FRAMELIC findings row 191 — an FX peer entry is whole or the frame cannot pay it.

`frame_test_provisioner._render*` wrote the FX_ROUTE_PEERS entry for `--fx-peer` with THREE
defects in one literal, and each one hid the next. Measured live on EU→ASIA, three attempts:

  1. `registry_id: ""` → the source gateway refused with
     "FX route: GD peer ␣ not ACTIVE on this frame" — a message that could not name the peer
     it was looking for, because there wasn't one.
  2. `url: "http://<slug>-registry:8000"` → the delegate then talks PLAIN HTTP to a SOVEREIGN
     peer, so federation auth Mode 1 (mTLS) cannot happen and it falls to Mode 2, presenting
     THIS cluster's internal secret to a frame that has a different one → 401 "Invalid
     federation secret". Omitting `url` is the fix AND the standing rule: the engine reads
     `gd.get("url") or gd_peer.base_url`, and the peer ROW carries the authoritative mTLS
     federation address (CLAUDE.md: never hardcode a gateway url).
  3. no `router_did` → the FX core swap is a transfer to nobody.

None of the three could be seen from the frame: FX_ENABLED, the pool, `/fx/rates` and the
sim's fx mode were all green throughout, because the POOL and the ROUTE ENGINE are different
mechanisms that share the word FX (§FXSTRAND).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "hetzner_demo"))
sys.path.insert(0, str(REPO / "AgentVault" / "agentvault_registry" / "src"))

PROV = (REPO / "AgentVault/agentvault_registry/src/agentvault_registry/services/"
        "frame_test_provisioner.py").read_text()
DRIVER = (REPO / "scripts/hetzner_demo/standup_driver.py").read_text()
EXTRAS = (REPO / "scripts/hetzner_demo/standup_extras.py").read_text()
ENV_TMPL = (REPO / "templates/frame-test/frame-test.env.tmpl").read_text()


def _peers_literal() -> str:
    """The FX_ROUTE_PEERS value expression, read out of the renderer's own values dict."""
    i = PROV.index('"FX_ROUTE_PEERS":')
    return PROV[i:i + 700]


def test_the_peer_entry_names_the_peer():
    """registry_id must be the peer slug — an empty one is what produced the nameless refusal."""
    lit = _peers_literal()
    assert '"registry_id": ""' not in lit, "registry_id is still the empty literal"
    assert '"registry_id": ctx.fx_peer_slug' in lit


def test_the_peer_entry_carries_the_peers_router_did():
    lit = _peers_literal()
    assert '"router_did": ctx.fx_peer_router_did' in lit
    assert "fx_peer_router_did: str" in PROV, "the context field must exist"


def test_the_peer_entry_hardcodes_no_url():
    """The peer ROW decides the address. A hardcoded url beats it, and the only url we could
    hardcode here is the plain-HTTP internal one that cannot carry a client certificate."""
    lit = _peers_literal()
    assert '"url"' not in lit, "FX_ROUTE_PEERS must not hardcode a gateway url"
    assert "-registry:8000" not in lit


def test_an_fx_peer_without_a_router_did_is_refused():
    """A half-configured FX partner must fail at ARGUMENT time, not three hops into a transfer
    with a stranger's money already in transit."""
    assert "--fx-peer-router-did" in DRIVER
    i = DRIVER.index("ctx.fx_peer_router_did = ")
    window = DRIVER[i:i + 700]
    assert 'startswith("did:")' in window
    assert "die(" in window, "a missing router DID must refuse the standup"


def test_the_standup_mints_the_router_before_it_turns_the_flag_on():
    """§FXSTRAND's other half. The template ships the flag OFF (its precondition is an agent that
    does not exist yet); the standup is what may turn it on, and only after issuance."""
    assert "FT_REG_FX_ROUTE_ENABLED=false" in ENV_TMPL, "the template must still ship it OFF"
    assert "def mint_fx_router(" in EXTRAS
    i = DRIVER.index("mint_fx_router(")
    window = DRIVER[i:i + 1600]
    assert "FT_REG_FX_ROUTER_DID" in window and "FT_REG_FX_ROUTE_ENABLED" in window, \
        "the DID and the flag must be written together"
    # the issuance must come from a SERVICE account, never the frame admin (HIS decision 2026-09-07)
    assert "svc-provisioning" in DRIVER[i - 1200:i]


def test_the_router_credential_is_not_persisted():
    """His standing word: the @fx_router secret is deliberately not written down. The issuance must
    return a DID and nothing else — a helper that returned the credential would invite a caller
    to store it."""
    i = EXTRAS.index("def mint_fx_router(")
    body = EXTRAS[i:EXTRAS.index("\ndef ", i + 10)]
    sig = body[:body.index(":\n")] + ":"          # the whole multi-line signature
    assert sig.rstrip().endswith("-> str:"), f"mint_fx_router must return only a DID, got {sig[-40:]!r}"
    # ⚠ STRIP THE DOCSTRING FIRST. A source-reading gate finds its own documentation before it
    # finds the code — this assertion fired on the sentence *explaining* that the credential is
    # never kept ("nothing needs the client_secret, so nothing keeps it"). Prose next to a fix
    # names the CLASS; the gate must run against the statements. (standing gotcha, §EMITKEY)
    code = body.split('"""')[2] if body.count('"""') >= 2 else body
    assert "client_secret" not in code, "creating the router must not touch the credential"
    assert "secret.json" not in code, "creating the router must not write the credential to a secret file"


def test_the_rendered_entry_is_valid_json_with_every_field():
    """EVALUATE THE RENDERER'S OWN EXPRESSION, not a retyped copy of it.

    The first draft of this test rebuilt the dict by hand and therefore passed against the
    BROKEN source as well — a test that cannot fail measures nothing. It now parses the
    expression out of `frame_test_provisioner` and evaluates it against a stub context, so it
    is red whenever the real literal is wrong.
    """
    i = PROV.index('"FX_ROUTE_PEERS":')
    expr = PROV[i + len('"FX_ROUTE_PEERS":'):]
    # the value is a parenthesised conditional expression; take up to its matching close paren
    depth = 0
    for n, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                expr = expr[:n + 1]
                break

    class C:
        fx_peer_slug = "asia"
        fx_peer_currency = "ACU"
        fx_peer_router_did = "did:theprotocol:asia.theprotocol.cloud:0000"

    rendered = eval(expr, {"json": json}, {"ctx": C()})  # noqa: S307 — our own source, in-repo
    entry = json.loads(rendered)[0]
    assert entry["currency"] == "ACU"
    assert entry["registry_id"] == "asia", "the peer entry must name the peer"
    assert entry["teg_id"] == "teg-layer-asia"
    assert entry["router_did"].startswith("did:"), "the FX core swap needs a receiver"
    assert "url" not in entry, "the peer ROW carries the authoritative mTLS address"


def test_no_fx_peer_still_renders_an_empty_list():
    """The control for the whole shape: a frame with no FX partner declares none."""
    i = PROV.index('"FX_ROUTE_PEERS":')
    expr = PROV[i + len('"FX_ROUTE_PEERS":'):]
    depth = 0
    for n, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                expr = expr[:n + 1]
                break

    class C:
        fx_peer_slug = ""
        fx_peer_currency = ""
        fx_peer_router_did = ""

    assert json.loads(eval(expr, {"json": json}, {"ctx": C()})) == []
