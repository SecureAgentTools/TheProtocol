"""§AGORAWORDS Phase 5 (2026-09-22): every caller in the registry uses /api/v1/agora. The old prefix may appear only where
it DEFINES the legacy surface (the hidden mount, the hidden alias routes, the alias counter) or names it as the fallback
(core/agora_paths.LEGACY_PREFIX); in docstrings and comments it is prose. A new caller written with the old prefix fails
here, before a later release drops the old paths and breaks it silently."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
ALLOWED = {
    "main.py",                      # app.include_router(exchange_router, prefix="/api/v1/exchange", include_in_schema=False)
    "core/agora_paths.py",          # LEGACY_PREFIX: the fallback's second ask
    "mcp/tool_aliases.py",          # the legacy-name counter's own description
    "routers/stock_card.py",        # the hidden /api/v1/exchange/stock-card alias route
    "routers/solvency_card.py",     # the hidden /api/v1/exchange/solvency-card alias route
}


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                out.add(id(first.value))
    return out


def test_no_caller_builds_the_old_prefix():
    hits = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        if rel in ALLOWED or rel.startswith(("api_tests/", "static/")):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "/api/v1/exchange" in node.value and id(node) not in docs:
                hits.append(f"{rel}:{node.lineno}")
    assert not hits, "callers still build /api/v1/exchange (use /api/v1/agora or core.agora_paths): " + ", ".join(hits)
