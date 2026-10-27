"""§F6 group 4 (2026-09-27, his decision "retire frame a actions" and his words "i approve to finish f6 implementation on
sandbox"): the Command Center's Frame-A-era actions are retired, not ported, because each reached into Frame A or
Frame B from whichever frame ran it:

- `spire-bundle-refresh` ran `bundle set` on agentvault-spire-server and frame-b-spire-server by constant and restarted
  agentvault-cert-writer-a;
- `identity-network-reconnect` joined the target's TEG and sidecar to agentvault_identity_network (Frame A's), and
  `teg-restart` made the same join after every restart.

What is left acts on THIS frame's own operators only: teg-restart through the operator lifecycle's one rule
(restart_cloud_service: the runner when OPERATOR_LIFECYCLE_VIA=runner), nginx-reload by exec with its probe failure
named as such. The identity-network check reads the frame's own IDENTITY_NETWORK, and the four checks that offered the
retired actions name the rail instead (a manual-investigate hint, which the Command Center shows without a button).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agentvault_registry.services import cloud_provisioner as cp
from agentvault_registry.services.diagnostics import actions
from agentvault_registry.services.diagnostics.checks import identity_network

DIAG = pathlib.Path(actions.__file__).parent
RETIRED = {"identity-network-reconnect", "spire-bundle-refresh"}
FRAME_A_B_CONSTANTS = ("agentvault-spire-server", "frame-b-spire-server", "agentvault-cert-writer-a",
                       "agentvault_identity_network")


def _suggested_action_ids(source: str) -> list:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RemediationHint":
            for kw in node.keywords:
                if kw.arg == "action_id" and isinstance(kw.value, ast.Constant):
                    out.append(kw.value.value)
    return out


def _code_constants(source: str) -> list:
    """Every string constant that is not a docstring."""
    tree = ast.parse(source)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs]


def test_the_frame_a_actions_are_gone_and_the_operator_actions_stay():
    assert actions.known_action_ids() == ["nginx-reload", "teg-restart"]
    for a in RETIRED:
        assert actions.get_action(a) is None, a


def test_no_check_suggests_an_action_that_does_not_exist():
    registered = set(actions.known_action_ids()) | {"manual-investigate"}
    found = {}
    for p in sorted((DIAG / "checks").glob("*.py")):
        bad = [a for a in _suggested_action_ids(p.read_text(encoding="utf-8")) if a not in registered]
        if bad:
            found[p.name] = bad
    assert not found, found


def test_control_a_suggestion_of_a_retired_action_is_caught():
    planted = 'x = RemediationHint(action_id="spire-bundle-refresh", description="d")'
    assert _suggested_action_ids(planted) == ["spire-bundle-refresh"]
    assert "spire-bundle-refresh" not in set(actions.known_action_ids()) | {"manual-investigate"}


def test_the_actions_name_no_frame_a_or_b_container_in_code():
    consts = _code_constants(pathlib.Path(actions.__file__).read_text(encoding="utf-8"))
    hits = [c for c in consts for name in FRAME_A_B_CONSTANTS if name in c]
    assert hits == [], hits


def test_control_a_planted_frame_a_constant_is_caught_and_prose_is_not():
    assert any("frame-b-spire-server" in c for c in _code_constants('b = "frame-b-spire-server"'))
    assert _code_constants('"""retired: frame-b-spire-server"""') == []


class _NoProbe:
    """A probe that must not be touched: the lifecycle rule does the work, never docker from the registry."""

    def __getattr__(self, name):
        raise AssertionError(f"the probe was used ({name})")


def _operator(slug="sbxbetaop"):
    return {"operator_id": f"op-{slug}", "role": "operator",
            "containers": {"teg": f"cloud-op-{slug}-teg", "nginx_federation": f"cloud-op-{slug}-nginx-federation"}}


def _mainframe():
    return {"operator_id": "frame-b", "role": "mainframe",
            "containers": {"teg": "frame-b-teg", "nginx_federation": "frame-b-nginx-federation"}}


@pytest.fixture
def restarts(monkeypatch):
    calls = []

    async def fake_restart(application, service):
        calls.append((application.name, service))
        return {"service": service, "restarted": True, "output_tail": "Container cloud-op-x-teg  Started"}
    monkeypatch.setattr(cp, "restart_cloud_service", fake_restart)
    monkeypatch.setenv("OPERATOR_LIFECYCLE_VIA", "runner")
    return calls


async def test_teg_restart_goes_through_the_operator_lifecycle_and_joins_no_network(restarts):
    r = await actions.teg_restart(_operator(), _NoProbe(), dry_run=False, actor="admin")
    assert r.status == "ok" and "via runner" in r.summary
    assert restarts == [("sbxbetaop", "teg-layer")]


async def test_teg_restart_dry_run_restarts_nothing(restarts):
    r = await actions.teg_restart(_operator(), _NoProbe(), dry_run=True, actor="admin")
    assert r.status == "ok" and r.dry_run and restarts == []


async def test_control_a_frames_own_teg_is_not_restarted_from_a_command_center(restarts):
    r = await actions.teg_restart(_mainframe(), _NoProbe(), dry_run=False, actor="admin")
    assert r.status == "skipped" and restarts == []


async def test_a_failed_restart_says_the_lifecycles_sentence(monkeypatch):
    async def refused(application, service):
        raise RuntimeError("frame 'sbx-beta' is not the calling frame")
    monkeypatch.setattr(cp, "restart_cloud_service", refused)
    r = await actions.teg_restart(_operator(), _NoProbe(), dry_run=False, actor="admin")
    assert r.status == "fail" and "not the calling frame" in r.summary


class _ExecProbe:
    def __init__(self, rc, out=""):
        self.rc, self.out, self.calls = rc, out, []

    async def exec_in(self, container, cmd, timeout=8):
        self.calls.append((container, cmd))
        return self.rc, self.out


async def test_nginx_reload_names_a_probe_failure_as_the_probes():
    probe = _ExecProbe(127, "exec failed: Error while fetching server API version")
    r = await actions.nginx_reload(_operator(), probe, dry_run=False, actor="admin")
    assert r.status == "fail" and "could not reach the sidecar" in r.summary and "rejected" not in r.summary
    assert len(probe.calls) == 1, "nothing is reloaded after a probe failure"


async def test_control_nginx_reload_still_refuses_a_config_nginx_rejects():
    probe = _ExecProbe(1, "nginx: [emerg] unknown directive")
    r = await actions.nginx_reload(_operator(), probe, dry_run=False, actor="admin")
    assert r.status == "fail" and "nginx -t rejected" in r.summary


async def test_control_nginx_reload_skips_a_frames_own_sidecar():
    probe = _ExecProbe(0)
    r = await actions.nginx_reload(_mainframe(), probe, dry_run=False, actor="admin")
    assert r.status == "skipped" and probe.calls == []


class _NetProbe:
    def __init__(self, attached):
        self.attached, self.asked = attached, []

    async def network_inspect(self, name):
        self.asked.append(name)
        return {"Containers": {str(i): {"Name": n} for i, n in enumerate(self.attached)}}


async def test_the_identity_network_check_asks_this_frames_own_network(monkeypatch):
    monkeypatch.setenv("IDENTITY_NETWORK", "sbx_beta_identity_network")
    probe = _NetProbe(["cloud-op-sbxbetaop-teg"])                     # the sidecar is missing
    r = await identity_network.run(_operator(), probe)
    assert probe.asked == ["sbx_beta_identity_network"]
    assert r.status == "fail" and r.details["network"] == "sbx_beta_identity_network"
    assert r.remediation.action_id == "manual-investigate"             # guidance, no button
    assert "retired" in r.remediation.description


async def test_control_without_the_variable_it_asks_the_provisioners_default(monkeypatch):
    monkeypatch.delenv("IDENTITY_NETWORK", raising=False)
    probe = _NetProbe(["cloud-op-sbxbetaop-teg", "cloud-op-sbxbetaop-nginx-federation"])
    r = await identity_network.run(_operator(), probe)
    assert probe.asked == [identity_network.NETWORK_NAME] == ["agentvault_identity_network"]
    # the same default the operator provisioner renders into an operator's compose
    assert 'os.getenv("IDENTITY_NETWORK", "agentvault_identity_network")' in pathlib.Path(cp.__file__).read_text()
    assert r.status == "ok"
