"""The admin attestation page reports the ZKP phases that run.

Before V0613 it read each switch with "false" as the default, while the attestation router and its
workers read "true": a registry that never set them (sbx-beta, every operator) was shown running no
phase while all five ran, and a sixth phase with no switch behind it was counted.
"""
from agentvault_registry.routers import admin_health

SWITCHES = [f"ZKP_PHASE_{i}_ENABLED" for i in range(1, 7)]


def _unset(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)


def test_unset_switches_are_reported_on_as_the_router_reads_them(monkeypatch):
    _unset(monkeypatch)
    assert admin_health.zkp_phase_state() == {f"phase_{i}": True for i in range(1, 6)}


def test_a_switch_set_off_is_reported_off(monkeypatch):
    _unset(monkeypatch)
    monkeypatch.setenv("ZKP_PHASE_3_ENABLED", "false")
    state = admin_health.zkp_phase_state()
    assert state["phase_3"] is False and sum(state.values()) == 4


def test_no_sixth_phase_is_reported(monkeypatch):
    _unset(monkeypatch)
    monkeypatch.setenv("ZKP_PHASE_6_ENABLED", "true")
    assert "phase_6" not in admin_health.zkp_phase_state()
