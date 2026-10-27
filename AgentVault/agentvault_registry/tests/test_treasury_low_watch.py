"""§MONEY-R43 — "the treasury is running low" reaches a person BEFORE it reaches a caller.

Behaviour tests against the real worker with its reads and its delivery monkeypatched, plus the
declarations that make the feature real: the catalog keys, the org setting, the profile knob.

What must hold:
  · with the threshold at 0 (today's fleet) the gauge is published and NOBODY is notified;
  · crossing DOWN notifies once; staying down notifies nobody; crossing UP notifies once (recovery);
  · a platform read that fails RAISES (the cycle stamps ERROR) and the state is untouched — "could
    not read" is never "recovered";
  · an org read that fails is counted and skipped, the cycle goes on;
  · org owners+admins are the recipients, nobody else.
Control: the hysteresis assertions are their own control — a watcher that notified every cycle fails
`test_staying_low_notifies_nobody`; one that never notified fails `test_crossing_down_notifies_once`.
"""
from __future__ import annotations

import ast
import os
import pathlib
from decimal import Decimal

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/agentvault_registry")
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/agentvault_registry")

from agentvault_registry.background_tasks import treasury_low_watch as tlw  # noqa: E402


class _Recorder:
    def __init__(self):
        self.calls = []

    async def audience(self, type_key, **kw):
        self.calls.append(("audience", type_key, kw))
        return 1

    async def direct(self, type_key, dev_ids, **kw):
        self.calls.append(("direct", type_key, list(dev_ids), kw))
        return len(list(dev_ids))


@pytest.fixture
def worker(monkeypatch):
    """A worker whose reads, delivery and state are ours. Redis is unavailable on purpose,
    so the state lives in the worker's memory fallback (deterministic in a test)."""
    w = tlw.TreasuryLowWatchWorker()
    balances = {"platform": Decimal("1000"), "orgs": []}
    rec = _Recorder()

    async def _read_platform():
        v = balances["platform"]
        if isinstance(v, Exception):
            raise v
        return v

    async def _orgs():
        return balances["orgs"]

    async def _read_org(did):
        for o in balances["orgs"]:
            if o["did"] == did:
                v = o.get("balance")
                if isinstance(v, Exception):
                    raise v
                return v
        raise KeyError(did)

    async def _no_redis():
        return None

    monkeypatch.setattr(w, "_read_platform_balance", _read_platform)
    monkeypatch.setattr(w, "_org_candidates", _orgs)
    monkeypatch.setattr(w, "_read_org_balance", _read_org)
    import agentvault_registry.background_tasks.leader as leader
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    import agentvault_registry.background_tasks.push_notify as pn
    monkeypatch.setattr(pn, "notify_audience", rec.audience)
    monkeypatch.setattr(pn, "notify", rec.direct)
    monkeypatch.setenv("FRAME_CURRENCY", "AVT")
    return w, balances, rec


# ---------------------------------------------------------------- pure rule
def test_transition_rule():
    assert tlw._transition(None, True) == "low"          # first sight, already low: somebody must hear
    assert tlw._transition(None, False) is None          # first sight, fine: silence
    assert tlw._transition("ok", True) == "low"
    assert tlw._transition("low", True) is None          # staying low: no repeat
    assert tlw._transition("low", False) == "recovered"
    assert tlw._transition("ok", False) is None


def test_threshold_parsing(monkeypatch):
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "250000")
    assert tlw._threshold() == Decimal("250000")
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "abc")
    assert tlw._threshold() == Decimal("0")
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "-5")
    assert tlw._threshold() == Decimal("0")
    monkeypatch.delenv("TREASURY_LOW_NOTIFY_THRESHOLD", raising=False)
    assert tlw._threshold() == Decimal("0")


# ---------------------------------------------------------------- platform behaviour
@pytest.mark.asyncio
async def test_disabled_threshold_publishes_but_notifies_nobody(worker, monkeypatch):
    w, balances, rec = worker
    monkeypatch.delenv("TREASURY_LOW_NOTIFY_THRESHOLD", raising=False)
    balances["platform"] = Decimal("1")
    await w._cycle_once()
    assert rec.calls == []
    assert w._stats["state"] == "disabled" and w._stats["platform_balance"] == "1"


@pytest.mark.asyncio
async def test_crossing_down_notifies_once_and_recovery_once(worker, monkeypatch):
    w, balances, rec = worker
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "500")
    balances["platform"] = Decimal("900")
    await w._cycle_once()
    assert rec.calls == [] and w._stats["state"] == "ok"
    balances["platform"] = Decimal("100")
    await w._cycle_once()                       # crossing down
    assert [c[1] for c in rec.calls] == ["treasury.low"]
    assert rec.calls[0][2]["priority"] == "high" and "running low" in rec.calls[0][2]["title"]
    await w._cycle_once()                       # staying low
    await w._cycle_once()
    assert len(rec.calls) == 1, "staying low must not repeat the notice"
    balances["platform"] = Decimal("800")
    await w._cycle_once()                       # recovery
    assert len(rec.calls) == 2 and "back above" in rec.calls[1][2]["title"]
    await w._cycle_once()                       # staying fine
    assert len(rec.calls) == 2


