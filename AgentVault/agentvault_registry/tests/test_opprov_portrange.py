"""§OPPROV (2026-09-27, his words "fix operators provisioning"): the cloud operator port allocator, measured on sbx-alpha.

sbx-alpha's range CLOUD_PORT_MIN..MAX = 31100..31499 (four blocks) held its own operator at 31100 and, above it, three
blocks published by OTHER frames' operators on the same host (sbxbetaop 31200, amsterdam 31300, lisbon 31400). The
allocator scanned only ABOVE the frame's highest live block (31100 + 100), skipped the three bound blocks and refused the
provision with "No free port block found above 31100". The ranges of the frames on this host overlap (sbx-beta
31200-31599, EU 31300-32099, ASIA 32100-32899), so a sandbox frame could only ever take production's blocks; and a block
freed below a frame's highest live one was never handed out again.

The allocator now scans from CLOUD_PORT_MIN, counts this frame's live blocks from its database (cloud-hosted, not torn
down, whether or not anything binds them) and every container's CONFIGURED bindings (a stopped container publishes
nothing), and a refusal names why each block was taken. These tests call the real allocate_port_block against a
scripted database and a fake Docker; the first four fail on the pre-fix code (RED control), the last three are controls.
"""
import sys
import types

import pytest

from agentvault_registry.services import cloud_provisioner as cp


class _Result:
    def __init__(self, bases):
        self.bases = list(bases)

    def all(self):
        return [(b,) for b in self.bases]

    def scalar(self):                       # the pre-fix code asked for MAX(cloud_port_base)
        return max(self.bases) if self.bases else None


class _DB:
    """The two questions the allocator asks of the frame's database: its live blocks, and the recently torn down ones."""

    def __init__(self, live=(), torn_recently=()):
        self.live, self.torn = list(live), list(torn_recently)

    async def execute(self, stmt):
        sql = str(stmt)
        return _Result(self.torn if "cloud_torn_down_at >=" in sql else self.live)


class _Container:
    def __init__(self, name, ports=(), running=True):
        self.name = name
        binds = {f"{8000 + i}/tcp": [{"HostIp": "", "HostPort": str(p)}] for i, p in enumerate(ports)}
        self.running = running
        self.attrs = {"NetworkSettings": {"Ports": binds if running else {}},
                      "HostConfig": {"PortBindings": binds}}


def _block(name, base, running=True):
    return _Container(name, (base, base + 43, base + 80), running)


def _docker(monkeypatch, containers=(), refuses=()):
    """A docker module whose daemon holds `containers` (list(all=False) returns the running ones only, as Docker does)
    and refuses to bind the blocks in `refuses`; every bind probe it creates is recorded with whether it was removed."""
    world = {"probes": []}

    class _Probe:
        def __init__(self, base):
            self.base, self.removed = base, False
            world["probes"].append(self)

        def start(self):
            if self.base in refuses:
                raise RuntimeError(f"driver failed programming external connectivity: address already in use ({self.base})")

        def remove(self, force=False):
            self.removed = True

    class _Containers:
        def list(self, all=False, ignore_removed=False):   # the SDK's signature (ignore_removed: §DOCKERLISTRACE)
            return [c for c in containers if all or c.running]

        def create(self, image, cmd, labels=None, ports=None):
            return _Probe(int((labels or {}).get("theprotocol.port-base", "0")))

    class _Client:
        containers = _Containers()
        images = types.SimpleNamespace(pull=lambda *a, **k: None)

    # §F6 (2026-09-27): the allocator runs its host-wide census and bind probe only where the registry HOLDS a docker
    # socket; these tests are about that posture, so the socket "exists" (this file stands in for it)
    monkeypatch.setattr(cp, "DOCKER_SOCKET", __file__)
    mod = types.ModuleType("docker")
    mod.from_env = lambda: _Client()
    mod.errors = types.SimpleNamespace(ImageNotFound=type("ImageNotFound", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "docker", mod)
    return world


def _range(monkeypatch, lo, hi):
    monkeypatch.setattr(cp, "CLOUD_PORT_MIN", lo)
    monkeypatch.setattr(cp, "CLOUD_PORT_MAX", hi)
    monkeypatch.setenv("CLOUD_PORT_TEARDOWN_COOLDOWN_MINUTES", "120")


# the host as measured 2026-09-27 11:46Z: four operator stacks of three frames publishing 31100..31480
HOST = [_block("cloud-op-sbxalphaop-registry", 31100), _block("cloud-op-sbxbetaop-registry", 31200),
        _block("cloud-op-amsterdam-registry", 31300), _block("cloud-op-lisbon-registry", 31400)]


async def test_sbx_alpha_as_measured_is_refused_naming_why_each_block_was_taken(monkeypatch):
    _range(monkeypatch, 31100, 31499)
    _docker(monkeypatch, HOST)
    with pytest.raises(RuntimeError) as exc:
        await cp.allocate_port_block(_DB(live=[31100]))
    msg = str(exc.value)
    assert "31100..31499" in msg, msg
    assert "31100 this frame's operator" in msg, msg
    for base, name in ((31200, "sbxbetaop"), (31300, "amsterdam"), (31400, "lisbon")):
        assert f"{base} bound by cloud-op-{name}-registry" in msg, msg


async def test_a_moved_range_is_scanned_from_its_min(monkeypatch):
    """The fix for the sandbox: a range no other frame's covers. The pre-fix scan began at the highest live block + 100
    (31200) whatever MIN said, and handed out 31500, a block inside sbx-beta's and EU's ranges."""
    _range(monkeypatch, 32900, 33299)
    _docker(monkeypatch, HOST)
    assert await cp.allocate_port_block(_DB(live=[31100])) == 32900


async def test_a_block_freed_below_the_highest_live_one_is_handed_out_again(monkeypatch):
    _range(monkeypatch, 31300, 31699)
    _docker(monkeypatch, [_block("cloud-op-a-registry", 31300), _block("cloud-op-c-registry", 31500)])
    assert await cp.allocate_port_block(_DB(live=[31300, 31500])) == 31400


async def test_a_stopped_containers_configured_binding_counts(monkeypatch):
    """A stopped container publishes nothing, but starting it again would collide with the block handed out meanwhile."""
    _range(monkeypatch, 32900, 33299)
    _docker(monkeypatch, [_block("cloud-op-stopped-registry", 32900, running=False)])
    assert await cp.allocate_port_block(_DB(live=[])) == 33000


# ── controls: what did not change ────────────────────────────────────────────────────────────────────────────────────

async def test_control_this_frames_live_block_counts_even_when_nothing_binds_it(monkeypatch):
    _range(monkeypatch, 32900, 33299)
    _docker(monkeypatch, [])
    assert await cp.allocate_port_block(_DB(live=[32900])) == 33000


async def test_control_a_block_the_daemon_refuses_is_skipped_and_its_probe_removed(monkeypatch):
    _range(monkeypatch, 32900, 33299)
    world = _docker(monkeypatch, [], refuses={32900})
    assert await cp.allocate_port_block(_DB()) == 33000
    assert [p.base for p in world["probes"]] == [32900, 33000] and all(p.removed for p in world["probes"])


async def test_control_a_block_torn_down_within_the_cool_down_is_skipped(monkeypatch):
    _range(monkeypatch, 32900, 33299)
    _docker(monkeypatch, [])
    assert await cp.allocate_port_block(_DB(torn_recently=[32900])) == 33000
