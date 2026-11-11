"""V0658 (2026-11-08, session-tester; the Commander's word at room seq 2220, session-lead's order at seq 2225): the
registry image carries pytest-xdist, so the whole suite runs in parallel inside the image (`python -m pytest -n <N>`)
instead of one process for 12-13 minutes.

The image installs its test tools from the Dockerfile's pin list resolved against constraints-network.txt (the image's
own freeze); requirements.txt mirrors that file (test_requirements_mirror_the_image.py). Pinned here: the Dockerfile
installs pytest-xdist at exactly the version the constraints name, and the constraints carry its one dependency,
execnet, so a rebuild installs the same two packages and pip check stays clean. BASE (v0657/cut): no pin anywhere.
"""
from __future__ import annotations

import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")


def _read(name):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        pytest.skip(f"{name} is not beside the tests here")
    return open(path, encoding="utf-8").read()


def _pin(text, name):
    m = re.search(rf"^{re.escape(name)}==(\S+)$", text, re.MULTILINE)
    return m.group(1) if m else None


def test_the_image_installs_pytest_xdist_at_the_constrained_version():
    dockerfile, constraints = _read("Dockerfile"), _read("constraints-network.txt")
    wanted = _pin(constraints, "pytest-xdist")
    assert wanted, "constraints-network.txt names no pytest-xdist"
    installs = re.findall(r"^\s*pytest-xdist==(\S+?)\s*\\?$", dockerfile, re.MULTILINE)
    assert installs == [wanted], f"the Dockerfile installs pytest-xdist {installs}, the constraints name {wanted}"


def test_its_dependency_is_constrained_too():
    constraints = _read("constraints-network.txt")
    assert _pin(constraints, "execnet"), "constraints-network.txt names no execnet (pytest-xdist needs it)"
