"""§OPPROV (2026-09-27): a routed fiat purchase is refunded automatically only when its cross-TEG fund PROVES nothing moved.

The routed settle (routers/fiat_onramp.py, _handle_routed_settle) funds the operator through /teg/treasury/cross-teg-fund
with the purchase id as the correlation id, and refunded the customer on ANY 4xx. Since TEG opprov1 (AgentVault 6db9669c)
a 409 means that another send already used the correlation id, or that the peer refused a RESUMED send whose first attempt
may have landed (the TEG no longer re-credits then: that paid twice). A replay of a purchase whose earlier attempt was
uncertain is such a resume, so any refusal of it is as blind. Refunding in those cases pays the customer back for funds the
operator may hold; the purchase stays PROCESSING for an admin replay. sbx-alpha runs the fiat lane (FIAT_ONRAMP_ENABLED)
on a frame TEG that is opprov1 since 2026-09-27 12:2xZ, so the case is live there.
RED control: on the pre-fix code the decision function does not exist and the handler refunds on 409.
"""
import ast
import inspect

import pytest

from agentvault_registry.routers import fiat_onramp as fo


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_a_first_attempt_the_teg_refused_is_refunded(status):
    assert fo.cross_teg_fund_failure_is_final(status, resumed=False) is True


def test_a_409_is_never_final():
    assert fo.cross_teg_fund_failure_is_final(409, resumed=False) is False
    assert fo.cross_teg_fund_failure_is_final(409, resumed=True) is False


@pytest.mark.parametrize("status", [400, 403, 404, 409, 422])
def test_no_refusal_of_a_resumed_send_is_final(status):
    assert fo.cross_teg_fund_failure_is_final(status, resumed=True) is False


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_5xx_is_never_final(status):
    assert fo.cross_teg_fund_failure_is_final(status, resumed=False) is False


def test_both_uncertain_reasons_mark_a_replay_as_a_resume():
    assert "cross_teg_fund_5xx_pending_retry: 503 Peer TEG unreachable".startswith(fo.UNCERTAIN_FUND_PREFIXES)
    assert "cross_teg_fund_uncertain: 409 Peer TEG refused a resumed send".startswith(fo.UNCERTAIN_FUND_PREFIXES)
    assert not "target_peer_inactive (refund=re_1)".startswith(fo.UNCERTAIN_FUND_PREFIXES)


def test_the_routed_settle_decides_through_the_function():
    src = inspect.getsource(fo._handle_routed_settle)
    tree = ast.parse(src)
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "cross_teg_fund_failure_is_final" in calls
    assert "400 <= http_exc.status_code < 500" not in src, "the old any-4xx refund rule"
