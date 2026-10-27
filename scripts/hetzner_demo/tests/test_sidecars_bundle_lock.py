"""A frame's teardown and the 5-minute bundle refresh take one lock (§NIGHTPROV, 2026-10-06).

Nightly nt261006: the 01:05:00Z run of frame-spire-bundle.sh was still walking /etc/theprotocol/frame-spire-bundles.list
when nt261006a's teardown removed its line and its pem (01:05:02Z); the run fetched from the still-running server,
found the file absent ("was 0 / 0 valid") and wrote it back, and the pair's leftover check failed on it. The refresh
script now holds FRAME_SPIRE_BUNDLE_LOCK for its whole run and `unregister_bundle` holds it while the lines and files
go, releasing it before it runs the refresh itself (the refresh takes it too). Pinned on fixture files and a fixture
lock, never on this host's live ones: the frame name is one no host carries, so the per-frame pem under /etc/nginx is
only ever tested for existence, and the net is the `left` branch (no `nginx -t`).
"""
import fcntl
import importlib.util
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DRIVER_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


sc = _load("sidecars")
NAME = "zzbundlelocktest"            # no host has a frame of this name: /etc/nginx/<it>-spire-bundle.pem never exists
PEM = f"/etc/nginx/{NAME}-spire-bundle.pem"
OTHER = "/etc/nginx/zzbundlelockpeer-spire-bundle.pem"


def _fixture(tmp_path, monkeypatch):
    lock = tmp_path / "bundle.lock"
    monkeypatch.setattr(sc, "FRAME_SPIRE_BUNDLE_LOCK", str(lock))
    frames, fed = tmp_path / "frames.list", tmp_path / "federated.list"
    net_list, net_pem = tmp_path / "net.list", tmp_path / "net.pem"
    frames.write_text(f"{PEM} {NAME}-spire-server\n{OTHER} zzbundlelockpeer-spire-server\n")
    net_list.write_text(f"{PEM}\n{OTHER}\n")
    fed.write_text(f"{net_list} {net_pem}\n")
    marker = tmp_path / "refresh.ran"
    refresh = tmp_path / "refresh.sh"
    # the refresh records whether the lock was FREE when it ran (flock -n succeeds only then)
    refresh.write_text(f"#!/bin/sh\nif flock -n {lock} true; then echo free > {marker}; else echo held > {marker}; fi\n")
    refresh.chmod(0o755)
    m = {"bundles": {"frames_list": str(frames), "federated_lists": str(fed), "refresh": str(refresh),
                     "federated_by_net": {"zznet": {"list": str(net_list), "pem": str(net_pem)}}}}
    return m, lock, frames, net_list, marker


def test_the_lines_go_only_once_a_running_refresh_lets_go(tmp_path, monkeypatch):
    m, lock, frames, net_list, marker = _fixture(tmp_path, monkeypatch)
    held = threading.Event()
    released_at = {}

    def holder():   # a refresh run in the middle of the list
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        held.set()
        time.sleep(1.5)
        released_at["t"] = time.time()
        os.close(fd)

    th = threading.Thread(target=holder); th.start(); held.wait(5)
    logs = []
    sc.unregister_bundle(m, NAME, "zznet", log=logs.append)
    th.join()
    assert PEM not in frames.read_text() and OTHER in frames.read_text(), frames.read_text()
    assert net_list.read_text().split() == [OTHER]
    # the frame's line went AFTER the holder let go: the list was rewritten at or after the release
    assert os.stat(frames).st_mtime >= released_at["t"] - 0.05, (os.stat(frames).st_mtime, released_at)
    assert any("unregistered" in x for x in logs), logs


def test_the_refresh_it_runs_finds_the_lock_free(tmp_path, monkeypatch):
    m, lock, frames, net_list, marker = _fixture(tmp_path, monkeypatch)
    sc.unregister_bundle(m, NAME, "zznet", log=lambda s: None)
    assert marker.read_text().strip() == "free", "the refresh ran while unregister_bundle still held the lock"


def test_a_lock_that_cannot_be_opened_is_named_and_the_step_goes_on(tmp_path, monkeypatch):
    m, lock, frames, net_list, marker = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sc, "FRAME_SPIRE_BUNDLE_LOCK", str(tmp_path / "no-such-dir" / "bundle.lock"))
    logs = []
    sc.unregister_bundle(m, NAME, "zznet", log=logs.append)
    assert PEM not in frames.read_text()
    assert any("not opened" in x and "without the refresh lock" in x for x in logs), logs


def test_a_lock_held_past_the_wait_is_named_and_the_step_goes_on(tmp_path, monkeypatch):
    m, lock, frames, net_list, marker = _fixture(tmp_path, monkeypatch)
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        logs = []
        with sc._bundle_writer_lock(logs.append, timeout=0.6) as held:
            assert held is False
        assert any("still held after" in x for x in logs), logs
    finally:
        os.close(fd)
    with sc._bundle_writer_lock(lambda s: None, timeout=0.6) as held:
        assert held is True
