"""§DOCKERSTATSRACE (2026-09-28) — a container that vanishes mid-listing costs its own row, never the route.

Measured on sbx-alpha during the V0488 tester run: GET /api/v1/admin/docker-stats answered 503 with
"404 ... No such container: 4239...". docker-py's plain `containers.list()` inspects EVERY container on the
host (about 300 here) before the route's 'agentvault' filter runs, and outside the per-container try, so a
container removed in between (a CI job, a `docker run --rm`) raised out of the listing and failed the whole
call. The route now lists SPARSE, names each entry from the list response, and a vanished container fails
only its own stats() read, which the per-container try already skips.

Red on the code before §DOCKERSTATSRACE except the named control.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.routers import admin_health as ah  # noqa: E402
from agentvault_registry.services import host_observe as ho  # noqa: E402


class NotFound(Exception):
    """Stands in for docker.errors.NotFound: the product catches Exception, never the class by name."""


def _stats_doc():
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": 200, "percpu_usage": [1, 1]}, "system_cpu_usage": 2000},
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
        "memory_stats": {"usage": 50 * 1024 * 1024, "limit": 100 * 1024 * 1024},
        "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20}},
        "blkio_stats": {"io_service_bytes_recursive": []},
    }


class _Entry:
    """One container as the daemon lists it. list(sparse=True) hands it back as is (docker-py 7.x: attrs with
    `Names`, no `Name`, so `.name` is None); the plain list() INSPECTS it first (GET /containers/{id}/json),
    which is where a container removed since the listing raises."""

    def __init__(self, name, cid, gone=False):
        self._name = name
        self.attrs = {"Names": ["/" + name], "Id": cid, "State": "running"}
        self.id, self.short_id, self.status, self.name = cid, cid[:12], "running", None
        self._gone = gone
        self.stats_calls = 0
        self.inspect_calls = 0

    def inspect(self):
        self.inspect_calls += 1
        if self._gone:
            raise NotFound(f"404 Client Error for http+docker://localhost/v1.55/containers/{self.id}/json")
        self.attrs["Name"], self.name = "/" + self._name, self._name
        return self

    def stats(self, stream=False):
        self.stats_calls += 1
        if self._gone:
            raise NotFound(f"404 Client Error: Not Found (\"No such container: {self.id}\")")
        return _stats_doc()


def _fake_docker(monkeypatch, entries):
    """A daemon listing the way docker-py does: sparse answers from the list alone, plain inspects every entry."""
    def _list(**kw):
        return list(entries) if kw.get("sparse") else [e.inspect() for e in entries]
    fake = types.ModuleType("docker")
    fake.from_env = lambda: types.SimpleNamespace(containers=types.SimpleNamespace(list=_list))
    monkeypatch.setattr(ah, "docker", fake, raising=False)
    monkeypatch.delenv(ho.OBSERVE_VIA_ENV, raising=False)


def test_a_container_removed_mid_listing_does_not_fail_the_route(monkeypatch):
    kept = _Entry("agentvault-registry-a", "aaaaaaaaaaaa1111")
    gone = _Entry("agentvault-ci-job", "4239316500000000", gone=True)
    other = _Entry("eu-registry", "bbbbbbbbbbbb2222")
    _fake_docker(monkeypatch, [kept, gone, other])
    out = ah._collect_docker_stats_sync()
    assert set(out["containers"]) == {"agentvault-registry-a"}, out["containers"].keys()
    assert out["container_count"] == 1


def test_a_container_outside_the_filter_costs_no_call(monkeypatch):
    """The filter runs on the list response: the plain listing inspected all ~300 containers on the host to
    report ~46, and every one of those inspects was a chance to meet a container that had just gone."""
    kept = _Entry("agentvault-event-store", "cccccccccccc3333")
    other = _Entry("eu-registry", "dddddddddddd4444")
    _fake_docker(monkeypatch, [kept, other])
    ah._collect_docker_stats_sync()
    assert kept.stats_calls == 1 and other.stats_calls == 0
    assert other.inspect_calls == 0, "a container the route does not report was inspected anyway"


def test_a_sparse_entry_is_named_from_the_list():
    assert ah._listed_name(_Entry("agentvault-x", "e" * 16)) == "agentvault-x"
    assert ah._listed_name(types.SimpleNamespace(attrs={"Name": "/agentvault-y"})) == "agentvault-y"
    assert ah._listed_name(types.SimpleNamespace(name="agentvault-z")) == "agentvault-z"
    row = ho.RunnerContainer({"id": "f" * 16, "name": "sbx-registry", "state": "running", "stats": _stats_doc()})
    assert ah._listed_name(row) == "sbx-registry"


def test_a_failed_stats_read_still_skips_only_that_container(monkeypatch):
    """Control (green before and after): a container whose stats() fails is skipped, the rest reported.
    Full-shaped entries that every list() form returns, so the old listing cannot fail here."""
    good = types.SimpleNamespace(name="agentvault-ok", short_id="111111111111", status="running",
                                 stats=lambda stream=False: _stats_doc())

    def _boom(stream=False):
        raise RuntimeError("daemon said no")

    bad = types.SimpleNamespace(name="agentvault-bad", short_id="222222222222", status="running", stats=_boom)
    fake = types.ModuleType("docker")
    fake.from_env = lambda: types.SimpleNamespace(containers=types.SimpleNamespace(list=lambda **kw: [good, bad]))
    monkeypatch.setattr(ah, "docker", fake, raising=False)
    monkeypatch.delenv(ho.OBSERVE_VIA_ENV, raising=False)
    out = ah._collect_docker_stats_sync()
    assert set(out["containers"]) == {"agentvault-ok"}
