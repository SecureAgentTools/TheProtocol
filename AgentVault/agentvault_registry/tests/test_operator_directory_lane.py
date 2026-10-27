"""§OPDIST — a provisioned cloud operator is born knowing its frame's federated index.

His first-named requirement ("connected to everything the frame provides ... DIRECTORY, es, kafka, redis ...
auditor"), measured absent on every operator on this box: 24 operator stacks, 0 carrying either key.

§FRAMELIC's rule is that a capability with several halves must be written by ONE flag or a clean reprovision drops
the ones nobody templated — and this lane's halves turned out to be TWO env values, not four, because an operator
can already read its parent's index through the parent's own public proxy (measured live before the code was
written: health 200 and graphql 200 from inside cloud-op-amsterdam-registry, unauthenticated).

Structural: the provisioner is an async function against a live host, so the ENV BLOCK is parsed rather than run.
Control: both tests RED against the pre-fix source via OPDIST_SRC.
"""
from __future__ import annotations

import os
import pathlib
import re

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")


def _provisioner() -> str:
    path = _SRC / "services" / "cloud_provisioner.py"
    if not path.is_file():
        path = _SRC / "cloud_provisioner.py"
    return path.read_text(encoding="utf-8")


def test_the_operator_env_carries_both_halves_of_the_lane():
    """Both, or neither is worth writing: the registry ANDs the flag with the address and the console ANDs them
    again, which is how shipping two of three halves still rendered nothing in §FRAMELIC."""
    src = _provisioner()
    assert 'f.write(f"DIRECTORY_PUBLIC_URL=' in src, "the operator must be told where the index is"
    assert 'f.write("DISCOVERY_VIA_DIRECTORY=true' in src, "and that it may use it"


def test_the_address_is_the_public_one_an_operator_can_resolve():
    """§MTLSGAP row 203 measured that CENTRAL_REGISTRY_URL is an internal docker name an operator cannot resolve,
    and the whole point of MAINFRAME_PUBLIC_URL is to be the one it can."""
    src = _provisioner()
    line = next(l for l in src.splitlines() if "DIRECTORY_PUBLIC_URL=" in l)
    assert "_mainframe_public" in line, f"the index address must be the public base: {line.strip()}"
    assert "CENTRAL_REGISTRY_URL" not in line
    assert "/api/v1/public/directory" in line, "the parent's own proxy path, the one its console uses"
    # and it must sit inside the https-only branch, or an operator gets an address that cannot work
    body = src[src.index('if _mainframe_public.startswith("https://"):'):]
    assert body.index("DIRECTORY_PUBLIC_URL=") < body.index("else:"), (
        "the lane must be written only where the public base is real")
