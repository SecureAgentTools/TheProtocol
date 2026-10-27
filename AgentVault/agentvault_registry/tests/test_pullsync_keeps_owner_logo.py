"""§MARKSURFACES (2026-09-10) — the pull-sync must not read an agent's SILENCE as a deletion
of the logo its owner set through the console.

His report: *"make so the set logo never gets lost on saving an upgraded agentcard when
updating the agentcard. this is a bug i noticed on agents same as registry cards had (from
fe update view for registry cards. for agents i am not sure how its set to the agent its not
on the card directly i think its in the metadata or whatever)."*  It is on the card, in
`card_data.iconUrl`, written by `views/MyAgents.vue::saveAgentAvatar`.

Reproduced before the fix, in the running V0301 image, against the real stored card of
`did:theprotocol:eu.theprotocol.cloud:76a8ed9b-…`:

    stored iconUrl : 'https://docs.theprotocol.cloud/assets/email/proto-mark-neural.png'
    merged iconUrl : None                       <- the upgrade dropped it
    drift entries  : ['iconUrl:removed']        <- and called it a removal
    registry-owned that survived: ['federation_metadata', 'flare']

`flare` survived because it is registry-owned. The logo did not, because `iconUrl` is a
legitimate A2A field an agent MAY publish — so it was classified agent-owned and any card
that did not repeat it was taken as an instruction to delete it.

THE CONTROLS ARE THE POINT. `test_agent_value_still_wins` and `test_a_real_removal_is_still_a_removal`
pass BOTH before and after the fix; only `test_the_logo_survives_an_upgraded_card` and
`test_the_kept_logo_is_not_reported_as_removed` fail before it. A suite where every test
changes direction with the fix cannot tell a fix from a rewrite.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.background_tasks import agent_card_pullsync as ps  # noqa: E402

LOGO = "https://docs.theprotocol.cloud/assets/email/proto-mark-neural.png"
AGENT_LOGO = "https://agent.example.test/its-own-logo.png"


def _stored(**over):
    """A stored card as the console leaves it: the agent's own fields plus the owner's logo."""
    card = {
        "name": "Shadowban Sheldon",
        "description": "Reads the feeds nobody reads.",
        "version": "1.0.0",
        "url": "https://eu.theprotocol.cloud/agents/shadowban-sheldon/a2a",
        "tags": ["moderation", "audit"],
        "iconUrl": LOGO,
        "flare": {"tier": "shadow_chancellor"},
        "federation_metadata": {},
        "last_pulled_at": "2026-09-09T00:00:00+00:00",
    }
    card.update(over)
    return card


def _upgraded(stored, **over):
    """What the agent serves at /.well-known/agent-card.json after an upgrade: its own fields,
    a bumped version, and — like essentially every agent card — no `iconUrl` at all."""
    fresh = {k: v for k, v in stored.items()
             if k not in ps._REGISTRY_OWNED_FIELDS and k != "iconUrl"}
    fresh["version"] = "1.1.0"
    fresh["description"] = stored["description"] + " Now with a version bump."
    fresh.update(over)
    return fresh


# ── the defect ──────────────────────────────────────────────────────────────────────
def test_the_logo_survives_an_upgraded_card():
    stored = _stored()
    merged, _ = ps._merge_pulled_card(stored, _upgraded(stored))
    assert merged.get("iconUrl") == LOGO, (
        "the owner-set logo was dropped by an agent card upgrade that never mentioned it"
    )
    # and the upgrade itself still landed
    assert merged["version"] == "1.1.0"
    assert merged["description"].endswith("Now with a version bump.")


def test_the_kept_logo_is_not_reported_as_removed():
    stored = _stored()
    _, drifted = ps._merge_pulled_card(stored, _upgraded(stored))
    assert not [d for d in drifted if d.startswith("iconUrl")], (
        f"a field we deliberately kept must not be reported as drift: {drifted}"
    )


def test_an_empty_string_from_the_agent_is_silence_not_a_deletion():
    """A card that ships `iconUrl: ""` (or null) is saying nothing, not 'delete it'. Clearing
    the logo is done from the console, whose PUT sends an explicit null the CRUD honours."""
    stored = _stored()
    for blank in ("", "   ", None):
        merged, _ = ps._merge_pulled_card(stored, _upgraded(stored, iconUrl=blank))
        assert merged.get("iconUrl") == LOGO, f"blank {blank!r} was treated as a deletion"


def test_the_snake_case_spelling_is_protected_too():
    """A card written before `canonicalize_card_data` ran can hold `icon_url`. A rule that
    protects one spelling of a two-spelling field protects nothing."""
    stored = _stored()
    del stored["iconUrl"]
    stored["icon_url"] = LOGO
    fresh = {k: v for k, v in stored.items()
             if k not in ps._REGISTRY_OWNED_FIELDS and k != "icon_url"}
    merged, _ = ps._merge_pulled_card(stored, fresh)
    assert merged.get("icon_url") == LOGO


# ── controls: these pass BEFORE the fix too ─────────────────────────────────────────
def test_agent_value_still_wins():
    """CONTROL. The card is the agent's. When the agent publishes its own icon, that is the
    icon — the preservation rule must not pin an owner's older choice over it."""
    stored = _stored()
    merged, _ = ps._merge_pulled_card(stored, _upgraded(stored, iconUrl=AGENT_LOGO))
    assert merged.get("iconUrl") == AGENT_LOGO


def test_a_real_removal_is_still_a_removal():
    """CONTROL. Only the owner-set fields are protected. Everything else the agent stops
    publishing is still dropped and still reported."""
    stored = _stored(customField={"kept": "by nobody"})
    fresh = _upgraded(stored)
    fresh.pop("customField", None)
    merged, drifted = ps._merge_pulled_card(stored, fresh)
    assert "customField" not in merged
    assert "customField:removed" in drifted


def test_registry_owned_fields_are_untouched():
    """CONTROL. `flare` and `federation_metadata` survived before this change and must keep
    surviving — the fix adds a set, it does not re-plumb the ones that worked."""
    stored = _stored()
    merged, _ = ps._merge_pulled_card(stored, _upgraded(stored))
    assert merged["flare"] == {"tier": "shadow_chancellor"}
    assert merged["federation_metadata"] == {}
    assert merged["last_pulled_at"] == "2026-09-09T00:00:00+00:00"


def test_no_logo_anywhere_stays_no_logo():
    """CONTROL. The rule restores a value; it never invents one."""
    stored = _stored()
    del stored["iconUrl"]
    merged, _ = ps._merge_pulled_card(stored, _upgraded(stored))
    assert not merged.get("iconUrl")
    assert not merged.get("icon_url")
