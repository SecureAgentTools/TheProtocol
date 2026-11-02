"""V0653 (am), item 5 (the hardening list in the sessions' room), the TEG: the home-frame guard compares whole trust domains.

home_frame_resolver's _bulk_rpc answers an agent's home TRUST DOMAIN (this TEG's own for a native agent), and the sync and
bulk checks compare it with LOCAL_TRUST_DOMAIN. async_check_home_or_raise compared it with LOCAL_FRAME, a letter ("A"/"B")
no trust domain equals, so with the guard on (EU, ASIA, Frame A and the sandbox TEGs) /credit-async refused a first profile
to every receiver whose home was known, this frame's own agents included. The two letter labels read a substring
("frame-b" in td), so a look-alike domain wore Frame B's letter. The registry's answer is faked at the HTTP layer
(httpx.MockTransport), so the resolver's own normalization runs. BASE (a5ef48ddd, V0652): the native receiver is refused
by the async check and the look-alikes read B.
"""
import asyncio
import json
import os
import pathlib
import subprocess
import sys

import httpx
import pytest

from teg_core_service.database import home_frame_resolver as hfr

SRC = pathlib.Path(hfr.__file__).resolve().parents[2]      # the source tree this test imported (src/)

LOCAL = "eu.theprotocol.cloud"
NATIVE, NATIVE2, FOREIGN, NOCARD = "did:theprotocol:n1", "did:theprotocol:n2", "did:theprotocol:f1", "did:theprotocol:x1"
REGISTRY = {NATIVE: "", NATIVE2: "native", FOREIGN: "asia.theprotocol.cloud"}     # NOCARD: absent, as for a DID with no card

_RealAsync, _RealSync = httpx.AsyncClient, httpx.Client


@pytest.fixture()
def rig(monkeypatch):
    calls = []

    def handler(request):
        dids = json.loads(request.content)["dids"]
        calls.append(dids)
        return httpx.Response(200, json={"home_trust_domains": {d: REGISTRY[d] for d in dids if d in REGISTRY}})

    t = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _RealAsync(transport=t, timeout=kw.get("timeout")))
    monkeypatch.setattr(httpx, "Client", lambda **kw: _RealSync(transport=t, timeout=kw.get("timeout")))
    monkeypatch.setattr(hfr, "get_httpx_verify", lambda: False)
    monkeypatch.setattr(hfr, "GUARD_ENABLED", True)
    monkeypatch.setattr(hfr, "LOCAL_TRUST_DOMAIN", LOCAL)
    monkeypatch.setattr(hfr, "LOCAL_FRAME", "A")
    hfr.cache_clear()
    yield calls
    hfr.cache_clear()


def _async_verdict(did):
    hfr.cache_clear()
    try:
        asyncio.run(hfr.async_check_home_or_raise(did))
        return "ok"
    except hfr.AgentNotHomeError as e:
        return ("refused", e.home_frame, e.this_frame)


def _sync_verdict(did):
    hfr.cache_clear()
    try:
        hfr.check_home_or_raise(did)
        return "ok"
    except hfr.AgentNotHomeError as e:
        return ("refused", e.home_frame, e.this_frame)


@pytest.mark.parametrize("did", [NATIVE, NATIVE2])
def test_a_native_receiver_gets_its_first_profile(rig, did):
    assert _async_verdict(did) == "ok"
    assert rig == [[did]]                       # the registry was asked: the home was known, and it is this frame


def test_a_receiver_homed_elsewhere_is_refused_naming_both_trust_domains(rig):
    assert _async_verdict(FOREIGN) == ("refused", "asia.theprotocol.cloud", LOCAL)


@pytest.mark.parametrize("did", [NATIVE, NATIVE2, FOREIGN, NOCARD])
def test_the_async_check_agrees_with_the_sync_check(rig, did):
    assert _async_verdict(did) == _sync_verdict(did)


def test_control_an_unknown_home_is_allowed_and_the_guard_off_asks_nothing(rig, monkeypatch):
    assert _async_verdict(NOCARD) == "ok"
    monkeypatch.setattr(hfr, "GUARD_ENABLED", False)
    rig.clear()
    assert _async_verdict(FOREIGN) == "ok" and rig == []


@pytest.mark.parametrize("spiffe,letter", [
    ("spiffe://frame-b.theprotocol.cloud/service/teg-layer", "B"), ("SPIFFE://Frame-B.theprotocol.cloud./x", "B"),
    ("spiffe://agentvault.com/service/registry", "A"),
    ("spiffe://frame-b.theprotocol.cloud.evil.test/x", None), ("spiffe://evil-frame-b.example/x", None),
    ("spiffe://notagentvault.com/x", None), ("spiffe://eu.theprotocol.cloud/x", None),
    ("frame-b.theprotocol.cloud", None), ("", None), (None, None),
])
def test_the_spiffe_letter_reads_the_whole_trust_domain(spiffe, letter):
    assert hfr._spiffe_to_frame(spiffe) == letter


@pytest.mark.parametrize("td,letter", [("frame-b.theprotocol.cloud", "B"), ("agentvault.com", "A"),
                                       ("eu.theprotocol.cloud", "A"), ("frame-b.evil.test", "A")])
def test_the_local_letter_reads_the_whole_trust_domain(td, letter):
    # a fresh process: the module derives LOCAL_FRAME once, at import (a reload here would leave the app's 409 handler
    # bound to a stale exception class for the tests after this one)
    env = dict(os.environ, SPIRE_TRUST_DOMAIN=td, PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1")
    probe = "import teg_core_service.database.home_frame_resolver as m; print(m.LOCAL_FRAME)"
    r = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().splitlines()[-1] == letter
