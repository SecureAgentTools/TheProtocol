"""§FESUITE: every recovery key a person is given works, each exactly once.

Registration handed out three keys and stored the hash of the first only ("one representative key"): keys two and
three could never recover the account, and the first, once used, left the account with none while the person still
held two they believed in. One hash per key now lives in the same column (newline-separated; a legacy single hash is
one key), and the key presented is burned when it verifies.
"""
from agentvault_registry import security


def test_every_key_matches_its_own_hash():
    keys = security.generate_recovery_keys()
    stored = security.hash_recovery_keys(keys)
    assert len(security.recovery_key_hashes(stored)) == 3
    assert [security.match_recovery_key(k, stored) for k in keys] == [0, 1, 2]
    assert security.match_recovery_key("avrec-00000000-00000000-00000000", stored) is None
    assert security.match_recovery_key("", stored) is None


def test_a_key_works_once_and_the_others_stay():
    keys = security.generate_recovery_keys()
    stored = security.hash_recovery_keys(keys)
    used = security.match_recovery_key(keys[1], stored)
    stored = security.burn_recovery_key(stored, used)
    assert security.match_recovery_key(keys[1], stored) is None, "a burned key never works again"
    assert security.match_recovery_key(keys[0], stored) is not None
    assert security.match_recovery_key(keys[2], stored) is not None
    for k in (keys[0], keys[2]):
        stored = security.burn_recovery_key(stored, security.match_recovery_key(k, stored))
    assert stored is None, "no key left reads as none stored"


def test_a_legacy_single_hash_is_one_key():
    key = security.generate_recovery_keys(1)[0]
    legacy = security.hash_recovery_key(key)
    assert security.recovery_key_hashes(legacy) == [legacy]
    assert security.match_recovery_key(key, legacy) == 0
    assert security.burn_recovery_key(legacy, 0) is None
    assert security.match_recovery_key(key, None) is None