@pytest.mark.asyncio
async def test_first_sight_below_threshold_notifies(worker, monkeypatch):
    w, balances, rec = worker
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "500")
    balances["platform"] = Decimal("10")
    await w._cycle_once()
    assert [c[1] for c in rec.calls] == ["treasury.low"]


@pytest.mark.asyncio
async def test_failed_platform_read_raises_and_moves_no_state(worker, monkeypatch):
    w, balances, rec = worker
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "500")
    balances["platform"] = Decimal("100")
    await w._cycle_once()                       # low, notified once
    assert len(rec.calls) == 1
    balances["platform"] = RuntimeError("TEG unreachable")
    with pytest.raises(RuntimeError):
        await w._cycle_once()
    assert len(rec.calls) == 1, "a failed read must not be reported as anything"
    assert w._mem_state["platform"] == "low", "the state must be untouched by a failed read"
    balances["platform"] = Decimal("900")
    await w._cycle_once()
    assert len(rec.calls) == 2 and "back above" in rec.calls[1][2]["title"]


# ---------------------------------------------------------------- org behaviour
@pytest.mark.asyncio
async def test_org_admins_are_notified_once_and_failed_org_reads_are_counted(worker, monkeypatch):
    w, balances, rec = worker
    monkeypatch.delenv("TREASURY_LOW_NOTIFY_THRESHOLD", raising=False)   # platform disabled
    balances["orgs"] = [
        {"id": "org-1", "name": "Halden", "threshold": Decimal("50"), "did": "did:org1",
         "developer_ids": [11, 12], "balance": Decimal("10")},
        {"id": "org-2", "name": "Kestrel", "threshold": Decimal("50"), "did": "did:org2",
         "developer_ids": [21], "balance": RuntimeError("mover unreachable")},
        {"id": "org-3", "name": "Marlow", "threshold": Decimal("50"), "did": "did:org3",
         "developer_ids": [31], "balance": Decimal("500")},
    ]
    await w._cycle_once()
    direct = [c for c in rec.calls if c[0] == "direct"]
    assert [(c[1], c[2]) for c in direct] == [("org.treasury.low", [11, 12])]
    assert w._stats["orgs_checked"] == 3 and w._stats["org_read_failed"] == 1
    await w._cycle_once()                       # org-1 still low: silence
    assert len([c for c in rec.calls if c[0] == "direct"]) == 1
    balances["orgs"][0]["balance"] = Decimal("100")
    await w._cycle_once()                       # org-1 recovers
    direct = [c for c in rec.calls if c[0] == "direct"]
    assert len(direct) == 2 and "back above" in direct[1][3]["title"]


# ---------------------------------------------------------------- declarations
def test_catalog_declares_both_keys():
    from agentvault_registry.services.notification_catalog import get_type
    t = get_type("treasury.low")
    assert t is not None and t.audience == "admin" and t.severity == "warning" and not t.mandatory
    assert t.default_enabled.get("push_desktop") and t.default_enabled.get("push_mobile")
    o = get_type("org.treasury.low")
    assert o is not None and o.audience == "developer" and o.severity == "warning" and not o.mandatory


def test_org_setting_is_a_real_catalog_key():
    from agentvault_registry.services.org_policy import ORG_SETTING_CATALOG
    entry = next((e for e in ORG_SETTING_CATALOG if e["key"] == tlw.ORG_SETTING_KEY), None)
    assert entry is not None, "treasury_low_notify_threshold must be validated by the org setting catalog"
    assert entry["type"] == "number" and entry.get("min", 1) == 0


def test_profile_knob_names_this_reader():
    knobs = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "network_profile_knobs.py"
    if not knobs.is_file():
        knobs = pathlib.Path("/w/scripts/network_profile_knobs.py")
    if not knobs.is_file():
        pytest.skip("scripts/ not mounted here — NOT MEASURED")
    src = knobs.read_text(encoding="utf-8")
    assert 'name="TREASURY_LOW_NOTIFY_THRESHOLD"' in src
    assert "treasury_low_watch.py::_threshold" in src


def test_the_worker_is_a_background_worker_with_a_vitals_registered_id():
    tree = ast.parse((SRC / "background_tasks" / "treasury_low_watch.py").read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "TreasuryLowWatchWorker")
    assert any(getattr(b, "id", "") == "BackgroundWorker" for b in cls.bases), "must ride _worker_base (vitals + leader for free)"
    ids = [n.value.value for n in ast.walk(cls) if isinstance(n, ast.Assign)
           and any(getattr(t, "id", "") == "worker_id" for t in n.targets) and isinstance(n.value, ast.Constant)]
    assert ids == ["treasury_low_watch"]
    # and main.py starts it
    main = (SRC / "main.py").read_text(encoding="utf-8")
    assert "treasury_low_watch_worker.start()" in main
