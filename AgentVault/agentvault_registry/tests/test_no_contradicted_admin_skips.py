"""A TOOL MUST NOT BE DECLARED "DO NOT CALL" AND ALSO SIT IN A CALL BATCH.

§MCPADMSKIP-3 2026-09-07. `MCP_CONTRACTS[t].skip_reason` says "do not call this
tool". `mcp_admin_lifecycles.py` names tools in two very different ways: a
`_LIFECYCLE_NEVER_INVOKE` denylist, and batches that DO call them. A tool in both
the skip list and a call batch is two declarations disagreeing, and the winner is
whichever consumer happens to run — silently.

That is how `getAdminFundingPending` was called on every run while carrying a
"skip": the lifecycle branch is consulted before any skip check, so its membership
in `lifecycle_admin_dashboard_reads` beat its own contract without anything saying
so. (Resolved the other way in the same commit: the coverage is real and the route
is read-only, so the warning became a `notes=` and the switch nobody honoured went
away.)

§FANCLAIM 2026-09-07 SHARPENED WHAT THIS GATE IS ABOUT. `skip_reason` means DO NOT
CALL. A tool that IS deliberately called against a nonexistent target — so only its
refusal is measured — says that with `success_path_unmeasured` instead, which this
gate ignores by design: that field downgrades the ROW, it never suppresses a call,
so there is no contradiction for it to find. Writing that sentence as a
`skip_reason` would trip this gate, which is the gate working: the two sentences
had been sharing one field and the seven §FANCLAIM contracts are what separated
them.

⚠ THE CENSUS THIS GATE RUNS IS THE ONE THE FIRST VERSION GOT WRONG. Searching the
lifecycle file for tool names finds 16 — but 22 of those names are the denylist,
which means "never call", the exact opposite. Parsing `_LIFECYCLE_NEVER_INVOKE`
out of the AST and subtracting it gives 2. A census answers the question it asks.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS  # noqa: E402

_LIFECYCLES = (_ROOT / "agentvault_registry" / "api_tests" / "contracts" /
               "mcp_admin_lifecycles.py")

# ONE named exception, with the measurement that removes it. Never widen this
# without the same: a name, the reason, and what closes it.
# EMPTY, and that is the point. The one entry this list ever held
# (`getCloudOperators`) is gone because its contradiction was RESOLVED on
# 2026-09-07 — measured on both node classes, the frame answers 200 with
# `operators` and the skip was inherited from the retired sandbox-A. The
# second leg below FAILED the moment the contract changed, which is how the
# exception got removed instead of quietly protecting nothing.
#
# Adding an entry requires all three: the name, the reason, and the
# measurement that closes it.
_TOLERATED: dict[str, str] = {}


def _never_invoke_names(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_LIFECYCLE_NEVER_INVOKE" for t in node.targets):
            for el in ast.walk(node.value):
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    if el.value.startswith("theprotocol_"):
                        out.add(el.value)
    return out


def test_no_tool_is_both_skipped_and_called() -> None:
    src = _LIFECYCLES.read_text()
    never = _never_invoke_names(ast.parse(src))
    assert never, ("_LIFECYCLE_NEVER_INVOKE parsed as empty — the denylist moved or "
                   "was renamed, and without it this gate would report every "
                   "deliberately-never-called tool as a contradiction")
    named = set(re.findall(r'"(theprotocol_[A-Za-z0-9_]+)"', src))
    called = named - never
    contradicted = {
        t: MCP_CONTRACTS[t].skip_reason
        for t in sorted(called)
        if t in MCP_CONTRACTS and getattr(MCP_CONTRACTS[t], "skip_reason", None)
        and t not in _TOLERATED
    }
    assert not contradicted, (
        "these tools declare a skip_reason AND sit in a lifecycle call batch, so the "
        "skip binds nothing and the disagreement is invisible at runtime — resolve it "
        "in one direction (drop the skip and keep the coverage, or remove the tool "
        "from the batch): " + repr(contradicted))


def test_the_tolerated_list_is_still_real() -> None:
    """A tolerated exception that no longer applies is a stale excuse.

    If the name leaves either side of the contradiction, this fails so the entry
    gets removed rather than quietly protecting nothing.
    """
    src = _LIFECYCLES.read_text()
    never = _never_invoke_names(ast.parse(src))
    called = set(re.findall(r'"(theprotocol_[A-Za-z0-9_]+)"', src)) - never
    for name in _TOLERATED:
        assert name in called, f"{name} is no longer in a lifecycle call batch — drop the exception"
        c = MCP_CONTRACTS.get(name)
        assert c is not None and getattr(c, "skip_reason", None), (
            f"{name} no longer declares a skip_reason — the contradiction is gone, "
            f"so drop the exception")
