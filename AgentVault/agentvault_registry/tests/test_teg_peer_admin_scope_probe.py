"""§MCPTEST30 (V0546) — the federation probe that reads a peer frame's admin reach on this frame's TEG.

Measured by hand on the sandbox 2026-10-02 ~05:35Z, from inside sbx-beta-registry with its own SVID through
sbx-alpha-nginx-teg: GET /api/v1/admin/fx/reserve 200 (the designed use), /admin/treasury/info 200 and
/admin/fee-collector/info 200 (no designed use). These tests hold the probe's verdict to that reading, its control, and
the states it cannot decide.
"""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.federation_suite.decorator import REGISTRY
from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_teg_peer_admin_scope as P

TARGET = {"name": "_target", "target": "https://sbx-alpha-nginx-teg:8443"}


def _rows(**status):
    rows = {"_target": TARGET}
    for name, st in status.items():
        rows[name] = {"name": name, "status": st}
    return rows


def test_the_sandbox_reading_is_the_finding():
    passed, sentence, ev = P.verdict(_rows(fx_reserve=200, treasury_info=200, fee_collector_info=200))
    assert passed is False and sentence.startswith("BUG-FIND: sandbox-B's registry is an admin on sandbox-A's TEG")
    assert "GET /api/v1/admin/treasury/info answered 200" in sentence and ev["target"] == TARGET["target"]


def test_a_scoped_teg_passes():
    passed, sentence, _ = P.verdict(_rows(fx_reserve=200, treasury_info=403, fee_collector_info=403))
    assert passed is True and "refused on the admin routes it has no use for" in sentence


def test_one_admitted_route_is_enough_to_name():
    passed, sentence, _ = P.verdict(_rows(fx_reserve=200, treasury_info=403, fee_collector_info=200))
    assert passed is False and "fee-collector/info answered 200" in sentence and "treasury/info" not in sentence


@pytest.mark.parametrize("control", [403, 404, 502, None])
def test_without_the_designed_read_the_probe_decides_nothing(control):
    rows = _rows(treasury_info=403, fee_collector_info=403)
    if control is not None:
        rows["fx_reserve"] = {"name": "fx_reserve", "status": control}
    with pytest.raises(PreconditionUnmet, match="cannot tell a scoped TEG from one it never reached"):
        P.verdict(rows)


def test_an_unknown_sidecar_or_an_unclear_answer_is_not_measured():
    with pytest.raises(PreconditionUnmet, match="sidecar address is unknown"):
        P.verdict({"_target": {"name": "_target", "error": "no sidecar", "msg": "TEG_SIDECAR_MAP names no x"}})
    with pytest.raises(PreconditionUnmet, match="neither 200 nor a refusal"):
        P.verdict(_rows(fx_reserve=200, treasury_info=500, fee_collector_info=403))


def test_the_probe_output_is_read_line_by_line():
    out = 'noise\n{"name": "_target", "target": "https://x:8443"}\n{"name": "fx_reserve", "status": 200}\nnot json {\n'
    assert P.read_answers(out) == {"_target": {"name": "_target", "target": "https://x:8443"},
                                   "fx_reserve": {"name": "fx_reserve", "status": 200}}


def test_the_row_is_a_regression_guard_now_and_reads_only():
    """§TEGSCOPE (his word 2026-10-07 "2. yes fix"): every frame's TEG is scoped (adminscope1), so the row is no longer an
    expected red; a TEG without the scope fails it as a bug find."""
    spec = [s for s in REGISTRY if s.name == "teg_admin_is_scoped_for_a_peer_frame"]
    assert len(spec) == 1 and not spec[0].expected_red
    assert "read-only" in spec[0].tags
    assert all(path.startswith("/api/v1/admin/") for _n, path, _d in P.CALLS) and "c.get(" in P._PROBE
    assert "c.post(" not in P._PROBE and "c.request(" not in P._PROBE, "the probe only reads"
