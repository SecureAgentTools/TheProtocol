"""§TESTBED (2026-09-19): the sandbox seeder never writes a password into the log, neither a generated one nor the
first seed's env-supplied ones (a kit sandbox's `docker logs` was a password listing)."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "test_seed.py"


def _logged_names(tree):
    """Every Name/attribute/subscript text inside a logger.<level>(...) call's arguments."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
                and n.func.value.id == "logger":
            out.append(ast.unparse(n))
    return out


def test_no_log_call_carries_a_password():
    calls = _logged_names(ast.parse(SRC.read_text()))
    assert calls, "the seeder logs something; a census over zero calls proves nothing"
    bad = [c for c in calls if "generated" in c.split("(", 1)[1] and "{generated}" in c or "'password'" in c or '"password"' in c]
    assert not bad, bad


def test_control_the_old_lines_would_be_caught():
    old = 'logger.info(f"  Admin:     {TEST_ADMIN[\'email\']} / {TEST_ADMIN[\'password\']}")'
    assert any("'password'" in c for c in _logged_names(ast.parse(old)))
