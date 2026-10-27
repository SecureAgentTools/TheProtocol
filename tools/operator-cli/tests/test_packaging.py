"""Every package the CLI imports is one its build installs (CB-300).

`tp mcp serve` imports the mcp package, which neither requirements.txt nor pyproject.toml listed, so a `tp` built from
requirements.txt failed at that import. This reads every import in tp_operator (function-level ones included: mcp is
imported inside _serve) and holds the third-party ones to requirements.txt; pyproject offers the same as an extra.
"""
import ast
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def _imported_top_level_modules():
    names = set()
    for path in (HERE / "tp_operator").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names - set(sys.stdlib_module_names) - {"tp_operator", "__future__"}


def _requirements():
    out = set()
    for line in (HERE / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(re.split(r"[<>=!~\[ ]", line, 1)[0].lower())
    return out


def test_every_third_party_import_is_a_requirement():
    missing = sorted(_imported_top_level_modules() - _requirements())
    assert not missing, f"imported by tp_operator but not in requirements.txt: {missing}"


def test_pyproject_offers_mcp_and_the_umbrella():
    project = tomllib.loads((HERE / "pyproject.toml").read_text())["project"]
    assert any(d.startswith("mcp") for d in project["optional-dependencies"]["mcp"])
    assert project["scripts"]["tp"] == "tp_operator.umbrella:umbrella"
