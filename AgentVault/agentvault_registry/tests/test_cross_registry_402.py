"""§AGORASIM-2 (2026-09-22): the TEG's 402 (the sender cannot pay) must reach the caller as 402, never as the generic
503 "Cross-registry transfer service unavailable" (the sandbox's live sim read every broke trader as an outage). Pinned on
the AST: the status chain that ends in that 503 carries an explicit 402 branch that raises HTTP_402_PAYMENT_REQUIRED."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "teg_integration.py"


def _chain_with(tree, needle):
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and needle in ast.unparse(node) and "response.status_code == 200" in ast.unparse(node.test):
            return node
    return None


def test_the_402_branch_precedes_the_generic_503():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    chain = _chain_with(tree, "Cross-registry transfer service unavailable")
    assert chain is not None, "the cross-registry status chain moved: re-point this test"
    tests, node = [], chain
    while isinstance(node, ast.If):
        tests.append((ast.unparse(node.test), ast.unparse(node.body[-1]) if node.body else ""))
        node = node.orelse[0] if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) else None
    codes = [t for t, _ in tests]
    assert "response.status_code == 402" in codes, codes
    body_402 = dict(tests)["response.status_code == 402"]
    assert "HTTP_402_PAYMENT_REQUIRED" in body_402, body_402
