"""V0655 (ax), order gwo_75fb1d4d0b83d0e7bee5ac2f: no key-shaped literal in the registry's tests or source, by the shapes the
OSS export's G2 gate refuses, checked by the suite before a cut instead of at the kit's export.

V0654 (at)'s tests/test_mcp_earned_chat_tools.py wrote its fake developer key as ONE avreg_ literal of 24 characters or
more. The suite passed, the image was certified and rolled to production, and the first beta.33 export refused on G2;
kit/beta33 (acb3fc21f3) builds that key from two strings. This check runs in the suite, so a cut that carries such a literal
fails its build. A fake key in a fixture is built from parts ("avreg_" + "..."), so no single literal has a real key's shape.

The shapes mirror the stack's scripts/distribution/oss_export.py SHAPES (that repository is not beside this one in CI, so
they are copied, not imported): change both together. A hit names the file, the line and the shape, never the text it
matched (it may be a real secret).
"""
from __future__ import annotations

import pathlib
import re

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
SRC = TESTS.parent / "src" / "agentvault_registry"
SKIP_DIRS = {"node_modules", "dist", "__pycache__", ".git", "target", ".pytest_cache", ".venv", "venv"}
TEXT_MAX = 8 * 1024 * 1024          # oss_export.py's TEXT_MAX: larger files are not text the gate reads

SHAPES = {
    # a PEM header followed by a base64 BODY: a docstring that quotes the header line alone is not a key
    "pem_private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/=\r\n ]{40,}"),
    "avreg_api_key": re.compile(rb"\bavreg_[A-Za-z0-9_-]{24,}"),
    "dpt_pull_token": re.compile(rb"\bdpt_[0-9a-f]{40,}"),
    "tp_fed_licence": re.compile(rb"\btp_fed_[0-9a-f]{40,}"),
    "hex_secret_assignment": re.compile(
        rb"(?i)\b[A-Z_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|INTERNAL_KEY)[A-Z_]*\b[\"']?\s*[:=]\s*[\"']?[0-9a-f]{40,}\b"),
}
# What each match must contain, tested first (exact: no match lacks it): the scan reads about 270 MB, and the anchored
# patterns alone took about 20 s of it; with these it takes about 4 s.
MUST_CONTAIN = {
    "pem_private_key": b"PRIVATE KEY-----",
    "avreg_api_key": b"avreg_",
    "dpt_pull_token": b"dpt_",
    "tp_fed_licence": b"tp_fed_",
    "hex_secret_assignment": re.compile(rb"[0-9a-fA-F]{40}"),
}


def _files(root: pathlib.Path):
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts) or not p.is_file():
            continue
        if p.stat().st_size > TEXT_MAX:
            continue
        yield p


def _hits(root: pathlib.Path):
    scanned, hits = 0, []
    for p in _files(root):
        body = p.read_bytes()
        scanned += 1
        for name, rx in SHAPES.items():
            need = MUST_CONTAIN[name]
            if not (need in body if isinstance(need, bytes) else need.search(body)):
                continue
            for m in rx.finditer(body):
                line = body.count(b"\n", 0, m.start()) + 1
                hits.append(f"{p.relative_to(root.parent)}:{line}: {name}")
    return scanned, hits


@pytest.mark.parametrize("root, floor", [(TESTS, 500), (SRC, 1000)], ids=["tests", "src"])
def test_no_key_shaped_literal(root, floor):
    scanned, hits = _hits(root)
    assert scanned >= floor, f"read {scanned} files under {root}, expected at least {floor}: the check measured too little"
    assert not hits, ("key-shaped literals (the export's G2 refuses them; build a fake key from parts, "
                      "'avreg_' + '...'):\n  " + "\n  ".join(hits))


@pytest.mark.parametrize("name, sample", [
    ("avreg_api_key", b"KEY = 'avreg_" + b"offline-test-key-of-the-run'"),   # V0654's line, joined into one literal
    ("avreg_api_key", b"avreg_" + b"a" * 24),
    ("pem_private_key", b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64),
    ("dpt_pull_token", b"dpt_" + b"0" * 40),
    ("tp_fed_licence", b"tp_fed_" + b"f" * 40),
    ("hex_secret_assignment", b"ADMIN_API_KEY=" + b"ab" * 20),
])
def test_each_shape_fires_on_its_control(name, sample):
    assert SHAPES[name].search(sample), f"{name} did not fire on its control: the check would pass blind"
    need = MUST_CONTAIN[name]
    assert (need in sample if isinstance(need, bytes) else need.search(sample)), f"{name}'s prefilter skips its control"


@pytest.mark.parametrize("sample", [
    b"KEY = 'avreg_' + 'offline-test-key-of-the-run'",                       # kit/beta33's line: two strings
    b"avreg_" + b"a" * 23,                                                   # shorter than a real key
    b"-----BEGIN " + b"PRIVATE KEY----- (the header alone, quoted in a docstring)",
])
def test_a_fixture_built_from_parts_passes(sample):
    assert not any(rx.search(sample) for rx in SHAPES.values())
