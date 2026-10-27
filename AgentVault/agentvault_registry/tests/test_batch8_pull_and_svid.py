"""§BATCH8 items 4 + 5 (2026-09-06).

4. `federation_sync.is_peer_frames_operator`: a `discovered` row inside a directly-federated peer FRAME's
   trust domain is that frame's operator — served through the frame, never pulled (a 401 + a 33-minute
   park every cycle on the fresh pair). Own ops mis-tagged `discovered` (`is_own_reachable_op`) stay pulled.
5. `SVIDClient.watcher_state()` / `_note_poll()`: the poller reports what it did (root counts, outcome, age).
"""
import os
import time
from types import SimpleNamespace as NS

import pytest


def _peer(name, ptype, td, base_url=""):
    return NS(name=name, peer_type=ptype, trust_domain=td, base_url=base_url)


def test_peer_frames_operator_is_skipped_but_own_ops_and_frames_are_not(monkeypatch):
    from agentvault_registry.background_tasks import federation_sync as fs
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "juice.theprotocol.cloud")
    peers = [
        _peer("BRRR", "frame", "brrr.theprotocol.cloud", "https://brrr.theprotocol.cloud:8443"),
        _peer("juiceop-a", "cloud_operator", "juice.theprotocol.cloud", "https://juiceop-a.op.theprotocol.cloud:8443"),
        _peer("brrrop-a", "discovered", "brrr.theprotocol.cloud", "https://brrrop-a.op.theprotocol.cloud"),
        _peer("far-op", "discovered", "elsewhere.example", "https://far-op.op.theprotocol.cloud"),
        _peer("op-mine-mistagged", "discovered", "juice.theprotocol.cloud", "https://op-mine.juice.theprotocol.cloud"),
    ]
    skipped = [p.name for p in peers if fs.is_peer_frames_operator(p, peers)]
    assert skipped == ["brrrop-a"], skipped
    # control: without the frame row, the same discovered row is NOT a peer-frame operator
    no_frame = [p for p in peers if p.peer_type != "frame"]
    assert not fs.is_peer_frames_operator(peers[2], no_frame)
    # the frame itself and our own cloud_operator are never skipped
    assert not fs.is_peer_frames_operator(peers[0], peers) and not fs.is_peer_frames_operator(peers[1], peers)


def test_peer_frames_operator_ignores_blank_trust_domains():
    from agentvault_registry.background_tasks import federation_sync as fs
    peers = [_peer("F", "frame", ""), _peer("d", "discovered", "")]
    assert not fs.is_peer_frames_operator(peers[1], peers)


def test_svid_watcher_state_reports_roots_outcome_and_age(tmp_path, monkeypatch):
    from agentvault_registry.identity.svid_client import SVIDClient
    c = SVIDClient()
    assert c.watcher_state()["last_poll_at"] is None and c.watcher_state()["age_sec"] is None
    snap = tmp_path / "snap.bundle"; snap.write_text("-----BEGIN CERTIFICATE-----\nAA\n-----END CERTIFICATE-----\n" * 2)
    disk_dir = tmp_path / "certs"; disk_dir.mkdir()
    (disk_dir / "bundle.0.pem").write_text("-----BEGIN CERTIFICATE-----\nBB\n-----END CERTIFICATE-----\n" * 3)
    monkeypatch.setenv("SVID_CERT_DIR", str(disk_dir))
    c.bundle_path = snap
    c._note_poll(True)
    st = c.watcher_state()
    assert st["last_poll_ok"] is True and st["last_poll_roots"] == 2 and st["snapshot_roots"] == 2 and st["disk_roots"] == 3
    assert st["age_sec"] is not None and st["age_sec"] < 5 and st["last_poll_error"] == ""
    c._note_poll(False, "boom")
    st = c.watcher_state()
    assert st["last_poll_ok"] is False and st["last_poll_error"] == "boom"
    # an unreadable bundle counts as zero roots, never raises
    assert SVIDClient.count_roots(tmp_path / "absent.pem") == 0
