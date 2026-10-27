"""§DIGESTSTALL (2026-09-28): a digest mismatch that outlives its repair walks must still be walked, at a slower cadence.

Measured on production after V0484 (read-only): the §FEDSYNC-V2 back-off stopped walking FOR GOOD once a mismatch
survived two repair walks, and the miss counter clears only on an equal digest, which a divergence that only a walk can
heal never reaches. ASIA's counters read 6 for every peer, EU's 4-6, the operators' 3-7: no node walked anyone, and a
mirror stuck since 2026-09-12 could not heal on V0484, which heals it on the next walk. Pinned here, driving
FederationSyncWorker._maybe_reconcile_one_peer against an in-memory Redis:
  - a persistent mismatch walks once per backed-off check, and the cadence survives a walk that pauses on its budget;
  - a new image pulls one check forward per peer; the same image does not;
  - a REFUSED probe (401/403 = "skipped") never counts as a mismatch and never walks (agentvault2-a4's edge: under
    licence enforce a refused peer must not read as out of sync);
  - the unchanged paths: an equal digest clears the counter; a first mismatch walks and verifies soon.
RED control: the tree before §DIGESTSTALL fails exactly the walk, cadence and fresh-look tests; the other four pin
behaviour that did not change and pass on both.
"""
from __future__ import annotations

import types

import pytest

from agentvault_registry.background_tasks import federation_sync as fs

NOW = 1_790_000_000.0
DAY = 86_400.0
PEER = types.SimpleNamespace(name="EU")
# The image key is spelled out as a fallback so the RED control can load this file against the old module and fail
# only the tests that pin the new behaviour.
NEXT, MISS, IMAGE, CURSOR = (fs._DIGEST_NEXT_PREFIX + "EU", fs._DIGEST_MISS_PREFIX + "EU",
                             getattr(fs, "_DIGEST_IMAGE_PREFIX", "registry:federation:digest_image:") + "EU",
                             fs._RECONCILE_CURSOR_PREFIX + "EU")


class _Clock:
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t


class _Sync:
    """The peer: a scripted digest verdict, and walks that may pause on their budget (leave a cursor) once."""

    def __init__(self, store, verdict, pause_first_walk=False):
        self.store, self.verdict, self.pause = store, verdict, pause_first_walk
        self.calls = []

    async def __call__(self, peer, our_spiffe_id, digest_probe=False, reconcile=False):
        if digest_probe:
            self.calls.append("probe")
            return self.verdict
        self.calls.append("walk")
        if self.pause:
            self.pause = False
            self.store[CURSOR] = "2026-09-28T00:00:00+00:00"
        else:
            self.store.pop(CURSOR, None)
        return True


