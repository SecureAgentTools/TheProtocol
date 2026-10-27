"""§MONEY-R49 — the operator provisioner's `spire-server entry update` must re-pass the entry's
existing `-federatesWith` domains, or it silently un-federates the operator.

`entry update` is a REPLACE. Until 2026-09-04 the provisioner passed the id, the SPIFFE id, the
parent, the selector, the TTL and the `-dns` list — and nothing else — so a re-run against an
operator that had been federated since (both sandbox operators were, by hand) wiped its
federation. Found by agentvault2-07 (B0b), approved by the Commander ("r49 also approved").

Two properties: the parser reads the real `entry show` shape (a production entry's text, names
only), and the update command appends `-federatesWith` for every domain the parser returns
(parsed, never grepped). Control: RED against the pre-fix file via R49_SRC.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["R49_SRC"]) if os.environ.get("R49_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())
MOD = SRC / "services" / "cloud_provisioner.py"

# The shape spire-server 1.10 prints for a federated, hand-repaired production entry (op-berlin,
# revision 4, 2026-09-04) — the value is the BARE trust domain.
_ENTRY_SHOW = """Found 1 entry
Entry ID         : 5c438528-52b5-4fe5-ba98-d51ce3d6fc5a
SPIFFE ID        : spiffe://agentvault.com/operator/op-berlin/svid-writer
Parent ID        : spiffe://agentvault.com/spire/agent/x509pop/abc
Revision         : 4
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:svid-writer-operator
FederatesWith    : frame-b.theprotocol.cloud
FederatesWith    : spiffe://frame-c.theprotocol.cloud
FederatesWith    : frame-b.theprotocol.cloud
DNS name         : nginx-federation
DNS name         : op-berlin.op.theprotocol.cloud
DNS name         : nginx-teg
"""


def _load_parser():
    """Import only the pure helper, by executing its source — the module itself pulls in the
    provisioning stack. If the helper is absent (pre-fix tree) this returns None."""
    tree = ast.parse(MOD.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "_federates_with_from_entry_show"), None)
    if fn is None:
        return None
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(MOD), "exec"), ns)
    return ns["_federates_with_from_entry_show"]


def test_parser_reads_the_real_entry_show_shape():
    parse = _load_parser()
    assert parse is not None, "the parser _federates_with_from_entry_show is missing (pre-R49 tree)"
    assert parse(_ENTRY_SHOW) == ["frame-b.theprotocol.cloud", "frame-c.theprotocol.cloud"], (
        "order-preserving, deduplicated, spiffe:// stripped")
    assert parse("") == [] and parse("Entry ID : x\nDNS name : nginx-teg\n") == []


def test_the_update_command_re_passes_every_federation():
    tree = ast.parse(MOD.read_text(encoding="utf-8"))
    # the loop that appends "-federatesWith" to the update command, fed by the parser
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and any(isinstance(c, ast.Constant) and c.value == "-federatesWith"
                     for c in ast.walk(n))]
    assert loops, "entry update never passes -federatesWith — a re-run wipes the operator's federation"
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and getattr(c.func, "id", None) == "_federates_with_from_entry_show"]
    assert calls, "the domains must come from the entry show output, never be assumed"
    # and the -dns loop still exists right beside it (R48)
    dns_loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
                 and any(isinstance(c, ast.Constant) and c.value == "-dns" for c in ast.walk(n))]
    assert dns_loops


@pytest.mark.parametrize("bad", ["FederatesWith: \n", "federateswith : x\n"])
def test_parser_ignores_malformed_lines(bad):
    parse = _load_parser()
    assert parse is not None
    assert parse(bad) == []
