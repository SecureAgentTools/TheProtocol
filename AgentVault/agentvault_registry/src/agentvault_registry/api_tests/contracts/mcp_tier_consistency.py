"""MCP tier-set consistency static analyser (Phase 5 sprint 5.4).

Goal: catch the BUG class where a wrapper's runtime auth requirement
disagrees with the dispatcher's TIER2_TOOLS / TIER3_TOOLS set in
`mcp/server.py`. If a wrapper calls `require_agent_auth(auth)` (directly
or via `_agent_get/_agent_post/_agent_delete`) but the tool name is NOT
in TIER2_TOOLS, the dispatcher won't pop `agent_jwt` from arguments →
the tool gets dev_jwt outer + no inline override → 401 surprise.

This is a STATIC analysis pass — no API calls, runs in milliseconds.

Returns a list of ContractOutcome-shape dicts that the sweep can fold
into its results. Empty list = clean.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# Helper functions in tools_agent.py / tools_developer.py that imply
# their callers need the corresponding auth tier.
_AGENT_HELPERS = {"_agent_get", "_agent_post", "_agent_delete"}
_DEV_HELPERS = {"_dev_request"}
_DIRECT_AGENT_AUTH = "require_agent_auth"
_DIRECT_DEV_AUTH = "require_developer_auth"


def _scan_tier_sets(server_py_path: Path) -> Tuple[Set[str], Set[str], Dict[str, str]]:
    """Parse TIER2_TOOLS / TIER3_TOOLS sets + TOOL_DISPATCH wrapper-name
    mapping from server.py via AST.

    Returns (tier2_names, tier3_names, dispatch_name_to_wrapper_name).
    """
    src = server_py_path.read_text()
    tree = ast.parse(src)

    tier2: Set[str] = set()
    tier3: Set[str] = set()
    dispatch: Dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id in ("TIER2_TOOLS", "TIER3_TOOLS"):
                    bucket = tier2 if target.id == "TIER2_TOOLS" else tier3
                    if isinstance(node.value, ast.Set):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                bucket.add(elt.value)
                elif target.id == "TOOL_DISPATCH":
                    if isinstance(node.value, ast.Dict):
                        for k, v in zip(node.value.keys, node.value.values):
                            if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                                    and isinstance(v, ast.Name)):
                                dispatch[k.value] = v.id

    return tier2, tier3, dispatch


def _scan_wrapper_auth(tools_py_path: Path) -> Dict[str, str]:
    """Walk one tools_*.py file. For each top-level async function, classify
    its effective auth tier by inspecting calls in its body:
      - Calls `_agent_get` / `_agent_post` / `_agent_delete` → "agent"
      - Calls `require_agent_auth(auth)` directly → "agent"
      - Calls `_dev_request(...)` → "developer"
      - Calls `require_developer_auth(auth)` directly → "developer"
      - Otherwise → "" (no explicit auth claim; tier 1 or 0)

    Returns {wrapper_function_name: "agent"|"developer"|""}.
    """
    src = tools_py_path.read_text()
    tree = ast.parse(src)

    out: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        verdict = ""
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn_name = None
                if isinstance(sub.func, ast.Name):
                    fn_name = sub.func.id
                elif isinstance(sub.func, ast.Attribute):
                    fn_name = sub.func.attr
                if fn_name in _AGENT_HELPERS or fn_name == _DIRECT_AGENT_AUTH:
                    verdict = "agent"
                    break
                if fn_name in _DEV_HELPERS or fn_name == _DIRECT_DEV_AUTH:
                    verdict = "developer"
                    break
        out[node.name] = verdict
    return out


def run_tier_consistency_check(repo_root: Optional[Path] = None) -> List[Dict[str, str]]:
    """Run the static check. Returns list of issue dicts:
        {tool_name, wrapper_fn, actual_tier, expected_tier, issue}.
    Empty list → no drift.
    """
    if repo_root is None:
        # We're inside the registry container, source lives at
        # /app/agentvault_registry/...
        repo_root = Path(__file__).resolve().parents[2]
        # /app/agentvault_registry/api_tests/contracts/mcp_tier_consistency.py
        # → .parents[0]=contracts, [1]=api_tests, [2]=agentvault_registry

    server_py = repo_root / "mcp" / "server.py"
    if not server_py.exists():
        # Try via parent search
        for cand in (
            Path(__file__).resolve().parents[1] / "mcp" / "server.py",
            Path(__file__).resolve().parents[2] / "mcp" / "server.py",
            Path(__file__).resolve().parents[3] / "mcp" / "server.py",
        ):
            if cand.exists():
                server_py = cand
                break
        else:
            return [{
                "tool_name": "__meta__",
                "wrapper_fn": "",
                "actual_tier": "",
                "expected_tier": "",
                "issue": f"tier-consistency: server.py not found at {server_py!s}",
            }]

    mcp_root = server_py.parent
    tier2, tier3, dispatch = _scan_tier_sets(server_py)

    # Build a wrapper_name → effective_auth_tier map by scanning all
    # tools_*.py modules.
    wrapper_auth: Dict[str, str] = {}
    for tools_py in mcp_root.glob("tools_*.py"):
        wrapper_auth.update(_scan_wrapper_auth(tools_py))

    issues: List[Dict[str, str]] = []

    for tool_name, wrapper_fn in dispatch.items():
        eff = wrapper_auth.get(wrapper_fn, "")
        in_tier2 = tool_name in tier2
        in_tier3 = tool_name in tier3

        if eff == "agent":
            if not in_tier2:
                # Wrapper requires agent auth but tool is NOT in TIER2_TOOLS
                # → dispatcher won't pop `agent_jwt` from arguments.
                issues.append({
                    "tool_name": tool_name,
                    "wrapper_fn": wrapper_fn,
                    "actual_tier": "agent (wrapper body)",
                    "expected_tier": "TIER2_TOOLS",
                    "issue": (
                        f"BUG-FIND: wrapper {wrapper_fn!r} calls _agent_*/require_agent_auth "
                        f"but tool {tool_name!r} is NOT in TIER2_TOOLS — dispatcher "
                        f"will not pop inline agent_jwt"
                    ),
                })
            if in_tier3:
                issues.append({
                    "tool_name": tool_name,
                    "wrapper_fn": wrapper_fn,
                    "actual_tier": "agent (wrapper body)",
                    "expected_tier": "TIER2_TOOLS",
                    "issue": (
                        f"BUG-FIND: wrapper {wrapper_fn!r} calls _agent_*/require_agent_auth "
                        f"but tool {tool_name!r} is in TIER3_TOOLS (should be TIER2_TOOLS only)"
                    ),
                })
        elif eff == "developer":
            if not in_tier3:
                issues.append({
                    "tool_name": tool_name,
                    "wrapper_fn": wrapper_fn,
                    "actual_tier": "developer (wrapper body)",
                    "expected_tier": "TIER3_TOOLS",
                    "issue": (
                        f"BUG-FIND: wrapper {wrapper_fn!r} calls _dev_request/require_developer_auth "
                        f"but tool {tool_name!r} is NOT in TIER3_TOOLS"
                    ),
                })
            if in_tier2:
                issues.append({
                    "tool_name": tool_name,
                    "wrapper_fn": wrapper_fn,
                    "actual_tier": "developer (wrapper body)",
                    "expected_tier": "TIER3_TOOLS",
                    "issue": (
                        f"BUG-FIND: wrapper {wrapper_fn!r} calls _dev_request/require_developer_auth "
                        f"but tool {tool_name!r} is in TIER2_TOOLS (should be TIER3_TOOLS only)"
                    ),
                })
        # eff == "" → unclassified; tolerate (probably tier 0/1 or helper)

    return issues
