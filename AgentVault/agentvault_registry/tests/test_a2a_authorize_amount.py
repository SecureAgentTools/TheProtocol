"""§MCPTEST30 (V0525, 2026-10-01) — an authorize amount that is no finite number is the caller's 422, never a 500.
Round 8 on sbx-alpha (V0523): the amount_bounds probe's NaN answered 500 at /a2a-payment/authorize."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentvault_registry.routers.a2a_payment import AuthorizeRequest

DID = "did:theprotocol:payee"


@pytest.mark.parametrize("amount,said", [("NaN", "finite"), ("nan", "finite"), ("Infinity", "finite"), ("-inf", "finite"),
                                         ("abc", "valid number"), ("", "valid number"), ("1e", "valid number")])
def test_an_amount_that_is_no_finite_number_is_refused_by_the_model(amount, said):
    with pytest.raises(ValidationError) as e:
        AuthorizeRequest(target_agent_did=DID, amount=amount)
    assert said in str(e.value)


@pytest.mark.parametrize("amount", ["0.01", "5", "1e-2", "0", "-1"])
def test_a_number_passes_the_model_and_the_route_judges_its_sign(amount):
    assert AuthorizeRequest(target_agent_did=DID, amount=amount).amount == amount   # 0 and -1: the route's own 400
