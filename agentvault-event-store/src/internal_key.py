"""Incoming internal-key check with a ROTATION WINDOW (§KEYROT 2026-09-05).

Every reader used to compare against INTERNAL_API_KEY alone, so rotating the key meant a gap in which
every writer (registry, TEG, the sovereign agents) was refused until it was recreated — dropped ledger
events, invisible to Δ (§S4). INTERNAL_API_KEY_PREVIOUS is accepted alongside the current key while
set; unset it (and recreate) once every writer carries the new key. Constant-time on both.
"""
import hmac
import os

_CURRENT = os.getenv("INTERNAL_API_KEY", "")
_PREVIOUS = os.getenv("INTERNAL_API_KEY_PREVIOUS", "")


def configured() -> bool:
    return bool(_CURRENT)


def internal_key_ok(presented) -> bool:
    if not presented or not _CURRENT:
        return False
    if hmac.compare_digest(str(presented), _CURRENT):
        return True
    return bool(_PREVIOUS) and hmac.compare_digest(str(presented), _PREVIOUS)
