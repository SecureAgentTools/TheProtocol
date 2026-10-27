"""Every card this registry MINTS FOR ITSELF must validate against the canonical AgentCard schema.

🔴 THE SAME DEFECT, THREE TIMES, ACROSS THIRTEEN DAYS. §VENUEGW fixed it for the AGORA deposit
gateway on 2026-08-26 and wrote the reason down in that function's own docstring:

    "it used to be a five-field stub (name/description/did/agora_gateway/version). A registry
     running FEDERATION_INGEST_FAIL_CLOSED=true validates every inbound peer card against that
     schema and QUARANTINES what does not conform."

Its two siblings — the AGORA treasury (`exchange_service`) and the org treasury (`org_treasury`) —
were the identical five-field stub and were not looked at. Measured on the live EU frame
2026-09-09: the one AGORA treasury card there is the only native card failing validation for a
reason other than an empty `provider.url`, and it can never reach a peer.

Nothing detects this at runtime. The mint succeeds, the row is real, discovery shows it at home,
and the peer silently drops it with a message about "schema-invalid card_data" that names no
feature. So it is pinned here instead: one test per builder, and the same test would have caught
all three.
"""
import pytest

from agentvault import AgentCard


def _validate(card: dict) -> None:
    AgentCard.model_validate(card)


def test_agora_deposit_gateway_card_validates():
    """§VENUEGW's fix, kept fixed."""
    from agentvault_registry.services.exchange_passport import _gateway_card_data
    _validate(_gateway_card_data())


def test_agora_treasury_card_validates():
    from agentvault_registry.services.exchange_service import _treasury_card_data
    _validate(_treasury_card_data("Reach Limited", "REACH", "did:theprotocol:org-reach-treasury"))


def test_org_treasury_card_validates():
    from agentvault_registry.services.org_treasury import _org_treasury_card_data
    _validate(_org_treasury_card_data("Reach Limited", "did:theprotocol:org-reach-treasury"))


@pytest.mark.parametrize("builder,args", [
    ("agentvault_registry.services.exchange_service._treasury_card_data",
     ("Acme", "ACME", "did:theprotocol:acme-treasury")),
    ("agentvault_registry.services.org_treasury._org_treasury_card_data",
     ("Acme", "did:theprotocol:acme-treasury")),
])
def test_system_cards_declare_an_endpoint_and_never_a_loopback(builder, args):
    """Two failures the schema alone would not catch.

    The card model demands SOME endpoint, so a builder can satisfy it with a lie — and a cloud-op's
    baked `BASE_URL` default is `http://localhost:8000`, which is TRUTHY and sails past a plain
    falsy-guard. Publishing a loopback to the whole federation is the §CARDLINK failure: an address
    that is served nowhere."""
    import importlib
    mod_name, fn_name = builder.rsplit(".", 1)
    fn = getattr(importlib.import_module(mod_name), fn_name)
    card = fn(*args)
    url = (card.get("url") or "").lower()
    assert url, "the card declares no endpoint at all"
    for bad in ("localhost", "127.0.0.1", "0.0.0.0"):
        assert bad not in url, f"the card publishes a loopback address ({url})"


def test_the_control_the_old_five_field_stub_is_refused():
    """THE CONTROL. Each builder above is asserted VALID; this asserts the shape they replaced is
    INVALID, so those assertions are discriminating rather than merely passing."""
    stub = {
        "name": "Reach Limited Treasury ($REACH)",
        "description": "AGORA treasury agent for $REACH — receives IPO proceeds.",
        "did": "did:theprotocol:org-reach-treasury",
        "agora_treasury": True,
        "version": "1.0",
    }
    with pytest.raises(Exception):
        _validate(stub)
