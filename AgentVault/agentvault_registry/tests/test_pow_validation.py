"""Unit tests for the stateless proof-of-work validator (routers/onboarding.py)."""
import hashlib
import time

from agentvault_registry.routers.onboarding import (
    _leading_zero_bits,
    validate_proof_of_work,
)


def _mine(bits: int = 8, payload: str = "demo-agent", ts: int | None = None) -> str:
    """Mine a solution with at least `bits` leading zero bits."""
    ts = int(time.time()) if ts is None else ts
    nonce = 0
    while True:
        sol = f"v1:{ts}:{payload}:{nonce}"
        if _leading_zero_bits(hashlib.sha256(sol.encode()).digest()) >= bits:
            return sol
        nonce += 1


def test_valid_solution_passes(monkeypatch):
    monkeypatch.setenv("POW_DIFFICULTY_BITS", "8")
    assert validate_proof_of_work(_mine(bits=8)) is True


def test_insufficient_difficulty_fails(monkeypatch):
    monkeypatch.setenv("POW_DIFFICULTY_BITS", "30")
    # An 8-bit solution will practically never satisfy 30 bits.
    assert validate_proof_of_work(_mine(bits=8)) is False


def test_stale_timestamp_fails(monkeypatch):
    monkeypatch.setenv("POW_DIFFICULTY_BITS", "8")
    monkeypatch.setenv("POW_MAX_AGE_SECONDS", "600")
    stale = int(time.time()) - 3600
    assert validate_proof_of_work(_mine(bits=8, ts=stale)) is False


def test_future_timestamp_beyond_skew_fails(monkeypatch):
    monkeypatch.setenv("POW_DIFFICULTY_BITS", "8")
    future = int(time.time()) + 3600
    assert validate_proof_of_work(_mine(bits=8, ts=future)) is False


def test_malformed_and_empty_fail(monkeypatch):
    monkeypatch.setenv("POW_DIFFICULTY_BITS", "8")
    assert validate_proof_of_work(None) is False
    assert validate_proof_of_work("") is False
    assert validate_proof_of_work("not-a-solution") is False
    assert validate_proof_of_work("v2:123:payload:0") is False
    assert validate_proof_of_work("v1:notanint:payload:0") is False


def test_leading_zero_bits_counter():
    assert _leading_zero_bits(bytes([0x00, 0x00, 0xFF])) == 16
    assert _leading_zero_bits(bytes([0x00, 0x0F])) == 12
    assert _leading_zero_bits(bytes([0x80])) == 0
    assert _leading_zero_bits(bytes([0x01])) == 7


if __name__ == "__main__":
    import os, sys
    os.environ.setdefault("POW_DIFFICULTY_BITS", "8")

    class _MP:
        def setenv(self, k, v):
            os.environ[k] = v

    mp = _MP()
    for fn in [test_valid_solution_passes, test_insufficient_difficulty_fails,
               test_stale_timestamp_fails, test_future_timestamp_beyond_skew_fails,
               test_malformed_and_empty_fail]:
        fn(mp)
    test_leading_zero_bits_counter()
    print("ALL PASS")
    sys.exit(0)
