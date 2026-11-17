"""V0665 art (gwo_0915581a208ca772961c96c9; room seq 4063: the old ones stay): the registry's flare catalogs
are pinned exactly. The contributor track adds NEW badges, rings and titles in the console (components/contributor/, services/contributorTrack.ts);
SINCE the track's own order wired the unlock records (services/contributor_track) the new keys ARE in these catalogs, and in EARNED_ONLY; no OLD key is added,
removed or renamed. A change to a catalog is a decision, and this test is where it is made on purpose.
"""
from __future__ import annotations

from agentvault_registry.core import registry_identity as ri

FLARE_ENCIRCLEMENT_VARIANTS = (
    "alpine",
    "andes",
    "aurora",
    "bastille",
    "blackhole",
    "bullion-vault",
    "chad-frog",
    "chancellery",
    "circuit",
    "commons",
    "cross-shield",
    "crystal",
    "diamond-hands",
    "galaxy",
    "glacier",
    "goth",
    "halloween",
    "harvest",
    "inferno",
    "ink",
    "liberty",
    "lighthouse",
    "matrix",
    "ministry",
    "moonshot",
    "obsidian",
    "olive-branch",
    "outback",
    "phoenix",
    "pixel-shrine",
    "sakura",
    "sauron",
    "savanna",
    "solstice",
    "statehouse",
    "void",
    "yule",
)

FLARE_ENCIRCLEMENT_OVERLAYS = (
    "bleed",
    "breach",
    "brownout",
    "cascade",
    "crackle",
    "feedback",
    "freeze",
    "glitch",
    "karma-debt",
    "manifold",
    "panic-a",
    "panic-b",
    "panic-c",
    "redaction",
    "refract",
    "rugpull",
    "shilling",
    "spatter",
    "stampede",
    "stutter",
    "unravel",
)

FLARE_CORNER_VARIANTS = (
    "bullion-vault",
    "chancellery",
    "circuit",
    "crystal",
    "diamond-hands",
    "liberty",
    "matrix",
    "phoenix",
    "sauron",
)

NEW_RING_KEYS = ("lantern", "ember", "eye-of-the-senate", "event-horizon", "abyss", "supernova", "ouroboros", "merkle-ring", "lattice",
                 "quantum-halo", "watcher", "solar-flare", "singularity", "eclipse")
NEW_BADGE_KEYS = ("initiate", "architect-prime", "keystone", "founders-seal", "crown-of-the-commons", "gatekeeper", "ledger-seal", "quill",
                  "anvil", "lantern-key")


def test_the_old_encirclements_are_exactly_these():
    assert tuple(sorted(ri.FLARE_ENCIRCLEMENT_VARIANTS - ri.EARNED_ENCIRCLEMENTS)) == FLARE_ENCIRCLEMENT_VARIANTS


def test_the_old_overlays_are_exactly_these():
    assert tuple(sorted(ri.FLARE_ENCIRCLEMENT_OVERLAYS)) == FLARE_ENCIRCLEMENT_OVERLAYS


def test_the_old_corner_badges_are_exactly_these():
    assert tuple(sorted(ri.FLARE_CORNER_VARIANTS - ri.EARNED_CORNERS)) == FLARE_CORNER_VARIANTS


def test_a_new_ring_or_badge_is_in_the_catalog_and_earned_only():
    """V0665 the contributor track wired the unlock records: the new keys are in the catalogs (every card validator and the federation export
    accept them) and EARNED_ONLY (the shop never lists one, a customize call needs its unlock row)."""
    assert set(NEW_RING_KEYS) == set(ri.EARNED_ENCIRCLEMENTS)
    assert set(NEW_BADGE_KEYS) == set(ri.EARNED_CORNERS)
    for key in NEW_RING_KEYS:
        assert key in ri.FLARE_ENCIRCLEMENT_VARIANTS and ("encirclement", key) in ri.EARNED_ONLY, key
    for key in NEW_BADGE_KEYS:
        assert key in ri.FLARE_CORNER_VARIANTS and ("corner", key) in ri.EARNED_ONLY, key


def test_no_old_key_is_earned_only():
    for key in FLARE_ENCIRCLEMENT_VARIANTS:
        assert ("encirclement", key) not in ri.EARNED_ONLY, key
    for key in FLARE_CORNER_VARIANTS:
        assert ("corner", key) not in ri.EARNED_ONLY, key
