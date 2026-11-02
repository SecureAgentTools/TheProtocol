"""V0653 (am) item 1 (session-lead, the sessions' room seq 895): cloud_provisioner._run's seven call sites, driven.

Each site's own argument list, read out of the source (not copied here), is built with hostile values and passed through
the real _run with subprocess.run replaced: every value stays one whole argument (no shell ever reads it), no call asks
for a shell, and where a step runs `sh -c` its script is a constant (the values ride as its positional arguments). These
sites run only where the registry holds a docker socket (Frame A's direct path); a runner-built frame's operator work
goes through the runner, which every pair run drives live (session-tester, seq 893), so no proof reaches them. A new site
fails the count here, on purpose: add it to the drive. The cases marked BASE fail on a5ef48ddd (V0652), where the sites
were shell strings.
"""
from __future__ import annotations

import ast
import inspect
import subprocess

from agentvault_registry.services import cloud_provisioner as cp

# every name a site interpolates, with a value a shell would split, substitute or end a command at
HOSTILE = {
    "bundle_path": "/tmp/b dl;rm -rf /;$(id).tgz",
    "stack_dir_container": "/stack/op x;$(id)",
    "safe": "evil;$(id) x",
    "domain": "a.example;$(id) 'x\"",
    "fed_port": 31443,
    "stack_dir_host": "/opt/theprotocol/stack/op y;$(id)",
}


def _sites():
    tree = ast.parse(inspect.getsource(cp))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_run"]


def _value(expr):
    code = compile(ast.fix_missing_locations(ast.Expression(body=expr)), "<site>", "eval")
    return eval(code, {"__builtins__": {"str": str}}, dict(HOSTILE))   # noqa: S307 - the module's own literals


def test_seven_sites_each_an_argument_list():
    # BASE: the sites were f-strings (a shell command line)
    sites = _sites()
    assert len(sites) == 7, f"{len(sites)} _run sites: a new one must join this drive"
    for s in sites:
        assert isinstance(s.args[0], ast.List), ast.unparse(s)[:200]
        names = {n.id for n in ast.walk(s.args[0]) if isinstance(n, ast.Name)} - {"str"}
        assert names <= set(HOSTILE), f"a site interpolates a name this drive does not set: {names - set(HOSTILE)}"


def test_each_site_through_the_real_run_keeps_every_value_one_argument(monkeypatch):
    # BASE: _run took a string and ran it through a shell
    calls = []

    def fake_run(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    sites = _sites()
    for node in sites:
        kwargs = {k.arg: _value(k.value) for k in node.keywords if k.arg in ("timeout", "cwd")}
        cp._run(_value(node.args[0]), **kwargs)
    assert len(calls) == len(sites) == 7
    for (args, kw), node in zip(calls, sites):
        where = ast.unparse(node)[:120]
        assert isinstance(args, list) and all(isinstance(a, str) for a in args), where
        assert not kw.get("shell"), where
        names = {n.id for n in ast.walk(node.args[0]) if isinstance(n, ast.Name)} & set(HOSTILE)
        for name in names:
            v = str(HOSTILE[name])
            # whole: the argument is the value, or the value closes it (f"cloud-op-{safe}", "path:path")
            assert any(a == v or a.endswith(v) for a in args), (where, name)
        if "-c" in args:
            script = args[args.index("-c") + 1]
            assert not any(str(v) in script for v in HOSTILE.values()), f"a value inside a shell script: {where}"


def test_a_shell_string_is_refused():
    # control on the branch (V0652's _run took the string and ran it)
    try:
        cp._run("tar xzf /tmp/x.tgz -C /tmp/y")
    except TypeError as e:
        assert "argument vector" in str(e)
    else:
        raise AssertionError("_run ran a shell string")
