"""§MONEY-M3a (2026-09-03) — R26 the shared admin key carries NO default credential and a
placeholder-shaped configured key never authenticates; R33 the test faucet is OFF unless
TEG_TESTING_FAUCET_ENABLED is true.

Measured before the fix (2026-09-03): the retired non-secret marker string was the configured
ADMIN_API_KEY on 15 of 16 production TEGs and the code compared bearers against it in ten
places; core/config.py shipped `default-admin-key…` and `default-token-signing-key…` literals;
the test faucet (no auth dependency, get_or_create() on its target) was live wherever
ENVIRONMENT was unset — 15 of 16 TEGs.

Pure unit tests, no database. Runner style (python tests/test_admin_key_defaults.py) so the
CI job's "<passed>/<total> passed" floor gate reads it like its siblings. Every literal this
file refuses is written SPLIT, so the tree-absence gates can never match this file itself.
"""
import os
import sys
import pathlib

sys.path.insert(0, "/app")

# secure_config requires these two at import; dummies only, never a production value.
os.environ.setdefault("AVTP_SYSTEM_API_KEY", "ci-dummy-0123456789abcdef0123456789abcdef")
os.environ.setdefault("TEG_TOKEN_SIGNING_KEY", "ci-dummy-0123456789abcdef0123456789abcdef")
os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from src.teg_core_service.core import config as cfg          # noqa: E402
from src.teg_core_service.core import internal_auth as ia    # noqa: E402

REAL = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"   # a SHAPE (64 hex), not a secret


def _with_admin_key(value):
    if value is None:
        os.environ.pop("ADMIN_API_KEY", None)
    else:
        os.environ["ADMIN_API_KEY"] = value
    cfg.get_settings.cache_clear()


def test_unset_key_refuses_everything():
    _with_admin_key(None)
    assert cfg.Settings(_env_file=None).admin_api_key == ""
    assert ia.configured_admin_key() == ""
    assert ia.admin_key_ok("") is False
    assert ia.admin_key_ok("anything") is False
    assert ia.admin_key_ok(None) is False


def test_retired_marker_is_not_a_credential():
    marker = "deprecated-shared-key" + "-retired-mtls-phase4"      # the configured value on 15/16 TEGs today
    _with_admin_key(marker)
    assert ia.looks_like_placeholder(marker)
    assert ia.configured_admin_key() == ""
    assert ia.admin_key_ok(marker) is False


def test_known_defaults_are_not_credentials():
    for lit in ("default-admin-key" + "-change-in-production",
                "deprecated-shared-admin-key" + "-retired-by-mtls-phase4",
                "registry-service" + "-token",
                "x" * 31,
                "0123456789abcdef0123456789abcdef-EXAMPLE-key"):
        _with_admin_key(lit)
        assert ia.admin_key_ok(lit) is False, lit


def test_real_key_matches_exactly():
    _with_admin_key(REAL)
    assert not ia.looks_like_placeholder(REAL)
    assert ia.configured_admin_key() == REAL
    assert ia.admin_key_ok(REAL) is True
    assert ia.admin_key_ok(REAL[:-1] + "1") is False
    assert ia.admin_key_ok(REAL + "0") is False
    assert ia.admin_key_ok("") is False


def test_plain_settings_carry_no_default_credentials():
    # The harness itself exports dummy AVTP/SIGNING values for secure_config; the assertion is
    # about the DEFAULTS, so both dotenv and the process env are withheld for this construction.
    _with_admin_key(None)
    saved = {k: os.environ.pop(k, None) for k in ("TEG_TOKEN_SIGNING_KEY", "AVTP_SYSTEM_API_KEY",
                                                   "REGISTRY_SERVICE_TOKEN")}
    try:
        s = cfg.Settings(_env_file=None)
        assert s.admin_api_key == ""
        assert s.teg_token_signing_key == ""
        assert s.registry_service_token == ""
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_faucet_flag_default_off():
    from src.teg_core_service.api.v1 import endpoints_token as et
    os.environ.pop("TEG_TESTING_FAUCET_ENABLED", None)
    assert et._testing_faucet_enabled() is False
    os.environ["TEG_TESTING_FAUCET_ENABLED"] = "true"
    assert et._testing_faucet_enabled() is True
    os.environ["TEG_TESTING_FAUCET_ENABLED"] = "false"
    assert et._testing_faucet_enabled() is False
    os.environ.pop("TEG_TESTING_FAUCET_ENABLED", None)


def test_tree_carries_no_default_credential_literal():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "teg_core_service"
    frags = ("default-admin-key" + "-change", "default-token-" + "signing-key", "registry-service" + "-token",
             "== settings." + "admin_api_key", "!= settings." + "admin_api_key")
    files = [p for p in root.rglob("*.py") if p.is_file() and ".bak" not in p.name]
    assert len(files) > 50, f"population too small: {len(files)}"   # 83 files on 2026-09-03
    hits = [(str(p.relative_to(root)), f) for p in files for f in frags if f in p.read_text(errors="ignore")]
    assert hits == [], hits


TESTS = [
    test_unset_key_refuses_everything,
    test_retired_marker_is_not_a_credential,
    test_known_defaults_are_not_credentials,
    test_real_key_matches_exactly,
    test_plain_settings_carry_no_default_credentials,
    test_faucet_flag_default_off,
    test_tree_carries_no_default_credential_literal,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
