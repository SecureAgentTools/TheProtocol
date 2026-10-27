"""§DEPS (2026-09-27): requirements.txt is the image's exact package set, so what a scanner reports is what runs.

The registry image installs from the Dockerfile's pin list resolved against constraints-network.txt (the image's own
`pip freeze --all`). Dependency scanners read neither: GitHub's Dependabot reads requirements.txt. Until V0474 that file
held version RANGES nobody had run for months (fastapi 0.111, cryptography 41), so 21 of its alerts described nothing
real while the image's real packages (aiohttp 3.9.5, starlette 0.37.2) raised none. This test keeps the two files the
same SET of name==version lines, so the file a scanner reads cannot drift from the one the build installs from.
"""
from __future__ import annotations

import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOTS = [os.path.join(HERE, ".."), "/app"]


def _pins(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", line)
        assert m, f"{os.path.basename(path)}: not a name==version line: {line!r}"
        name = re.sub(r"[-_.]+", "-", m.group(1)).lower()
        assert name not in out, f"{os.path.basename(path)}: {name} twice"
        out[name] = m.group(2)
    return out


def _pair():
    for root in ROOTS:
        req, con = os.path.join(root, "requirements.txt"), os.path.join(root, "constraints-network.txt")
        if os.path.isfile(req) and os.path.isfile(con):
            return req, con
    pytest.skip("requirements.txt and constraints-network.txt are not beside the tests here")


def test_requirements_is_the_image_set():
    req, con = _pair()
    r, c = _pins(req), _pins(con)
    assert len(c) >= 100, f"constraints-network.txt holds {len(c)} pins: not an image freeze"
    only_r = {k: r[k] for k in r.keys() - c.keys()}
    only_c = {k: c[k] for k in c.keys() - r.keys()}
    differ = {k: (r[k], c[k]) for k in r.keys() & c.keys() if r[k] != c[k]}
    assert not (only_r or only_c or differ), f"only in requirements {only_r}; only in constraints {only_c}; differ {differ}"


def test_the_mirror_can_fail(tmp_path):
    # the control: a one-version drift must be seen
    req, con = _pair()
    lines = open(con, encoding="utf-8").read().splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("fastapi=="))
    lines[i] = "fastapi==0.111.0"
    drifted = tmp_path / "requirements.txt"
    drifted.write_text("\n".join(lines) + "\n")
    assert _pins(str(drifted))["fastapi"] != _pins(con)["fastapi"]
