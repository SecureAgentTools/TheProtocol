"""§RESIDUES C2 (2026-09-13): the diagnostics targets rail lists the operators THIS frame knows, not every
`cloud-op-*` container on the host (sbx-alpha listed EU's and ASIA's operators and the three retiring mainframes)."""
from agentvault_registry.services.diagnostics.targets import scope_operator_slugs, scope_mainframes


def test_scope_keeps_admitted_and_own_operators_and_chained_children():
    discovered = ["amsterdam", "hochiminh", "lisbon", "sbxalphaop", "sbxbetaop", "shenzhen", "api-test-operator-7"]
    enrichment = {"op-sbxalphaop": {"display_name": "sbxalphaop"}}
    own = {"sbxalphaop"}
    assert scope_operator_slugs(discovered, enrichment, own) == ["api-test-operator-7", "sbxalphaop"]


def test_scope_control_a_frame_that_admitted_everything_keeps_everything():
    discovered = ["amsterdam", "lisbon"]
    enrichment = {"op-amsterdam": {}, "op-lisbon": {}}
    assert scope_operator_slugs(discovered, enrichment, set()) == ["amsterdam", "lisbon"]


def test_scope_by_own_peer_row_when_no_application_exists():
    assert scope_operator_slugs(["berlin"], {}, {"op-berlin"}) == ["berlin"]
    assert scope_operator_slugs(["berlin"], {}, set()) == []


def test_mainframes_belong_to_the_frame_that_is_one_of_them():
    entries = [{"operator_id": "registry-a", "display_name": "Registry A (Mainframe)"}, {"operator_id": "frame-b", "display_name": "Frame B"}]
    assert scope_mainframes(entries, {"sandbox alpha", "sbx-alpha"}) == []
    assert [e["operator_id"] for e in scope_mainframes(entries, {"registry-a"})] == ["registry-a"]
    assert [e["operator_id"] for e in scope_mainframes(entries, {"sandbox alpha"}, fleet_all=True)] == ["registry-a", "frame-b"]
