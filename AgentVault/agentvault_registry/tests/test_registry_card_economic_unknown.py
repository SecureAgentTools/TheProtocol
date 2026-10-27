"""§DOCSFIX CB-413: an UNKNOWN supply verdict publishes no numbers.

When the supply read failed on a registry that is not a federated operator, the card's economic block said
supply_invariant_status UNKNOWN beside "0" in every supply term and "0.0" as the delta: zeros nobody measured, under a
spec that says a registry publishes a measured value or omits it. The terms are now null (the schema allows it, and the
FEDERATED block already does it) and the delta is left out.
"""
import pytest

from agentvault_registry.services import registry_card_builder as rcb

TERMS = ("tokens_issued", "total_circulating", "tokens_destroyed", "tokens_fees_collected")


@pytest.fixture(autouse=True)
def _not_an_operator(monkeypatch):
    monkeypatch.delenv("MINTING_AUTHORITY", raising=False)
    monkeypatch.delenv("EXTERNAL_AUDITOR_ENDPOINT", raising=False)


def _audit(monkeypatch, data):
    async def _fetch():
        return data
    monkeypatch.setattr(rcb, "_fetch_supply_audit", _fetch)


async def test_an_unread_supply_publishes_no_numbers(monkeypatch):
    _audit(monkeypatch, {})
    block = await rcb._build_economic_block()
    assert block["supply_invariant_status"] == "UNKNOWN"
    assert [block[t] for t in TERMS] == [None] * 4
    assert "supply_invariant_delta" not in block


async def test_a_measured_supply_is_published_as_measured(monkeypatch):
    _audit(monkeypatch, {"status": "OK", "delta": "0.0", "tokens_issued": "1000001.0", "total_circulating": "1000001.0",
                         "tokens_destroyed": "0.0", "tokens_fees_collected": "0.0", "_source": "eventstore"})
    block = await rcb._build_economic_block()
    assert block["supply_invariant_status"] == "OK" and block["supply_invariant_delta"] == "0.0"
    assert block["tokens_issued"] == "1000001.0" and block["supply_source"] == "eventstore"


async def test_a_federated_operator_still_says_federated(monkeypatch):
    monkeypatch.setenv("MINTING_AUTHORITY", "disabled")
    _audit(monkeypatch, {})
    block = await rcb._build_economic_block()
    assert block["supply_invariant_status"] == "FEDERATED"
    assert "—" not in block["supply_note"] and "token" not in block["supply_note"].lower()
