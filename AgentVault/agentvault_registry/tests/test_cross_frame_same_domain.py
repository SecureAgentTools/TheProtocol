"""§REPBOND-F1 (2026-09-05) — a same-trust-domain target never takes the async cross-frame
branch, whatever TEG_CROSS_FRAME_BACKEND says (HANDOVER_2026-09-04_SANDBOX_MONEYRAIL §3).

Structural: the resolver runs BEFORE the backend choice, the choice is overridden on a
same-domain target, and the lock-then-emit failure is loud (ERROR + the S4 counter).
RED control: `REPBOND_SRC` at a pre-batch tree.
"""
from __future__ import annotations

import os
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ["REPBOND_SRC"]) if os.environ.get("REPBOND_SRC") else HERE.parent / "src" / "agentvault_registry"


def _src():
    p = SRC / "routers" / "teg_integration.py"
    if not p.exists():
        pytest.fail(f"missing {p}")
    return p.read_text(encoding="utf-8")


def test_resolution_precedes_the_backend_choice():
    s = _src()
    i_res = s.find("_f1_target_td = await _f1_resolve(")
    i_choice = s.find('_backend_choice = (backend or os.environ.get("TEG_CROSS_FRAME_BACKEND", "2pc")).lower()')
    assert i_res > 0 and i_choice > 0
    assert i_res < i_choice, "the trust domain must be resolved BEFORE the backend is chosen"


def test_same_domain_forces_the_local_branch():
    s = _src()
    assert 'if _f1_same_domain and _backend_choice == "async":' in s
    assert '_backend_choice = "2pc"' in s
    assert "registry_cross_frame_same_domain_reroutes_total" in s


def test_the_lock_then_emit_failure_is_loud():
    s = _src()
    assert 'logger.warning(f"[CROSS-REG ASYNC] Event emission failed (non-fatal): {e}")' not in s
    assert 'TRANSFER_EVENT_EMIT_FAILURES.labels(path="cross_frame_async_initiated").inc()' in s
