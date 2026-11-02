"""V0653 (am), item 1 (the hardening list in the sessions' room): one operator-name rule at intake and at use, and the
provisioner's commands as argument lists.

core/operator_names.OPERATOR_SLUG is the one pattern for the name an operator's paths, containers and commands are built
from (cloud_provisioner._safe_name's output: lower case, a-z 0-9 and '-', 40 characters, a letter or digit at both
ends). The application refuses a name that gives no such slug (slug_problem), and every place that builds a path or a
command from a slug checks it again (checked_slug): the cloud provisioner's provisioning and teardown, and the frame
runner's host work, which takes the slug from the registry's request. cloud_provisioner._run took a shell string
(shell=True) at seven sites; it takes an argument vector now and refuses a string. BASE (a5ef48ddd, V0652): no
slug_problem or checked_slug, an application named "!!!" is stored, and _run runs a string through a shell.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import subprocess

import pytest
from fastapi import HTTPException

from agentvault_registry.core import operator_names as on
from agentvault_registry.services import cloud_provisioner as cp

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


@pytest.mark.parametrize("name,slug", [("Amsterdam", "amsterdam"), ("lisbon", "lisbon"), ("Ho Chi Minh", "hochiminh"),
                                       ("op-tokyo-2", "op-tokyo-2"), ("A" * 60, "a" * 40)])
def test_an_ordinary_name_gives_its_slug(name, slug):
    assert on.slug_problem(name) is None
    assert on.checked_slug(cp._safe_name(name)) == slug


@pytest.mark.parametrize("name", ["!!!", "", "   ", "-tokyo", "tokyo-", "____", "a" * 39 + "-b"])
def test_a_name_without_a_usable_slug_is_refused_with_its_reason(name):
    assert on.slug_problem(name)


@pytest.mark.parametrize("slug", ["", "-a", "a-", "A", "a_b", "../x", "a b", "a/b", "a;b", "a" * 41, None])
def test_a_slug_is_checked_where_it_is_used(slug):
    with pytest.raises(ValueError):
        on.checked_slug(slug)


def test_the_application_refuses_a_name_without_a_slug_before_anything_is_stored():
    from agentvault_registry import schemas
    from agentvault_registry.routers import operator_applications as oa
    fn = getattr(oa.submit_operator_application, "__wrapped__", oa.submit_operator_application)
    body = schemas.OperatorApplicationCreate(name="!!!", email="nobody@example.com", accept_operator_terms=True)
    with pytest.raises(HTTPException) as e:
        asyncio.run(fn(request=None, application=body, db=None))   # refused before the database is asked
    assert e.value.status_code == 422 and "!!!" in str(e.value.detail)


def test_run_takes_an_argument_vector_and_never_a_shell(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen.update(args=args, **kw)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    cp._run(["tar", "xzf", "/x/b.tgz", "-C", "/x/s"])
    assert seen["args"] == ["tar", "xzf", "/x/b.tgz", "-C", "/x/s"] and not seen.get("shell")
    with pytest.raises(TypeError):
        cp._run("tar xzf /x/b.tgz -C /x/s; rm -rf /")


def test_no_provisioner_passes_a_string_to_a_shell():
    for rel in ("services/cloud_provisioner.py", "services/operator_provisioner.py", "host_work.py"):
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    assert not (kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True), \
                        f"{rel}:{node.lineno}: shell=True"
                if isinstance(node.func, ast.Name) and node.func.id == "_run" and node.args:
                    assert not _stringy(node.args[0]), f"{rel}:{node.lineno}: _run is given a string"


def _stringy(node) -> bool:
    """A string expression: a str literal, an f-string, or a + with one of those on a side (a list + a list is a list)."""
    if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return True
    if isinstance(node, ast.BinOp):
        return _stringy(node.left) or _stringy(node.right)
    return False
