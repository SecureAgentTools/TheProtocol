"""§SLUGCONVERGE — the identity / infra-label rule for the four renamed operators (pure, no network)."""
from agentvault_registry.core.operator_names import (INFRA_LABEL_TO_IDENTITY, IDENTITY_TO_INFRA_LABEL, collapse_to_identity,
                                                     identity_slug, infra_label, scrape_job)


def _svc(name, url=None, **kw):
    return dict({"name": name, "url": url or f"https://{name}.frame-b.theprotocol.cloud:8443/health", "group": "operator", "publicUrl": None}, **kw)


def test_the_label_maps_onto_the_identity_and_the_identity_knows_its_container_and_job():
    assert identity_slug("op-singapore") == "op-losangeles"
    assert identity_slug("OP-Sydney") == "op-chicago"
    assert identity_slug("op-seoul") == "op-houston"
    assert identity_slug("op-tokyo") == "op-newyork"
    assert identity_slug("op-losangeles") == "op-losangeles"       # an identity passes through
    assert identity_slug("op-berlin") == "op-berlin"
    assert identity_slug("Registry A") == "Registry A"
    assert identity_slug(None) == ""
    assert infra_label("op-chicago") == "cloud-op-op-sydney" and infra_label("op-berlin") is None
    assert scrape_job("op-losangeles") == "op-singapore" and scrape_job("op-berlin") == "op-berlin"
    assert set(IDENTITY_TO_INFRA_LABEL) == set(INFRA_LABEL_TO_IDENTITY.values())


def test_a_lone_label_face_is_renamed_in_place_and_keeps_its_probe_url():
    out = collapse_to_identity([_svc("Registry A", "http://registry-a:8000/health", group="core"), _svc("op-sydney"), _svc("op-berlin")])
    assert [s["name"] for s in out] == ["Registry A", "op-chicago", "op-berlin"]
    assert out[1]["url"] == "https://op-sydney.frame-b.theprotocol.cloud:8443/health"   # the alias still answers
    assert out[1]["infra_label"] == "cloud-op-op-sydney" and "infra_label" not in out[2]


def test_both_faces_collapse_and_the_identity_keeps_the_seat_in_either_order():
    ghost = _svc("op-singapore"); ident = _svc("op-losangeles", publicUrl="https://op-losangeles.frame-b.theprotocol.cloud")
    out = collapse_to_identity([ghost, ident, _svc("op-doha")])
    assert [s["name"] for s in out] == ["op-losangeles", "op-doha"]
    assert out[0]["publicUrl"] == ident["publicUrl"] and out[0]["infra_label"] == "cloud-op-op-singapore"
    out2 = collapse_to_identity([ident, ghost])
    assert len(out2) == 1 and out2[0]["publicUrl"] == ident["publicUrl"]


def test_the_measured_shape_fourteen_tiles_for_thirteen_operators_becomes_thirteen_identities():
    names = ["op-abudhabi", "op-berlin", "op-chicago", "op-doha", "op-houston", "op-london", "op-losangeles", "op-newyork",
             "op-paris", "op-riyadh", "op-singapore", "op-telaviv", "op-washington", "qatest16"]
    out = collapse_to_identity([_svc(n) for n in names])
    got = [s["name"] for s in out]
    assert len(got) == 13 and len(set(got)) == 13
    assert not (set(got) & set(INFRA_LABEL_TO_IDENTITY))          # no bare label survives
    assert {"op-losangeles", "op-chicago", "op-houston", "op-newyork"} <= set(got)
    assert sum(1 for s in out if s.get("infra_label")) == 4


def test_self_is_dropped_under_either_face_and_the_rule_is_idempotent():
    out = collapse_to_identity([_svc("op-singapore"), _svc("op-losangeles"), _svc("op-berlin")], drop={"op-losangeles"})
    assert [s["name"] for s in out] == ["op-berlin"]
    once = collapse_to_identity([_svc("op-sydney"), _svc("op-chicago"), _svc("op-paris")])
    assert collapse_to_identity(once) == once
