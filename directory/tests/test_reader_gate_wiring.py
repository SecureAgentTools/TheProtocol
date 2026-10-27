"""§SOVKIT T4 — the app actually installs the reader gate (an AST read of `directory/app.py`).

The gate's own tests prove the rule; this proves the Directory runs it. Proven RED against the pre-gate app:
  git show HEAD~N:directory/directory/app.py > /tmp/app_pre.py
  DIRECTORY_APP_SRC=/tmp/app_pre.py python -m pytest tests/test_reader_gate_wiring.py   # must FAIL
"""
import ast
import os
from pathlib import Path

from directory import reader_gate

APP = Path(os.environ.get("DIRECTORY_APP_SRC") or Path(__file__).resolve().parents[1] / "directory" / "app.py")


def _tree():
    return ast.parse(APP.read_text())


def test_app_imports_the_gate():
    imports = [n for n in ast.walk(_tree()) if isinstance(n, ast.ImportFrom)]
    assert any(n.module == "reader_gate" and n.level == 1 and any(a.name == "ReaderGate" for a in n.names)
               for n in imports), "app.py does not import ReaderGate from .reader_gate"


def test_app_installs_the_gate_as_middleware():
    calls = [n for n in ast.walk(_tree()) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    installs = [n for n in calls if n.func.attr == "add_middleware" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "app" and n.args and isinstance(n.args[0], ast.Name)
                and n.args[0].id == "ReaderGate"]
    assert installs, "app.py never calls app.add_middleware(ReaderGate): /graphql would be open"


def test_app_announces_the_gate_at_import():
    module_calls = [n.value for n in _tree().body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
    names = {ast.unparse(c.func) for c in module_calls}
    assert "reader_gate.announce" in names or "announce" in names, \
        "app.py does not announce the gate at import: an empty allowlist would refuse silently"


def test_graphql_is_not_an_open_path():
    assert reader_gate.OPEN_PATHS == frozenset({"/health"}), reader_gate.OPEN_PATHS
    assert "/graphql" not in reader_gate.OPEN_PATHS
