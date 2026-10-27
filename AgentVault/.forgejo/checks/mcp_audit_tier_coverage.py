#!/usr/bin/env python3
"""§EVTYPES3 gate — every dispatched public MCP tool must sit in a tier set.

WHY. `mcp/audit.py::_tier_for()` walks _TIER_0/1/2/3_TOOLS and returns the string
"unknown" for anything it does not find. That value is written into
`security_audit_logs.tier` for every `tools/call`, so a tool missing from those
sets is not merely undocumented — its audit trail cannot say what authority it was
invoked under. CLAUDE.md PART 11 already names this as the third place in the
"adding a tool is 3-place wiring" rule; nothing enforced it.

Measured 2026-09-06: coverage is COMPLETE, 433 of 433. This gate exists to keep it
that way, not to record a gap.

⚠ It very nearly recorded a gap that was not there. My first census read only the
initial `_TIER_*_TOOLS = {...}` assignments and reported 16 tools missing — the whole
AGORA exchange family plus the OurChat message path, which reads like an alarming
finding about money rails. It was wrong: those sets are EXTENDED by `.update({...})`
calls at audit.py:769-793, which an ast.Assign-only walker cannot see. The same blind
spot in a different costume as the ast.AnnAssign one that made an earlier census
report zero. Hence `_collect` below handles Assign, AnnAssign AND `.update()/.extend()`,
and the plausibility check refuses to report green on an implausible parse.

PURE AST: imports nothing from the package. Resolves the same three shapes the
sanctioned catalog script does — string keys, `tools_gateway.<CONST>` attribute
keys, and AnnAssign targets (a plain ast.Assign-only walker reports ZERO, which is
a claim about the walker, not about the code).

Exit 0 clean · 1 violation · 2 the gate could not run.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
MCP = ROOT / "agentvault_registry/src/agentvault_registry/mcp"

# Known-missing as of 2026-09-06. Shrink only: the gate fails on a stale entry.
BASELINE: set[str] = set()   # EMPTY — coverage is complete (433/433) as of 2026-09-06.


def _gateway_consts() -> dict[str, str]:
    out: dict[str, str] = {}
    tree = ast.parse((MCP / "tools_gateway.py").read_text())
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def _keys(node, env, gw):
    out = []
    if isinstance(node, ast.Dict):
        seq = node.keys
    elif isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        seq = node.elts
    elif isinstance(node, ast.Name):
        return list(env.get(node.id, []))
    else:
        return out
    for k in seq:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            out.append(k.value)
        elif isinstance(k, ast.Attribute) and isinstance(k.value, ast.Name) \
                and k.value.id == "tools_gateway" and k.attr in gw:
            out.append(gw[k.attr])
    return out


def _collect(path: pathlib.Path, gw) -> dict[str, list[str]]:
    tree = ast.parse(path.read_text())
    env: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        tgts, val = [], None
        if isinstance(node, ast.Assign):
            tgts = [t.id for t in node.targets if isinstance(t, ast.Name)]
            val = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tgts, val = [node.target.id], node.value
        if tgts and val is not None:
            ks = _keys(val, env, gw)
            for t in tgts:
                env.setdefault(t, []).extend(ks)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr in ("update", "extend") \
                    and isinstance(f.value, ast.Name):
                for a in node.value.args:
                    env.setdefault(f.value.id, []).extend(_keys(a, env, gw))
    return env


def main() -> int:
    try:
        gw = _gateway_consts()
        disp = _collect(MCP / "server.py", gw)
        audit = _collect(MCP / "audit.py", gw)
    except FileNotFoundError as e:
        print(f"GATE ERROR: {e}", file=sys.stderr)
        return 2

    public = {t for t in disp.get("TOOL_DISPATCH", []) if t.startswith("theprotocol_")}
    tiered: set[str] = set()
    for name, vals in audit.items():
        if name.startswith("_TIER_"):
            tiered |= {v for v in vals if v.startswith("theprotocol_")}

    # A zero here is a claim about the parser, never about the code.
    if len(public) < 100 or len(tiered) < 100:
        print(f"GATE ERROR: parsed {len(public)} dispatch / {len(tiered)} tiered "
              f"tools — implausible, the parser is wrong. Refusing to report green.",
              file=sys.stderr)
        return 2

    missing = {t for t in public if t not in tiered}
    fresh = sorted(missing - BASELINE)
    stale = sorted(BASELINE - missing)

    print(f"§EVTYPES3 audit tier coverage: {len(public)} public tools, "
          f"{len(public) - len(missing)} tiered, {len(missing)} would record "
          f"tier='unknown' (baselined {len(BASELINE & missing)})")

    rc = 0
    if fresh:
        print(f"\nFAIL — {len(fresh)} tool(s) newly missing from every _TIER_*_TOOLS "
              f"set in mcp/audit.py:\n", file=sys.stderr)
        for t in fresh:
            print(f"  * {t}", file=sys.stderr)
        print("\nAdding a tool is 3-place wiring (dispatch + schema + audit tier set)."
              " Without the third, its audit row cannot say what authority was used.",
              file=sys.stderr)
        rc = 1
    if stale:
        print(f"\nFAIL — {len(stale)} baseline entr(ies) are now tiered; delete them "
              f"so the baseline keeps meaning something:\n", file=sys.stderr)
        for t in stale:
            print(f"  * {t}", file=sys.stderr)
        rc = 1
    if rc == 0:
        print("PASS — no newly untiered tool; the baseline is exactly the known gap.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
