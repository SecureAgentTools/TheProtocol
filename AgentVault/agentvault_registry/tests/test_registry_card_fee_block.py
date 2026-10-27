"""§DOCSFIX (CB-103, D6-394, D6-458, D6-459, CB-415, CB-423): the signed card's fee block states what is charged.

Measured on the live EU card (2026-10-16): `fees.intra_registry` printed the network's locked values (0.5/5.0) whatever
the frame's policy document said, while the fee service charges the document's rates (an admin policy edit or a passed
policy_change moves them); `economic_disclosure.fee_floor_avt` said 0.000001 while the fee service applies no floor
(FEE_FLOOR_AVT = 0); `fee_waterfall_policy` named a third source, operator_pull, that the TEG's waterfall does not have;
`fx.size_cap` and `fx.reserve_floor` were two fixed entries read from FX_*_AVT and FX_*_BVT (EU and ASIA showed AVT and
BVT at 0), while the engine applies FX_SIZE_CAP_<CODE> and FX_RESERVE_FLOOR_<CODE> for any unit code; and the hosting
text promised a PUT that cannot set hosting.
"""
import ast
import os
import pathlib
from types import SimpleNamespace

import pytest

from agentvault_registry.crud import crud_enforcement
from agentvault_registry.services import registry_card_builder as rcb
from agentvault_registry.services import transaction_fee_service as tfs

_HERE = pathlib.Path(__file__).resolve()
TEG_TREASURY = (_HERE.parents[2] / "agentvault_teg_layer_mvp" / "src" / "teg_core_service" / "api" / "v1"
                / "endpoints_treasury.py")


@pytest.fixture(autouse=True)
def _no_teg(monkeypatch):
    async def _cfg():
        return {}
    monkeypatch.setattr(rcb, "_fetch_fee_config", _cfg)


def _policy_row(monkeypatch, policy_json):
    async def _row(db):
        return SimpleNamespace(policy_json=policy_json) if policy_json is not None else None
    monkeypatch.setattr(crud_enforcement, "get_active_policy", _row)


async def test_the_floor_is_the_one_the_fee_service_applies():
    blk = await rcb._build_fees_block()
    assert blk["economic_disclosure"]["fee_floor_avt"] == str(tfs.FEE_FLOOR_AVT) == "0"


async def test_the_waterfall_names_the_tegs_own_sources():
    tree = ast.parse(TEG_TREASURY.read_text(encoding="utf-8"))
    default = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", None) == "DEFAULT_WATERFALL" for t in n.targets))
    assert default == ["fee_collector", "treasury"]
    blk = await rcb._build_fees_block()
    assert blk["fee_waterfall_policy"].split(" → ") == default


async def test_the_hosting_text_promises_nothing_the_card_cannot_do():
    hosting = (await rcb._build_fees_block())["hosting"]
    assert hosting["enabled"] is False and hosting["rate_percent_of_agent_service_fee"] == 0.0
    assert "PUT" not in hosting["description"] and "/admin/" not in hosting["description"]


async def test_the_card_states_the_rates_the_fee_service_charges(monkeypatch):
    _policy_row(monkeypatch, {"transaction_fees": {"base_rate_percent": 0.7, "max_rate_percent": 4.0}})
    rates = await rcb._charged_intra_rates(db=None)
    blk = await rcb._build_fees_block(rates)
    assert (blk["intra_registry"]["base_rate_percent"], blk["intra_registry"]["max_rate_percent"]) == (0.7, 4.0)
    # the same document is what a transfer is charged: 0.7% of 100 at a quiet velocity
    fee, rate = await tfs.get_transaction_fee_service().calculate_fee(None, 100, velocity_index=0.0)
    assert (str(fee), rate) == ("0.700000", 0.7)


async def test_without_a_policy_row_the_card_states_the_fee_services_defaults(monkeypatch):
    _policy_row(monkeypatch, None)
    blk = await rcb._build_fees_block(await rcb._charged_intra_rates(db=None))
    assert (blk["intra_registry"]["base_rate_percent"], blk["intra_registry"]["max_rate_percent"]) == (
        tfs.DEFAULT_BASE_RATE_PCT, tfs.DEFAULT_MAX_RATE_PCT)


@pytest.fixture
def _fx_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("FX_SIZE_CAP_", "FX_RESERVE_FLOOR_")):
            monkeypatch.delenv(k)
    monkeypatch.setenv("FX_ENABLED", "true")
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    return monkeypatch


def test_the_fx_limits_are_keyed_by_the_codes_the_engine_applies(_fx_env):
    _fx_env.setenv("FX_SIZE_CAP_ECU", "500")
    _fx_env.setenv("FX_SIZE_CAP_ACU", "250")
    _fx_env.setenv("FX_RESERVE_FLOOR_ECU", "1000")
    _fx_env.setenv("FX_SIZE_CAP_lower", "7")      # never read by the engine (it reads the upper-cased code)
    fx = rcb._fx_card_block()
    assert fx["size_cap"] == {"ECU": 500.0, "ACU": 250.0}
    assert fx["reserve_floor"] == {"ECU": 1000.0}
    from agentvault_registry.routers import teg_integration as ti
    assert float(ti._fx_size_cap("ACU")) == fx["size_cap"]["ACU"]
    assert float(ti._fx_reserve_floor("ECU")) == fx["reserve_floor"]["ECU"]


def test_unset_the_frames_own_unit_is_published_uncapped(_fx_env):
    fx = rcb._fx_card_block()
    assert fx["size_cap"] == {"ECU": 0.0} and fx["reserve_floor"] == {"ECU": 0.0}
    assert "AVT" not in fx["size_cap"] and "BVT" not in fx["reserve_floor"]
