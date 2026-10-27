"""§OPDIST (2026-09-16): a venue the auditor cannot read says WHAT it observed, and a failed read is not "unreachable".

Measured on beacon the day this was written: the runner wired jelgava's share register into beacon's kit auditor and the
auditor answered, for two different defects, one sentence: "registry DB not reachable from the auditor". Its own log
held the observation (`PostgreSQL server at "cloud-op-jelgava-db:5432" rejected SSL upgrade`: the kit auditor speaks
verify-full TLS and the operator's Postgres serves none), and the second defect sat behind it (the read-only role could
not read exchange_trades, which three of the five share queries read: a pool that connects and a read that fails also
returned None, and the same sentence). The runner's CONNECTED verdict and its job note repeat what this endpoint says,
so the cause has to be in the answer, not only in a log line nobody reads.

RED on the base:
  1. a pool that cannot be established answers reach_status "unreachable" with the connect error in the note, and a
     password is never in the answer, even when the error text carries the DSN;
  2. a pool that connects and a share read that fails answers "read_failed", never "unreachable";
  3. a reading served from the cache after a failed read answers "stale" and names the failure;
  4. a success clears the recorded failure (a claim must not outlive what made it true);
  5. a replaced venue does not keep the failure recorded against its previous entry.
CONTROL that passes on the base: a good read answers reachable "ok".
"""
import asyncio
import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE
TOKEN = "admin-token-for-venue-reach-tests"
PW = "s3cret-venue-pw-4f1a"
DSN = f"postgresql://auditor_ro:{PW}@cloud-op-probe-db:5432/agentvault_registry"


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


class FakeCon:
    def __init__(self, fail=None):
        self.fail = fail

    async def fetch(self, sql, *args):
        if self.fail:
            raise Exception(self.fail)
        return []

    async def execute(self, sql, *args):
        return "SET"

    def transaction(self):
        class T:
            async def __aenter__(s):
                return s

            async def __aexit__(s, *a):
                return False
        return T()


class FakePool:
    def __init__(self, con):
        self.con = con
        self.terminated = False

    def acquire(self):
        pool = self

        class A:
            async def __aenter__(s):
                return pool.con

            async def __aexit__(s, *a):
                return False
        return A()

    def terminate(self):
        self.terminated = True


class FakeAsyncpg:
    def __init__(self):
        self.connect_error = None
        self.con = FakeCon()

    async def create_pool(self, **kw):
        if self.connect_error:
            raise Exception(self.connect_error)
        return FakePool(self.con)


@pytest.fixture()
def boot(tmp_path, monkeypatch):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "frames.json").write_text("[]")
    vf = frames_dir / "venues.json"

    def _boot(venues):
        _purge()
        for k in list(os.environ):
            if (k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or k.endswith("_REG_DSN")
                    or k == "VENUE_REG_DSNS_JSON" or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE")):
                monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
        monkeypatch.setenv("AUDITOR_SOLO", "true")
        monkeypatch.setenv("AUDITOR_ADMIN_TOKEN", TOKEN)
        monkeypatch.setenv("AUDITOR_EXTRA_FRAMES_FILE", str(frames_dir / "frames.json"))
        vf.write_text(json.dumps(venues))
        monkeypatch.syspath_prepend(TREE)
        main = importlib.import_module("src.auditor.main")
        fake = FakeAsyncpg()
        monkeypatch.setattr(main, "asyncpg", fake)
        return main, fake, vf

    return _boot


def _venue(dsn=DSN):
    return {"probe": {"dsn": dsn, "currency": "BCN", "frame": "beacon"}}


def _shares(main):
    return asyncio.run(main._venue_shares())["probe"]


def test_control_a_good_read_is_reachable_ok(boot):
    main, fake, _ = boot(_venue())
    v = _shares(main)
    assert v["reachable"] is True and v["reach_status"] == "ok"


def test_red_a_pool_that_cannot_be_established_names_the_observed_error(boot):
    main, fake, _ = boot(_venue())
    fake.connect_error = 'PostgreSQL server at "cloud-op-probe-db:5432" rejected SSL upgrade'
    v = _shares(main)
    assert v["reachable"] is False and v["reach_status"] == "unreachable"
    assert "rejected SSL upgrade" in (v.get("note") or ""), v


def test_red_a_connect_error_that_carries_the_dsn_never_carries_the_password(boot):
    main, fake, _ = boot(_venue())
    fake.connect_error = f"invalid connection option in {DSN}?sslmode=bogus"
    v = _shares(main)
    blob = json.dumps(v)
    assert PW not in blob, "the venue answer printed the read-only password"
    assert "cloud-op-probe-db" in (v.get("note") or ""), "the redaction removed the observation along with the secret"


def test_red_a_failed_read_is_read_failed_never_unreachable(boot):
    main, fake, _ = boot(_venue())
    fake.con = FakeCon(fail="permission denied for table exchange_trades")
    v = _shares(main)
    assert v["reachable"] is False
    assert v["reach_status"] == "read_failed", "a pool that connected and a read that failed is not 'unreachable'"
    assert "permission denied for table exchange_trades" in (v.get("note") or ""), v


def test_red_a_stale_reading_after_a_failed_read_says_so(boot, monkeypatch):
    main, fake, _ = boot(_venue())
    assert _shares(main)["reach_status"] == "ok"
    monkeypatch.setattr(main, "_SHARES_REFRESH_SEC", 0.0)   # the reading is now due for a refresh
    fake.con.fail = "permission denied for table exchange_trades"
    v = _shares(main)
    assert v["reach_status"] == "stale", "an old reading served after a failed read must not answer ok"
    assert "permission denied for table exchange_trades" in (v.get("note") or ""), v


def test_red_a_success_clears_the_recorded_failure(boot, monkeypatch):
    main, fake, _ = boot(_venue())
    fake.connect_error = 'PostgreSQL server at "cloud-op-probe-db:5432" rejected SSL upgrade'
    first = _shares(main)
    assert first["reach_status"] == "unreachable" and "rejected SSL upgrade" in (first.get("note") or ""), \
        "the failure was never reported, so its clearing proves nothing"
    fake.connect_error = None
    v = _shares(main)
    assert v["reach_status"] == "ok" and not v.get("note"), "a failure recorded earlier outlived the success"


def test_red_a_successful_read_clears_a_recorded_read_failure(boot, monkeypatch):
    # the pool stays up across both calls, so only the READ's success can clear this one
    main, fake, _ = boot(_venue())
    fake.con = FakeCon(fail="permission denied for table exchange_trades")
    first = _shares(main)
    assert first["reach_status"] == "read_failed" and "exchange_trades" in (first.get("note") or "")
    fake.con.fail = None
    v = _shares(main)
    assert v["reach_status"] == "ok" and not v.get("note"), "a read failure outlived the read that succeeded"


def test_red_a_replaced_venue_does_not_keep_the_previous_entrys_failure(boot):
    main, fake, vf = boot(_venue())
    fake.con = FakeCon(fail="permission denied for table exchange_trades")
    assert _shares(main)["reach_status"] == "read_failed"
    vf.write_text(json.dumps(_venue(DSN.replace(PW, PW + "-rotated"))))
    out = asyncio.run(main.api_reload_venues(x_auditor_admin=TOKEN))
    assert out["replaced"] == ["venue:probe"], out
    assert "venue:probe" not in main._share_errors, "the replaced entry kept the old entry's failure"
