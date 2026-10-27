"""§FEDPROOF (2026-09-13): the elevation payload is JSON-safe with the Decimals the vote summary carries.
Pre-fix the builder was inline and `httpx(json=...)` raised `Object of type Decimal is not JSON serializable`,
so `POST /governance/federation/propose` answered 500 on every frame whose voters held ve power (measured on
sbx-beta, 2026-09-12 23:07Z). The test pins the BUILDER's output, the thing the wire receives."""
import json
from decimal import Decimal

from agentvault_registry.routers.governance import origin_tally_payload


def test_origin_tally_payload_is_json_serializable_with_decimals():
    tally = {"votes_for": Decimal("1.000000"), "votes_against": Decimal("0"), "pass_rate": Decimal("100.0")}
    out = origin_tally_payload(tally, 7)
    encoded = json.dumps(out)  # would raise pre-fix
    back = json.loads(encoded)
    assert back["votes_for"] == 1 and back["votes_against"] == 0 and back["pass_rate"] == 100.0
    assert back["quorum_met"] is True and back["status"] == "PASSED" and back["local_proposal_id"] == 7


def test_origin_tally_payload_keeps_fractions_and_plain_numbers():
    out = origin_tally_payload({"votes_for": Decimal("2.5"), "votes_against": 3, "pass_rate": 66.6}, 1)
    assert out["votes_for"] == 2.5 and isinstance(out["votes_for"], float)
    assert out["votes_against"] == 3 and out["pass_rate"] == 66.6
    json.dumps(out)


def test_origin_tally_payload_control_the_raw_summary_is_not_serializable():
    # the control: the shape the route used to send raises, so the test cannot pass vacuously
    import pytest
    with pytest.raises(TypeError):
        json.dumps({"votes_for": Decimal("1.000000")})
