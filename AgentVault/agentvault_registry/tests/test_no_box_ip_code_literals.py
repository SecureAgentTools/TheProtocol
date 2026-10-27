"""§BATCH3 item 1 — the production box's IP is a deployment fact, never a code literal.

The scan is AST-based on purpose: comments are not in the tree, a module/class/function
docstring is skipped, and every other string constant (plain, f-string parts, defaults,
dict keys) counts. Before this batch four code sites carried it (a canary rebalancer dial
base ×2, an operator health probe, an IRONHAND demo default) and two literal tables
(the canary mTLS map, the sandbox canary bootstrap). All six now read a carrier:
CANARY_HOME_HOST, CLOUD_OP_HEALTH_HOST_IP, IRONHAND_ALPHA_URL, CANARY_MTLS_MAP_FILE
(+ config/canary_mtls_map.mainnet-2026.json), SANDBOX_CANARY_SPECS_FILE.

Control: the same scanner must FIND the literal in a synthetic module, or the zero is a
claim about the scanner.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
BOX_IP = "168." + "119.0.8"   # split so this test file is not itself a hit for a text grep


def _code_string_hits(tree: ast.AST) -> int:
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if BOX_IP in node.value:
                hits += 1
    return hits


def scan(root: pathlib.Path):
    out = {}
    for path in sorted(root.rglob("*.py")):
        if "/tests/" in str(path) or "/node_modules/" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        n = _code_string_hits(tree)
        if n:
            out[str(path.relative_to(root))] = n
    return out


def test_no_box_ip_in_registry_code():
    hits = scan(SRC)
    assert hits == {}, f"box IP as a CODE literal in: {hits}"


def test_control_scanner_sees_a_code_literal_but_not_a_comment_or_docstring():
    good = ast.parse(f'"""doc {BOX_IP} in a docstring"""\n# comment {BOX_IP}\nX = 1\n')
    assert _code_string_hits(good) == 0
    bad = ast.parse(f'BASE = f"http://{BOX_IP}:{{port}}"\nOTHER = {{"k": "https://{BOX_IP}:8443"}}\n')
    assert _code_string_hits(bad) == 2
