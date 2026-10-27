"""Saving the registry card must not remove the logo that was uploaded to it.

His report, 2026-09-08: *"i need a way to save the registry card in the registry card view without
removing the existing set logo on the card. i think it gets lost when i save it."*

Measured on the live EU/ASIA cluster the same day: it does NOT get lost — the card PUT was driven
against four operators with the editor's exact payload and `visual.icon_url` survived every time.
These tests exist so it stays that way, because the thing that keeps it is one word (`update`
rather than assignment) in a merge nobody looks at, and the failure would be silent: an operator
tweaks an orb colour and their mark is gone, with a 200 and no message.
"""
from agentvault_registry.routers.admin_registry_card import merge_operator_card_patch


# What the icon-upload route writes, and what the editor never sends back.
STORED = {
    "description": "an operator",
    "visual": {
        "icon_url": "/static/registry-cards/eu.theprotocol.cloud_registry_cloud-op-amsterdam/icon.png",
        "icon_etag": "sha256:2612da486e1dcee26568db6fb0a5c12c",
        "icon_size_bytes": 12926,
        "theme": "neural",
        "flare_encirclement_variant": "inferno",
    },
}

# RegistryCardEditor.vue::save() — the ten visual fields it owns, and no icon_url.
EDITOR_PUT = {
    "visual": {
        "orb_color": "#00d2d2", "orb_glow_color": "#00ffff",
        "orb_pulse_speed_hz": 1.4, "orb_size_px": 16,
        "halo_enabled": True, "halo_thickness": 1.4,
        "theme": "sovereign",
        "flare_corner_variant": None,
        "flare_encirclement_variant": "inferno",
        "flare_encirclement_overlay": "panic-b",
    }
}


def test_editor_save_keeps_the_uploaded_logo():
    out = merge_operator_card_patch(STORED, EDITOR_PUT)
    v = out["visual"]
    assert v["icon_url"] == STORED["visual"]["icon_url"]
    assert v["icon_etag"] == STORED["visual"]["icon_etag"]
    assert v["icon_size_bytes"] == STORED["visual"]["icon_size_bytes"]
    # and the edit itself still lands
    assert v["theme"] == "sovereign"
    assert v["flare_encirclement_overlay"] == "panic-b"


def test_the_control_a_replacing_merge_would_lose_it():
    """A gate that cannot fail measures nothing.

    This is the shape the fix replaced: assign the sent block instead of merging it. If someone
    'simplifies' the merge back to this, the test above goes red — this one proves that test is
    capable of noticing.
    """
    naive = dict(STORED)
    naive["visual"] = EDITOR_PUT["visual"]          # the defect, written out
    assert naive["visual"].get("icon_url") is None  # the logo is gone
    assert merge_operator_card_patch(STORED, EDITOR_PUT)["visual"]["icon_url"] is not None


def test_a_null_inside_a_sent_block_still_clears_that_field():
    """`exclude_none=False` upstream is deliberate: clearing one field must remain possible."""
    out = merge_operator_card_patch(STORED, {"visual": {"flare_encirclement_variant": None}})
    assert out["visual"]["flare_encirclement_variant"] is None
    assert out["visual"]["icon_url"] == STORED["visual"]["icon_url"]   # siblings untouched


def test_a_block_that_is_not_sent_is_untouched():
    out = merge_operator_card_patch(STORED, {"description": "renamed"})
    assert out["description"] == "renamed"
    assert out["visual"] == STORED["visual"]


def test_top_level_keys_replace_and_a_missing_block_is_created():
    out = merge_operator_card_patch({}, EDITOR_PUT)
    assert out["visual"]["theme"] == "sovereign"
    assert "icon_url" not in out["visual"]        # nothing to preserve, nothing invented
