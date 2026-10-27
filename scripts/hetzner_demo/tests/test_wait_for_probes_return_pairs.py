"""§MTLSHOPS (2026-09-15, b5): every wait_for probe in the standup driver returns (ok, detail).

wait_for unpacks `ok, detail = fn()`. The auditor's live-read gate (bfda1e6, T2 S4) returned a bare bool, so its first try
would have raised TypeError in every standup and resume that reached the kit gates (none had). These drive the probe
through the real wait_for, run the census contract R33 runs in CI (the contract's own wait_for_probe_census, so there is
one census), and pin each shape it must name (agentvault2-85's list). STANDUP_DRIVER_UNDER_TEST points them at another copy
of the driver (the red run against master's).
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
DRIVER = pathlib.Path(os.environ.get("STANDUP_DRIVER_UNDER_TEST") or HERE / "standup_driver.py")
_cspec = importlib.util.spec_from_file_location("frame_template_contract_r33", ROOT / ".forgejo" / "checks" / "frame_template_contract.py")
contract = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(contract)
census = contract.wait_for_probe_census


@pytest.fixture()
def drv(monkeypatch):
    spec = importlib.util.spec_from_file_location("standup_driver_waitfor_pairs", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def _latest(**row):
    return {"f": {"status": "OK", **row}}


@pytest.mark.parametrize("status, body, ok, words", [
    (200, _latest(extra_data=json.dumps({"atomic_delta": 0})), True, "no live_error"),
    (200, _latest(extra_data=json.dumps({"live_error": "CERTIFICATE_VERIFY_FAILED"})), False, "live_error: CERTIFICATE_VERIFY_FAILED"),
    (200, {}, False, "no audit row for f yet"),
    (502, None, False, "HTTP 502"),
])
def test_the_auditor_live_read_probe_answers_a_pair_through_the_real_wait_for(drv, monkeypatch, status, body, ok, words):
    monkeypatch.setattr(drv, "http", lambda method, url, **kw: (status, body))
    seen = []
    monkeypatch.setattr(drv, "log", seen.append)
    assert drv.wait_for("probe", lambda: drv.auditor_live_read_probe(8045, "f"), tries=1, sleep=0) is ok
    assert any(words in line for line in seen), seen


def test_every_wait_for_probe_in_the_driver_returns_a_pair():
    probes, problems = census(DRIVER.read_text())
    assert probes >= 15, probes   # the census read the driver (17 probes on 2026-09-15)
    assert problems == []


# ── the shapes the census must name, each alone ────────────────────────────────────────────────────────────────────────
HEAD = "def wait_for(desc, fn, tries=1, sleep=0):\n    ok, detail = fn()\n\n"


def _one(body, call):
    probes, problems = census(HEAD + body + "\n\ndef gate():\n    " + call + "\n")
    assert probes == 1
    return problems


def test_a_bare_bool_is_named():
    (p,) = _one("def probe():\n    return True", 'wait_for("x", probe)')
    assert "the function probe returns True" in p


def test_a_bare_return_is_named():
    (p,) = _one("def probe(x):\n    if x:\n        return\n    return True, 'y'", 'wait_for("x", probe)')
    assert "returns None (a bare return)" in p


def test_a_body_that_falls_off_its_end_is_named():
    (p,) = _one("def probe(x):\n    if x:\n        return True, 'y'", 'wait_for("x", probe)')
    assert "can end without a return (None)" in p


def test_a_lambda_that_returns_no_call_is_named():
    (p,) = _one("def probe():\n    return True, 'y'", 'wait_for("x", lambda: probe()[0])')
    assert "a lambda probe returns probe()[0]" in p


def test_a_partial_is_read_through_to_what_it_wraps():
    (p,) = _one("def probe(url):\n    return url == 'y'", 'wait_for("x", functools.partial(probe, "y"))')
    assert "a functools.partial of probe returns url == 'y'" in p


def test_a_probe_defined_elsewhere_is_refused_by_name():
    (p,) = _one("", 'wait_for("x", imported_probe)')
    assert "the function imported_probe is not defined in the driver" in p


def test_pairs_through_try_with_and_a_tuple_lambda_pass():
    body = ("def probe(url):\n    try:\n        with open(url) as f:\n            return True, f.read()\n"
            "    except OSError as e:\n        return False, str(e)")
    assert _one(body, 'wait_for("x", lambda: probe("y"))') == []
    assert _one("", 'wait_for("x", lambda: (True, "y"))') == []


# ── agentvault2-85's follow-up: every wait_for call is counted, a probe passed as fn= is read, a missing one refused ───────
def test_a_probe_passed_as_fn_is_read():
    (p,) = _one("def probe():\n    return True", 'wait_for("x", fn=probe)')
    assert "the function probe returns True" in p


def test_a_wait_for_call_whose_probe_cannot_be_found_is_refused():
    (p,) = _one("", 'wait_for("x", **kwargs)')
    assert "whose probe the census cannot find" in p


def test_every_wait_for_call_is_counted():
    src = HEAD + "def probe():\n    return True, 'y'\n\ndef gate():\n    wait_for('x', probe)\n    wait_for('y', fn=probe)\n    wait_for('z')\n"
    probes, problems = census(src)
    assert probes == 3 and len(problems) == 1 and "cannot find" in problems[0]