class _Session:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def rig(monkeypatch):
    store, clock = {}, _Clock(NOW)

    async def _get(key):
        return store.get(key)

    async def _set(key, value):
        store[key] = str(value)

    async def _del(key):
        store.pop(key, None)

    async def _redis():
        return types.SimpleNamespace(set=lambda *a, **k: None)

    async def _peers(db, skip=0, limit=1000):
        return [PEER]

    monkeypatch.setattr(fs, "_reconcile_get", _get)
    monkeypatch.setattr(fs, "_reconcile_set", _set)
    monkeypatch.setattr(fs, "_reconcile_del", _del)
    monkeypatch.setattr(fs, "_reconcile_redis", _redis)
    monkeypatch.setattr(fs, "_reconcile_interval_seconds", lambda: 7 * DAY)
    monkeypatch.setattr(fs, "_digest_interval_seconds", lambda: DAY)
    monkeypatch.setattr(fs, "_reconcile_jitter_frac", lambda name: 0.5)
    monkeypatch.setattr(fs, "_time_mod", clock)
    monkeypatch.setattr(fs, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(fs.crud_peer_registry, "list_active_peer_registries_all", _peers)
    monkeypatch.setattr(fs.svid_client, "get_spiffe_id", lambda: "spiffe://test/registry")
    monkeypatch.setattr(fs, "_running_image_tag", lambda: "V_NOW", raising=False)
    return types.SimpleNamespace(store=store, clock=clock, monkeypatch=monkeypatch)


def _worker(sync):
    w = object.__new__(fs.FederationSyncWorker)
    w._sync_with_peer = sync
    return w


async def test_a_persistent_mismatch_still_walks_at_the_backed_off_cadence(rig):
    rig.store.update({NEXT: str(NOW - 1), MISS: "6", IMAGE: "V_NOW"})
    sync = _Sync(rig.store, "digest_mismatch")
    await _worker(sync)._maybe_reconcile_one_peer()
    assert sync.calls == ["probe", "walk"], "a backed-off mismatch stopped walking (the stall)"
    assert rig.store[MISS] == "7"
    assert float(rig.store[NEXT]) == NOW + 7 * DAY, "the walk's verify stamp pulled the backed-off check earlier"


async def test_the_backed_off_cadence_survives_a_walk_that_pauses_on_its_budget(rig):
    rig.store.update({NEXT: str(NOW - 1), MISS: "3", IMAGE: "V_NOW"})
    sync = _Sync(rig.store, "digest_mismatch", pause_first_walk=True)
    w = _worker(sync)
    await w._maybe_reconcile_one_peer()                    # probe, walk pauses (cursor left)
    assert CURSOR in rig.store and float(rig.store[NEXT]) == NOW + 4 * DAY
    rig.clock.t = NOW + 60
    await w._maybe_reconcile_one_peer()                    # branch (1): the walk resumes and finishes
    assert sync.calls == ["probe", "walk", "walk"] and CURSOR not in rig.store
    assert float(rig.store[NEXT]) == NOW + 4 * DAY, "a resumed walk turned the back-off into an hourly check"


async def test_a_new_image_gets_one_fresh_look(rig):
    rig.store.update({NEXT: str(NOW + 6 * DAY), MISS: "6", IMAGE: "V_OLD"})
    sync = _Sync(rig.store, "digest_mismatch")
    w = _worker(sync)
    await w._maybe_reconcile_one_peer()
    soon = NOW + DAY * (0.02 + 0.08 * 0.5)
    assert rig.store[IMAGE] == "V_NOW" and float(rig.store[NEXT]) == soon and sync.calls == []
    rig.clock.t = soon + 1
    await w._maybe_reconcile_one_peer()
    assert sync.calls == ["probe", "walk"], "the new image's fresh look did not walk the divergence"
    rig.clock.t = soon + 2
    await w._maybe_reconcile_one_peer()                    # the same image: nothing more until the backed-off check
    assert sync.calls == ["probe", "walk"]


async def test_the_same_image_does_not_pull_a_check_forward(rig):
    rig.store.update({NEXT: str(NOW + 6 * DAY), MISS: "6", IMAGE: "V_NOW"})
    sync = _Sync(rig.store, "digest_mismatch")
    await _worker(sync)._maybe_reconcile_one_peer()
    assert sync.calls == [] and float(rig.store[NEXT]) == NOW + 6 * DAY


async def test_a_refused_probe_never_counts_as_a_mismatch(rig):
    rig.store.update({NEXT: str(NOW - 1), MISS: "2", IMAGE: "V_NOW"})
    sync = _Sync(rig.store, "skipped")
    await _worker(sync)._maybe_reconcile_one_peer()
    assert sync.calls == ["probe"] and rig.store[MISS] == "2"
    assert float(rig.store[NEXT]) == NOW + 0.1 * DAY


async def test_an_equal_digest_clears_the_counter(rig):
    rig.store.update({NEXT: str(NOW - 1), MISS: "6", IMAGE: "V_NOW"})
    sync = _Sync(rig.store, "digest_equal")
    await _worker(sync)._maybe_reconcile_one_peer()
    assert sync.calls == ["probe"] and MISS not in rig.store
    assert float(rig.store[NEXT]) == NOW + DAY * (0.9 + 0.2 * 0.5)


async def test_a_first_mismatch_walks_and_verifies_soon(rig):
    rig.store.update({NEXT: str(NOW - 1), IMAGE: "V_NOW"})
    sync = _Sync(rig.store, "digest_mismatch")
    await _worker(sync)._maybe_reconcile_one_peer()
    assert sync.calls == ["probe", "walk"] and rig.store[MISS] == "1"
    assert float(rig.store[NEXT]) == NOW + max(1800.0, DAY * 0.05)
