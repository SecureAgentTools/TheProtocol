"""§BATCH5 — operator peer rows are TYPED at creation, not left to the column default.

Measured on the fresh JUICE pair (2026-09-05): the frame's row for each operator and the
operator's row for its parent both read ``direct_peer``. Production reads ``cloud_operator``
(frame → op) and ``frame`` (op → parent) — but only because main.py's startup reclassify pass
ran AFTER those rows existed. On a fresh standup the rows are written ~20 s after the
processes boot, the pass never sees them, and until the next restart the op's FX guard
cannot tell its parent is a frame (the 2026-06-04 class). This gate parses the three write
sites so the type travels with the write.
"""
from __future__ import annotations

import ast
import pathlib
import re

import agentvault_registry as _pkg  # the package that is actually importable (CI mounts tests beside /app/src, not beside src/)

SRC = pathlib.Path(_pkg.__file__).resolve().parent


def _peer_registry_calls(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "PeerRegistry":
                yield node


def _kw(node, key):
    for kw in node.keywords:
        if kw.arg == key and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def test_forward_rows_are_cloud_operator():
    for rel in ("routers/cloud_operators.py", "routers/operator_self_service.py"):
        calls = list(_peer_registry_calls(SRC / rel))
        assert calls, f"{rel}: no PeerRegistry(...) constructor found"
        for c in calls:
            assert _kw(c, "peer_type") == "cloud_operator", f"{rel}:{c.lineno} PeerRegistry(...) lacks peer_type='cloud_operator'"


def test_reverse_row_is_frame():
    src = (SRC / "services/cloud_provisioner.py").read_text(encoding="utf-8")
    m = re.search(r'INSERT INTO peer_registries \(name, base_url, status, owner_developer_id, "\s*\n(?:.*\n){0,4}?.*trust_domain, peer_type\) "', src)
    assert m, "the reverse-peer INSERT does not name peer_type"
    tail = src[m.end(): m.end() + 900]
    assert "'frame')" in tail, "the reverse-peer VALUES do not end in 'frame'"
    assert "\"peer_type = 'frame', \"" in tail, "the ON CONFLICT branch does not restate peer_type = 'frame'"


def test_control_the_gate_can_fail():
    # a constructor without the keyword must be caught — build one and run the same predicate
    node = ast.parse("models.PeerRegistry(name='x', status='ACTIVE')").body[0].value
    assert _kw(node, "peer_type") is None
