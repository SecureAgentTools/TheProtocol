"""D8 — the TEG onboarding faucet mounts only while TEG_ONBOARDING_MINT_ENABLED is not off (default on)."""
import pathlib, re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "teg_core_service" / "api" / "v1" / "api.py"


def test_onboarding_mount_is_gated_default_on():
    s = SRC.read_text(encoding="utf-8")
    m = re.search(r'if \(_os_d8\.getenv\("TEG_ONBOARDING_MINT_ENABLED", "true"\).*?\n\s+api_router\.include_router\(endpoints_onboarding\.router', s, re.S)
    assert m, "the onboarding router must mount inside the D8 flag guard"
    assert s.count("endpoints_onboarding.router") == 1, "one mount, inside the guard"
