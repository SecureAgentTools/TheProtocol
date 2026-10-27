"""§MONEY-R48 — the operator svid-writer SVID must be valid for BOTH sidecars it serves.

`services/cloud_provisioner.py` builds the DNS SAN list of the operator's svid-writer SPIRE entry.
Until 2026-09-04 it held `nginx-federation` and the operator's public hostname only. Every operator
dials its OWN TEG through `nginx-teg` (`TEG_API_BASE_URL=https://nginx-teg:8443`) with that same SVID,
so the handshake failed `CERTIFICATE_VERIFY_FAILED: Hostname mismatch` and every treasury / balance /
tokenomics call 500'd on a freshly provisioned operator. Production operators work only because their
entries were hand-repaired (op-berlin at revision 4). Found by agentvault2-07 driving the cloud-op MCP
flows on the sandbox operators; the two sandbox entries were repaired by hand (437→457 passed).

Structural (parsed, never grepped): the tuple the SAN loop iterates names both sidecars, in an
order-preserving dedupe (SPIRE enforces UNIQUE dns per entry — a repeat fails the whole command).
Control: RED against `git show HEAD~:…cloud_provisioner.py` (pre-fix) via R48_SRC.

⚠ RE-POINTED 2026-09-16 (§OPDIST): the loop moved to `core/operator_compose.py::svid_dns_sans`, because the
one-shot that provisions an operator on a runner-built frame must build the SAME list from a different container
and `services/__init__` is not importable there. This gate found the move itself — it refused the V0383 build
saying "found 0 — re-point this gate", which is exactly what a structural gate is for: the property survived the
move and the guard would otherwise have been left watching an empty room. It now looks in the new home and falls
back to the old one, so it reads either tree and the R48_SRC control still runs against the pre-fix source.
"""
from __future__ import annotations

import ast
import os
import pathlib

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["R48_SRC"]) if os.environ.get("R48_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())
def _module() -> pathlib.Path:
    """Wherever the SAN list lives: core since the move, the provisioner before it."""
    for rel in (("core", "operator_compose.py"), ("services", "cloud_provisioner.py")):
        candidate = SRC.joinpath(*rel)
        if candidate.is_file() and "nginx-federation" in candidate.read_text(encoding="utf-8"):
            return candidate
    return SRC / "services" / "cloud_provisioner.py"


MOD = _module()


def _san_tuples(tree):
    """Every `for _d in (<consts>...)` whose target feeds a `-dns` list — the SAN loop."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple):
            consts = [e.value for e in n.iter.elts if isinstance(e, ast.Constant)]
            if "nginx-federation" in consts:
                out.append((consts, n))
    return out


def test_the_svid_writer_san_list_names_both_sidecars():
    tree = ast.parse(MOD.read_text(encoding="utf-8"))
    loops = _san_tuples(tree)
    assert len(loops) == 1, f"expected exactly one SAN loop, found {len(loops)} — re-point this gate"
    consts, loop = loops[0]
    assert "nginx-teg" in consts, (
        "the operator svid-writer SVID must be valid for nginx-teg — every operator dials its TEG "
        "through that sidecar with this SVID (TEG_API_BASE_URL=https://nginx-teg:8443)"
    )
    assert consts.index("nginx-federation") < consts.index("nginx-teg"), "order-preserving: federation first"


def test_the_san_loop_dedupes_before_appending():
    """SPIRE enforces UNIQUE(entry, dns): a repeated -dns fails `entry update` and the SVID gets NO SAN
    (§pass78c left an operator without a hostname SAN for weeks that way)."""
    tree = ast.parse(MOD.read_text(encoding="utf-8"))
    consts, loop = _san_tuples(tree)[0]
    guards = [n for n in ast.walk(loop) if isinstance(n, ast.If)]
    # parsed, not grepped: `_d not in _dns_sans` is Compare(ops=[NotIn()]) — ast.dump spells it "NotIn"
    assert any(
        isinstance(c, ast.Compare) and any(isinstance(op, ast.NotIn) for op in c.ops)
        for g in guards for c in ast.walk(g.test)
    ), "the SAN loop must guard `_d not in _dns_sans` before appending"
