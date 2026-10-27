"""§EMITKEY 2026-09-05 — the emission-integrity axis must authenticate to each
frame's EventStore with THAT frame's own internal key.

WHY THIS EXISTS. `_compute_emission_integrity` polls two EventStores: the local
frame's (`_EMIT_ES_URL`) and the peer frame's (`_EMIT_ES_B_URL`). Before this
change both polls sent a single `_EMIT_ES_KEY`. That is correct only where the
two frames share one internal key -- true on the retired sandbox tier, false on
the sbx-alpha/sbx-beta tier, where each frame holds its own. There, every
B-side poll 403s, `_es_count` returns None, and all four cross-frame checks
render "unknown" -- which is indistinguishable from "the transfer never
settled". A green that cannot go red.

The default is load-bearing: `API_TEST_EVENT_STORE_B_API_KEY` falls back to
`_EMIT_ES_KEY`, so a single-key tier keeps its exact previous behaviour. Test 5
is the control for that; test 6 is the control that the variable is genuinely
read and not hardcoded. Remove either half of `_es_key_for` and one of these
goes red.
"""
import os
import subprocess
import sys

import pytest

from agentvault_registry.routers import mcp_tester as mt


# ── selector logic (module globals patched; no import cost) ─────────────────
@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(mt, "_EMIT_ES_KEY", "KEY-A", raising=True)
    monkeypatch.setattr(mt, "_EMIT_ES_B_KEY", "KEY-B", raising=True)
    monkeypatch.setattr(mt, "_EMIT_ES_B_URL", "http://es-b:8200", raising=True)
    monkeypatch.setattr(mt, "_EMIT_ES_URL", "http://es-a:8200", raising=True)


def test_b_url_uses_b_key(keyed):
    """THE FIX: the peer frame's ES is polled with the peer frame's key."""
    assert mt._es_key_for("http://es-b:8200") == "KEY-B"


def test_a_url_uses_a_key(keyed):
    """The local frame is unaffected."""
    assert mt._es_key_for("http://es-a:8200") == "KEY-A"


def test_unknown_url_uses_a_key(keyed):
    """Anything that is not the B frame keeps the local key -- the B key is
    applied by explicit match, never as a catch-all."""
    assert mt._es_key_for("http://es-somewhere-else:8200") == "KEY-A"


def test_trailing_slash_is_normalised(keyed):
    """`_EMIT_ES_B_URL` is stored rstrip'd; a caller passing a trailing slash
    must still be recognised as the B frame (else it silently gets KEY-A)."""
    assert mt._es_key_for("http://es-b:8200/") == "KEY-B"


# ── import-time default (needs a fresh interpreter per env) ────────────────
_PROBE = (
    "from agentvault_registry.routers import mcp_tester as m; "
    "print('SAME' if m._EMIT_ES_B_KEY == m._EMIT_ES_KEY else 'DISTINCT')"
)


def _probe(env_overrides):
    env = dict(os.environ)
    env.pop("API_TEST_EVENT_STORE_B_API_KEY", None)
    env.update(env_overrides)
    env.setdefault("PYTHONPATH", "/app/src")
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env=env, timeout=180,
    )
    assert out.returncode == 0, f"probe failed: {out.stderr[-800:]}"
    return out.stdout.strip().splitlines()[-1]


def test_unset_b_key_defaults_to_a_key():
    """CONTROL (default-preserving): with the variable unset -- every tier that
    has not been configured for this, including a single-key tier -- the B key
    IS the A key, so behaviour is byte-identical to before the change."""
    assert _probe({}) == "SAME"


def test_set_b_key_is_actually_read():
    """CONTROL (not hardcoded): setting the variable must make the two keys
    differ. If `_EMIT_ES_B_KEY` were pinned to `_EMIT_ES_KEY`, this goes red."""
    assert _probe({"API_TEST_EVENT_STORE_B_API_KEY": "a-different-key"}) == "DISTINCT"
