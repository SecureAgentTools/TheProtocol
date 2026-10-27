"""§FEDLICENCE improvement 16 (2026-09-28): the registry-card admin PUT refuses an unknown key at EVERY level.

`RegistryCardOperatorPut` forbade extras at its top level only. Its nested models (operator and its support contact,
visual, links, commitments) took pydantic's default and IGNORED an unknown key, so a misspelled field one level down
was dropped silently and the PUT answered 200 having saved nothing of it (CLAUDE.md PART 1: "a request body whose
fields the schema does not declare is dropped silently"). The control that matters: the shape the frames SERVE today
must still land, or every console save would start answering 422. EU's editable blocks below are copied from its
public card of 2026-09-28; all ten live cards (4 frames, 6 operators) were validated the same way before this landed.
"""
from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from agentvault_registry import schemas as S

EU_EDITABLE = json.loads(r'''{
 "commitments": {
  "card_refresh_max_minutes": 5,
  "data_residency": "EU",
  "deprecation_notice_days": 30,
  "gdpr_compliant": true,
  "incident_disclosure_sla_hours": 72,
  "key_rotation_max_days": 90,
  "legally_binding_disclaimer": "A sovereign registry of TheProtocol network operated from Brussels under EU jurisdiction; not a bank, not a payment institution; the ECU is a network unit, not legal tender.",
  "support_response_hours": 72,
  "uptime_sla_pct": 99.0
 },
 "description": "EU — the European frame of TheProtocol network, operated from Brussels under EU jurisdiction (GDPR). A sovereign agent registry with its own unit, the ECU: open registration behind a reputation bond, enforcement that reaches every mirror, an AGORA venue, a guild, and an FX pool with its Asian sibling. Two cloud operators, Amsterdam and Lisbon, federate under it. EU is the anchor of this network: a frame that federates here holds a licence issued here.",
 "links": {
  "docs": "https://docs.theprotocol.cloud",
  "incident_log": "https://theprotocol.cloud/status",
  "privacy_policy": "https://theprotocol.cloud/#/privacy",
  "status_page": "https://eu.theprotocol.cloud/status",
  "support_url": "https://theprotocol.cloud/#/support",
  "terms_of_service": "https://theprotocol.cloud/#/terms"
 },
 "operator": {
  "bio": null,
  "company": "TheProtocol EU",
  "display_name": "TheProtocol EU",
  "github_url": null,
  "latitude": 50.8503,
  "location_label": "Brussels, Belgium",
  "longitude": 4.3517,
  "operator_avatar_url": null,
  "operator_since": "2026-09-07T16:20:36.509616+00:00",
  "successor_contact": null,
  "support_contact": null,
  "timezone": null,
  "twitter_handle": null,
  "url": null
 },
 "tags": [
  "eu",
  "europe",
  "gdpr",
  "sovereign-frame",
  "agora",
  "fx",
  "guild",
  "reputation-bond"
 ],
 "visual": {
  "flare_corner_variant": null,
  "flare_encirclement_overlay": "panic-a",
  "flare_encirclement_variant": "inferno",
  "halo_enabled": true,
  "halo_thickness": 1.4,
  "icon_url": "/static/registry-cards/eu.theprotocol.cloud_registry_EU/icon.png",
  "orb_color": "#00d2d2",
  "orb_glow_color": "#00ffff",
  "orb_pulse_speed_hz": 1.4,
  "orb_size_px": 16,
  "sovereign_variant": null,
  "theme": "neural"
 }
}''')

NESTED = (S.RegistryCardSupportContact, S.RegistryCardOperator, S.RegistryCardVisual, S.RegistryCardLinks,
          S.RegistryCardCommitments)


def _refused(body, *path):
    with pytest.raises(ValidationError) as ei:
        S.RegistryCardOperatorPut(**body)
    locs = [tuple(e["loc"]) for e in ei.value.errors() if e["type"] == "extra_forbidden"]
    assert tuple(path) in locs, locs


def test_control_the_shape_a_frame_serves_today_still_lands():
    S.RegistryCardOperatorPut(**copy.deepcopy(EU_EDITABLE))


@pytest.mark.parametrize("block,key", [("operator", "lattitude"), ("visual", "colour"), ("links", "webiste"),
                                       ("commitments", "uptime_sla_pc")])
def test_a_misspelled_key_one_level_down_is_refused(block, key):
    body = copy.deepcopy(EU_EDITABLE)
    body[block][key] = 1
    _refused(body, block, key)


def test_a_misspelled_key_two_levels_down_is_refused():
    body = copy.deepcopy(EU_EDITABLE)
    body["operator"]["support_contact"] = {**(body["operator"].get("support_contact") or {}), "emial": "x@example.org"}
    _refused(body, "operator", "support_contact", "emial")


def test_control_the_top_level_still_refuses_a_locked_field():
    body = {**copy.deepcopy(EU_EDITABLE), "identity": {}}
    _refused(body, "identity")


def test_every_nested_model_forbids_extras():
    assert all(m.model_config.get("extra") == "forbid" for m in NESTED)
