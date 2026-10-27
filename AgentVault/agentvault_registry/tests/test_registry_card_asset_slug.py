"""Tests for the registry-card asset-slug drift fix.

The defect: `upload_registry_card_icon` FREEZES `/static/registry-cards/<slug>/
icon.png` into the card row, while the file itself is written (and rehydrated at
startup) to a slug derived LIVE from the registry name. Rename the registry and
the two drift — the file follows, the advertised URL does not, and the card
points at a 404 until somebody re-uploads.

Measured in production: hetzner-frame was renamed "Hetzner Frame" ->
"Hetzner-Frame" on 2026-07-29 and its icon served 21 x 404 under the new slug
until it was re-uploaded (nginx access log).

These exercise the pure helpers in isolation (no DB, no app) — the same shape as
test_agent_card_export.py.
"""
import pytest

from agentvault_registry.services import registry_card_builder as rcb


@pytest.fixture
def named_registry(monkeypatch):
    """Rename the registry the way the deployment does: one setting."""
    def _rename(name: str) -> str:
        monkeypatch.setattr(rcb.settings, "REGISTRY_NAME", name, raising=False)
        return rcb.card_asset_slug()
    return _rename


# ── the slug itself ─────────────────────────────────────────────────────────

def test_slug_is_url_safe_for_a_name_with_spaces(named_registry):
    """A raw space is not fetchable; browsers hide it by auto-encoding img src."""
    slug = named_registry("Hetzner Frame")
    assert " " not in slug
    assert "Hetzner-Frame" in slug


def test_slug_follows_the_registry_name(named_registry):
    before = named_registry("Frame-B")
    after = named_registry("Texas")
    assert before != after, "the storage slug must move with the name (this is the hazard)"


def test_space_and_hyphen_names_collapse_to_one_slug(named_registry):
    """Why the 2026-07-29 burst was NOT a rename: the sanitiser makes these equal,
    so the drift there came from the SLUG SCHEME changing, not the name."""
    assert named_registry("Hetzner Frame") == named_registry("Hetzner-Frame")


# ── normalisation: the fix ──────────────────────────────────────────────────

def test_unsanitised_legacy_slug_is_repointed(named_registry):
    """THE REGRESSION TEST for the 2026-07-29 hetzner 404 burst.

    Before the sanitiser existed the upload froze a slug containing a RAW SPACE
    ("...registry_Hetzner Frame/icon.png", served once on 27 Jul as %20). When
    the sanitiser shipped, the live path became "...Hetzner-Frame" while the
    card still advertised the spaced one: 6 x 404 on the old path, 21 x 404 on
    the new one, until a re-upload re-froze it.
    """
    current = named_registry("Hetzner Frame")
    frozen_legacy = "/static/registry-cards/agentvault.com_registry_Hetzner Frame/icon.png"

    assert current not in frozen_legacy, "fixture no longer reproduces the drift"
    assert rcb.normalize_card_asset_url(frozen_legacy) == \
        f"/static/registry-cards/{current}/icon.png"


def test_percent_encoded_legacy_slug_is_repointed(named_registry):
    """The same row can hold the encoded form; it must heal too."""
    current = named_registry("Hetzner Frame")
    frozen = "/static/registry-cards/agentvault.com_registry_Hetzner%20Frame/icon.png"
    assert rcb.normalize_card_asset_url(frozen) == \
        f"/static/registry-cards/{current}/icon.png"


def test_rename_drift_is_repointed(named_registry):
    """A genuine rename drifts the same way and heals the same way."""
    frozen = f"/static/registry-cards/{named_registry('Frame-B')}/icon.jpg"
    current = named_registry("Texas")
    assert current not in frozen
    assert rcb.normalize_card_asset_url(frozen) == \
        f"/static/registry-cards/{current}/icon.jpg"


def test_trust_domain_change_is_repointed(monkeypatch, named_registry):
    """The slug also carries the trust domain — that can move too."""
    named_registry("Frame-C")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "old-domain.example")
    frozen = f"/static/registry-cards/{rcb.card_asset_slug()}/icon.png"
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "frame-c.theprotocol.cloud")
    current = rcb.card_asset_slug()
    assert current not in frozen
    assert rcb.normalize_card_asset_url(frozen).endswith(f"/{current}/icon.png")


def test_normalisation_is_idempotent(named_registry):
    slug = named_registry("Frame-B")
    url = f"/static/registry-cards/{slug}/icon.jpg"
    assert rcb.normalize_card_asset_url(url) == url
    assert rcb.normalize_card_asset_url(rcb.normalize_card_asset_url(url)) == url


def test_avatar_urls_normalise_too(named_registry):
    frozen = f"/static/registry-cards/{named_registry('Old Name')}/avatar.png"
    current = named_registry("New-Name")
    assert rcb.normalize_card_asset_url(frozen).endswith(f"/{current}/avatar.png")


@pytest.mark.parametrize("untouched", [
    None,
    "",
    "https://cdn.example.com/logo.png",          # external: never rewritten
    "http://evil.example/registry-cards/x/i.png",  # not our same-origin shape
    "/static/other-assets/icon.png",             # different static subtree
    "/static/registry-cards/slug/nested/icon.png",  # deeper than our shape
    "/static/registry-cards/onlyslug",           # no file segment
])
def test_leaves_everything_else_alone(untouched, named_registry):
    named_registry("Frame-C")
    assert rcb.normalize_card_asset_url(untouched) == untouched


def test_rewrites_only_the_slug_segment(named_registry):
    """The filename must survive: a .jpg upload stays a .jpg."""
    frozen = f"/static/registry-cards/{named_registry('A')}/icon.jpg"
    named_registry("B")
    assert rcb.normalize_card_asset_url(frozen).endswith("/icon.jpg")


def test_one_definition_of_the_slug():
    """Router and builder must not each own a copy — that is how they drifted."""
    from agentvault_registry.routers import admin_registry_card as arc
    assert arc._card_slug() == rcb.card_asset_slug()
