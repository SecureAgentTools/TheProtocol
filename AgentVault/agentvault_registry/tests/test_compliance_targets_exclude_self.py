"""§MCPTEST30 (V0564): the compliance page reads the Command Center's targets for its peers, and since V0562 that list
opens with this registry itself (target["self"]). Measured after V0563, on the sandbox and on production: every
registry's /admin/compliance listed itself as a target that was never admitted (sbx-alpha: 6 targets where it federates
with 5), and the quarantine preview read its own policy as a peer's. The router reads the targets through one helper,
which leaves this registry out; the Command Center keeps it (it is that page's first target)."""
import ast
import inspect

import pytest

from agentvault_registry import models
from agentvault_registry.routers import consul_admin as ca

SELF = {"operator_id": "sandbox-alpha", "display_name": "Sandbox Alpha", "frame": "sandbox-a", "role": "frame",
        "cloud_url": "https://sandbox-a.example", "containers": {}, "self": True}
OP = {"operator_id": "sbxalphaop", "display_name": "sbxalphaop", "frame": "sandbox-a", "role": "operator",
      "cloud_url": "https://sbxalphaop.example", "containers": {}}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Answers the two SELECTs get_overview issues, in order: peers, then compliance rows."""
    def __init__(self, peers, compliances):
        self._answers = [peers, compliances]

    async def execute(self, _stmt):
        return _Result(self._answers.pop(0))


@pytest.mark.asyncio
async def test_the_peer_targets_leave_this_registry_out(monkeypatch):
    async def _targets(_db):
        return [SELF, OP]
    monkeypatch.setattr(ca, "list_diag_targets", _targets)
    assert await ca._peer_targets(None) == [OP]


@pytest.mark.asyncio
async def test_the_overview_lists_its_peers_and_not_itself(monkeypatch):
    peer = models.PeerRegistry(name="sbxalphaop", base_url="https://sbxalphaop.example", status="ACTIVE",
                               peer_type="cloud_operator", trust_domain="sandbox-a.example")
    peer.id = 1

    class _State:
        compliance_enforcement_mode = "dry_run"

    async def _targets(_db):
        return [SELF, OP]

    async def _state(_db):
        return _State()

    async def _frame(_t):
        return "sandbox-a"

    async def _no_reach(_db, include_ok=True):
        return None
    monkeypatch.setattr(ca, "list_diag_targets", _targets)
    monkeypatch.setattr(ca, "_get_singleton_state", _state)
    monkeypatch.setattr(ca, "_resolve_frame", _frame)
    from agentvault_registry.services import federation_reachability
    monkeypatch.setattr(federation_reachability, "build_report", _no_reach)
    ov = await ca.get_overview(db=_FakeDB([peer], []))
    assert [r.operator_id for r in ov.peers] == ["sbxalphaop"] and ov.peers_total == 1
    assert ov.peers[0].peer_registry_id == 1


def test_the_router_reads_the_targets_only_through_the_helper():
    """Four routes read the targets (the overview, the detail, the quarantine preview, the trust bundle matrix): a fifth
    that called the list directly would bring this registry back as its own peer."""
    tree = ast.parse(inspect.getsource(ca))
    callers = set()
    for fn in [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "list_diag_targets":
                callers.add(fn.name)
    assert callers == {"_peer_targets"}
    readers = {fn.name for fn in tree.body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
               for node in ast.walk(fn) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_peer_targets"}
    assert readers == {"get_overview", "get_peer_detail_by_operator", "preview_quarantine", "trust_bundle_matrix"}
