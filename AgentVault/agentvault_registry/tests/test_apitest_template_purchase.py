"""V0649 (agentvault2-13, 2026-10-30; his approval that day, "c is also approved", lifted P8.28b's pre-skip): the API
tester buys a free OFFICIAL pipeline template with the sweep's own agent, as the MCP tester has since V0641. Read on
sbx-alpha 2026-10-30 before this change: the row PASSED on a 404 ("Agent did:theprotocol:placeholder not found",
template "99999", expected_failure), the contract accepting 400 and 404. Fails on V0648's router (the control)."""
from __future__ import annotations

import asyncio
import inspect
import json

from agentvault_registry.routers import admin_api_test as A
from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.contracts import agent_cicd_extras as X

OFFICIAL = {"id": "tpl-official", "name": "Official", "price_teg": "0.000000", "author_did": None}
AUTHORED = {"id": "tpl-authored", "name": "A developer's", "price_teg": 0, "author_did": "did:theprotocol:seller"}
PRICED = {"id": "tpl-priced", "name": "Priced", "price_teg": "5", "author_did": None}


class _R:
    def __init__(self, code, data):
        self.status_code, self._data = code, data
        self.text = json.dumps(data)

    def json(self):
        return self._data


def _client(monkeypatch, listed, bought):
    seen = []

    class _C:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen.append(("GET", url, None))
            return _R(*listed)

        async def post(self, url, headers=None, json=None):
            seen.append(("POST", url, json))
            return _R(*bought)
    monkeypatch.setattr(A.httpx, "AsyncClient", _C)
    return seen


def _row(token="dev-token", agent="did:theprotocol:sweep-agent"):
    return asyncio.run(A._template_purchase_row("POST", A._TEMPLATE_PURCHASE, "developer", token, agent))


def test_the_picker_takes_a_free_official_template_only():
    assert A.pick_free_official_template({"templates": [AUTHORED, PRICED, OFFICIAL]}) == OFFICIAL
    assert A.pick_free_official_template([PRICED, OFFICIAL]) == OFFICIAL
    assert A.pick_free_official_template([AUTHORED, PRICED]) is None, "an authored or priced one is never bought"
    assert A.pick_free_official_template({"templates": []}) is None and A.pick_free_official_template(None) is None


def test_the_sweep_buys_the_official_template_with_its_own_agent(monkeypatch):
    seen = _client(monkeypatch, (200, {"templates": [AUTHORED, PRICED, OFFICIAL]}),
                   (200, {"message": "Template purchased", "template_config": {"stages": []}}))
    r = _row()
    assert r["healthy"] is True and r["statusCode"] == 200 and r["error"] is None
    assert r["dispatched_via"] == "template_purchase_fixture" and r["expected_failure"] is False
    assert seen == [("GET", "/api/v1/pipeline-templates", None),
                    ("POST", "/api/v1/pipeline-templates/tpl-official/purchase", {"buyer_did": "did:theprotocol:sweep-agent"})]


def test_a_repeat_purchase_passes_as_the_route_says(monkeypatch):
    _client(monkeypatch, (200, [OFFICIAL]), (200, {"message": "Template already purchased", "template_config": {}}))
    assert _row()["healthy"] is True


def test_a_refusal_is_a_failure_never_a_pass(monkeypatch):
    _client(monkeypatch, (200, [OFFICIAL]), (404, {"detail": "Agent did:theprotocol:sweep-agent not found"}))
    r = _row()
    assert r["healthy"] is False and r["statusCode"] == 404 and r["error"].startswith("HTTP 404")
    assert r["expected_failure"] is False


def test_a_free_purchase_that_names_a_transaction_fails(monkeypatch):
    _client(monkeypatch, (200, [OFFICIAL]), (200, {"template_config": {}, "transaction_id": "teg_tx_1"}))
    r = _row()
    assert r["healthy"] is False and "transaction_id" in r["error"]


def test_what_the_sweep_cannot_do_is_not_measured_and_says_why(monkeypatch):
    _client(monkeypatch, (200, [AUTHORED, PRICED]), (200, {}))
    r = _row()
    assert r["not_measured"] is True and r["healthy"] is False and "no free official pipeline template" in r["not_measured_reason"]
    assert _row(agent="")["not_measured"] is True and _row(token=None)["not_measured"] is True
    _client(monkeypatch, (503, {"detail": "down"}), (200, {}))
    assert "template list answered 503" in _row()["not_measured_reason"]


def test_the_row_runs_before_any_contract_and_the_pre_skips_are_gone():
    src = inspect.getsource(A.test_endpoint)
    assert src.index("_template_purchase_row(") < src.index("_ensure_contracts_loaded()")
    assert "P8.28b: Skip purchase" not in inspect.getsource(A)
    assert "/pipeline-templates/{template_id}/purchase" not in inspect.getsource(B)
    assert X.PurchasePipelineTemplate.expected_status == [200], "a refusal never passes the purchase"
