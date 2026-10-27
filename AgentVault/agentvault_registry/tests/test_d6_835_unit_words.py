"""D6-835 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "sweep for avt again"): the registry's own
display texts named AVT on every frame. The org policy's presence threshold read "(AVT)" on EU's organisation settings
page, the reactors' worker card "Fires real synthetic AVT transfers", and the stuck-funds board's and the forensic
scanner's fiat findings "the AVT credit". EU's unit is ECU, ASIA's ACU; a fiat credit is the fiat genesis registry's
own unit. The setting keys stay (liability.presence_threshold_avt is a stored key, not a label).

RED control: against V0641's tree (e3a83ac3) the catalog label, the worker description and both finding texts say AVT.
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentvault_registry.background_tasks import forensic_scanner as FS
from agentvault_registry.routers import admin_health as AH
from agentvault_registry.services import org_policy as OP

_AVT = re.compile(r"\bAVT\b")
_LOG_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "warn"}


def _literals(path: pathlib.Path):
    """(line, text) of every string literal a caller can read: docstrings and log calls left out (comments are not
    in the AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            skip.add(id(body[0].value))
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in _LOG_CALLS:
                skip.update(id(sub) for sub in ast.walk(node))
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    skip.add(id(part))
                    out.append((node.lineno, part.value))
    return out


def _src(module) -> pathlib.Path:
    return pathlib.Path(module.__file__).with_suffix(".py")


def test_the_org_policy_catalog_names_no_unit_of_another_frame():
    texts = [(e["key"], e.get(f) or "") for e in OP.ORG_SETTING_CATALOG for f in ("label", "help")]
    assert texts, "the catalog is empty: nothing measured"
    named = [(k, t) for k, t in texts if _AVT.search(t)]
    assert not named, named
    presence = next(e for e in OP.ORG_SETTING_CATALOG if e["key"] == "liability.presence_threshold_avt")
    assert "frame's currency" in presence["label"], "the label says in which unit the threshold counts"


def test_the_worker_roster_and_the_stuck_funds_board_name_no_avt():
    found = [(line, text) for line, text in _literals(_src(AH)) if _AVT.search(text)]
    assert not found, f"admin_health names AVT to a reader: {found}"
    # control: the walk reads the roster, so a missing description would not pass by reading nothing
    assert any("synthetic transfers across paths" in text for _, text in _literals(_src(AH)))


def test_the_forensic_scanners_findings_name_no_avt():
    found = [(line, text) for line, text in _literals(_src(FS)) if _AVT.search(text)]
    assert not found, f"forensic_scanner names AVT to a reader: {found}"
    assert any("fiat_credit_retry" in text for _, text in _literals(_src(FS))), "the fiat finding is read"


# ── D6-835, the second pass (2026-10-25, after agentvault2-66's find in main.py's showcase_call): the registry's own
# messages. The activity feed's lines, four notification titles, three dispute texts, the MCP stake answer, the fee
# estimate's unit, the showcase note, the public API's amount descriptions, the admin MCP tool descriptions and four
# metrics' help named AVT on every frame. RED control: against cfb9109a's tree each of these fails.
from agentvault_registry import activity_bridge as AB  # noqa: E402
from agentvault_registry.routers import teg_transactions as TT  # noqa: E402

_ROOT = pathlib.Path(AB.__file__).parent
_MESSAGE_MODULES = (
    "activity_bridge.py", "background_tasks/reactor_push_notify.py", "background_tasks/reactor_agent_slashed.py",
    "background_tasks/reactor_dispute_filed.py", "background_tasks/reactor_funding_request_created.py",
    "crud/crud_disputes.py", "mcp/tools_agent.py", "mcp/tools_admin.py", "schemas_enhanced.py",
    "routers/token_bridge.py", "routers/funding_requests.py", "routers/enforcement_agent.py",
    "background_tasks/supply_auditor.py", "background_tasks/canary_rebalancer.py",
    "background_tasks/balance_reconciliation_guard.py",
)


def test_the_message_modules_name_no_avt():
    found = {m: [(ln, tx[:60]) for ln, tx in _literals(_ROOT / m) if _AVT.search(tx)] for m in _MESSAGE_MODULES}
    found = {m: f for m, f in found.items() if f}
    assert not found, found


def test_the_activity_lines_name_the_frames_unit_or_the_events(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    tpl = AB.ACTIVITY_MAP["TokensTransferred"]["description"]
    assert AB._format_template(tpl, "did:theprotocol:abc", {"amount": "10"}) == "Transfer of 10 ECU completed between agents."
    assert "ACU" in AB._format_template(tpl, "did:theprotocol:abc", {"amount": "10", "currency": "ACU"})
    staked = AB._format_template(AB.ACTIVITY_MAP["TokensStaked"]["description"], "did:theprotocol:abc", {"amount": "5"})
    assert staked.endswith("locked 5 ECU."), staked
    words = " ".join(f"{v['title']} {v['description']}" for v in AB.ACTIVITY_MAP.values() if v)
    assert not _AVT.search(words) and "Staked Tokens" not in words, "the feed's titles in the console's words"


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()   # its own loop: asyncio.run() would leave the next test file without one
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_the_fee_estimate_answers_in_the_frames_unit(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ACU")
    out = _run(getattr(TT.get_transaction_fees, "__wrapped__", TT.get_transaction_fees)(operation="transfer"))
    assert out["fee_currency"] == "ACU", out


def test_the_showcase_note_names_what_the_call_charged():
    src = (_ROOT / "main.py").read_text(encoding="utf-8")
    assert '"showcase_note": f"This call used {charge_amount} {charge_ccy} on TheProtocol.' in src
    assert "AVT on TheProtocol" not in src
