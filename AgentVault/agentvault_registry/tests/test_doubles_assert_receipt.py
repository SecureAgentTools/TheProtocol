"""Batch 2 item 2 — the ratchet: a test that stands in for the event emitter must either use the
STRICT double (tests/_doubles.py) or assert receipt on its own recorder. A permissive
MagicMock/AsyncMock emitter with no receipt assertion is the shape that let every bond event
vanish for two hours (§EMITKEY). The allowlist below is the measured baseline on 2026-09-05;
it may only shrink.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
LEGACY_ALLOWED = {
    "test_bulk_transfer_emit.py",      # records via monkeypatched emitter attributes; asserted by count — reads fine, not strict
    "test_coordinated_suspension.py",  # AsyncMock side_effects append to emitter_calls and the test asserts on it
    "test_reward_funding.py",          # AsyncMock emitter with assert_awaited on the calls
}


def test_every_emitter_double_asserts_receipt_or_is_strict():
    offenders = []
    for f in sorted(HERE.glob("test_*.py")):
        s = f.read_text()
        if "get_event_emitter" not in s and "fake_emitter" not in s and "StrictEmitter" not in s:
            continue
        strict = "StrictEmitter" in s
        asserts = re.search(r'assert_received|assert_awaited|assert_called|assert .*emitter_calls|assert .*\.received|assert\s+received\b|received\[', s)
        if not strict and not asserts and f.name not in LEGACY_ALLOWED:
            offenders.append(f.name)
    assert not offenders, f"emitter doubles that never assert receipt: {offenders}"


def test_legacy_allowlist_only_shrinks():
    present = {n for n in LEGACY_ALLOWED if (HERE / n).exists()}
    assert present == LEGACY_ALLOWED, f"a legacy file vanished or was renamed: {LEGACY_ALLOWED - present}"
