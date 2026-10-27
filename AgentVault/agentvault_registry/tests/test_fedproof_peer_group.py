"""§RESIDUES C1 (2026-09-13): a peer FRAME is grouped as a frame on stack-health and the public status page; a
FRESH_NETWORK_JSON entry without a group is `peer`, never `sandbox` (the flagship showed ASIA under `operator` and
ASIA's TEG/Event Store under `sandbox`)."""
import json

from agentvault_registry.core.peer_group import peer_group, tier_for_group, is_peer_group
from agentvault_registry.routers import public_status as ps


def test_peer_group_names_a_frame_and_an_operator():
    assert peer_group({"name": "asia", "peer_type": "frame"}) == "frame"
    assert peer_group({"name": "amsterdam", "peer_type": "cloud_operator"}) == "operator"
    assert peer_group({"name": "ghost", "peer_type": "discovered"}) == "operator"
    assert peer_group({"name": "bfs", "type": "frame"}) == "frame"
    assert peer_group({}) == "operator" and peer_group(None) == "operator"


def test_fresh_network_rows_default_to_peer_not_sandbox(monkeypatch):
    monkeypatch.setenv("FRESH_NETWORK_JSON", json.dumps([
        {"name": "ASIA", "slug": "asia", "console": "https://asia.example", "operators": ["shenzhen"]},
        {"name": "Labelled", "slug": "lab", "group": "sandbox"},
    ]))
    rows = ps._fresh_network_components()
    asia = [r for r in rows if r["name"].startswith("ASIA")]
    # E11: a frame's own rows are `frame`, its operators `operator` (the FE's vocabulary; "peer" was nobody's)
    assert [r["group"] for r in asia] == ["frame", "frame", "frame", "operator"], [r["group"] for r in asia]
    assert [r["job"] for r in asia] == ["asia-registry", "asia-event-store", "asia-teg", "shenzhen-registry"]
    lab = [r for r in rows if r["name"].startswith("Labelled")]
    assert lab and all(r["group"] == "sandbox" for r in lab)  # a declared group with no role is kept (the control)


def test_tier_follows_the_group_for_both_peer_kinds():
    # V0357 put a peer FRAME into the spine tier (the roll's spine gate read 4 of 3): the tier and the group are one rule
    assert tier_for_group("operator") == "federation" and tier_for_group("frame") == "federation"
    assert tier_for_group("core") == "spine" and tier_for_group(None) == "spine"
    assert is_peer_group("frame") and is_peer_group("operator") and not is_peer_group("core")


# ─── E11 (2026-09-13): the three halves measured on the flagship after the V0359 roll ────────────────────────────
from agentvault_registry.core.peer_group import collapse_twins, fresh_entry_groups, group_rank, identity_key

# EU's trusted-registries rail, as served 2026-09-13 04:5xZ (values shortened): the untyped card-name ghost "ASIA"
# beside the peer row "asia", and the untyped "eu" beside the typed "EU" (self).
_EU_RAIL = [
    {"name": "ASIA", "url": "https://asia.theprotocol.cloud", "public_url": "https://asia.theprotocol.cloud", "hop": 1, "peer_type": None, "trust_domain": "asia.theprotocol.cloud"},
    {"name": "amsterdam", "url": "https://amsterdam.op.theprotocol.cloud:8443", "public_url": "https://amsterdam.op.theprotocol.cloud", "hop": 1, "peer_type": "cloud_operator", "trust_domain": "eu.theprotocol.cloud"},
    {"name": "asia", "url": "https://asia.theprotocol.cloud:8443", "public_url": "https://asia.theprotocol.cloud", "hop": 1, "peer_type": "frame", "trust_domain": "asia.theprotocol.cloud"},
    {"name": "hochiminh", "url": "https://hochiminh.op.theprotocol.cloud:8443", "public_url": "https://hochiminh.op.theprotocol.cloud", "hop": 1, "peer_type": "discovered", "trust_domain": "asia.theprotocol.cloud"},
    {"name": "EU", "url": "https://eu.theprotocol.cloud:8443", "public_url": "https://eu.theprotocol.cloud", "hop": 2, "peer_type": "frame", "trust_domain": "eu.theprotocol.cloud"},
    {"name": "eu", "url": "https://eu.theprotocol.cloud:8443", "public_url": "https://eu.theprotocol.cloud", "hop": 2, "peer_type": None, "trust_domain": "eu.theprotocol.cloud"},
]


def test_identity_key_prefers_the_trust_domain_then_the_host_then_the_name():
    assert identity_key({"trust_domain": "ASIA.theprotocol.cloud"}) == "td:asia.theprotocol.cloud"   # no URL: the domain
    assert identity_key({"public_url": "https://asia.theprotocol.cloud:8443/x"}) == "host:asia.theprotocol.cloud"
    # the host wins over the domain: an operator shares its parent's trust domain and is NOT its parent's twin
    assert identity_key({"public_url": "https://amsterdam.op.theprotocol.cloud", "trust_domain": "eu.theprotocol.cloud"}) == "host:amsterdam.op.theprotocol.cloud"
    assert identity_key({"url": "asia.theprotocol.cloud"}) == "host:asia.theprotocol.cloud"
    assert identity_key({"name": " Ghost "}) == "name:ghost" and identity_key(None) == "name:"


def test_collapse_twins_drops_the_untyped_ghost_and_keeps_the_typed_row():
    # ⚠ the operators share their PARENT's trust domain (amsterdam: eu, hochiminh: asia), so a domain-first identity
    # folded every operator into its frame: the first run of this test caught exactly that. The identity is the HOST.
    out = collapse_twins(_EU_RAIL)
    names = [r["name"] for r in out]
    assert "ASIA" not in names and "eu" not in names, names          # the ghosts
    assert "asia" in names and "EU" in names, names                 # the typed rows
    assert "amsterdam" in names and "hochiminh" in names, names     # operators are not twins of their parent
    assert [r["name"] for r in collapse_twins([{"name": "lone", "peer_type": None, "trust_domain": "x.y"}])] == ["lone"]  # alone: kept
    two = [{"name": "a", "peer_type": "frame", "trust_domain": "x.y"}, {"name": "b", "peer_type": "frame", "trust_domain": "x.y"}]
    assert [r["name"] for r in collapse_twins(two)] == ["a"]         # two typed: the first
    assert collapse_twins([]) == [] and collapse_twins(None) == []


def test_fresh_entry_groups_follow_the_role_not_the_standup_label():
    # EU's env (2026-09-07 standup): role frame, group "sandbox" — the label that bled onto the public page
    assert fresh_entry_groups({"name": "ASIA", "slug": "asia", "role": "frame", "group": "sandbox"}) == ("frame", "operator")
    assert fresh_entry_groups({"name": "ASIA"}) == ("frame", "operator")
    assert fresh_entry_groups({"name": "Labelled", "group": "sandbox"}) == ("sandbox", "sandbox")   # no role: the label holds
    assert fresh_entry_groups(None) == ("frame", "operator")


def test_dedupe_prefers_a_known_group_over_a_label_whichever_came_first():
    assert group_rank("core") == 0 and group_rank("frame") == 1 == group_rank("operator")
    assert group_rank("sandbox") == 2 == group_rank("peer") == group_rank(None)
    stack = [{"name": "ASIA TEG", "job": "asia-teg", "group": "sandbox", "status": "healthy"}]
    synthetic = [{"name": "ASIA TEG", "job": "asia-teg", "group": "frame"}]
    out = ps.dedupe_by_job(stack + synthetic, "EU", "eu")
    assert [(x["name"], x["group"]) for x in out] == [("ASIA TEG", "frame")]
    # equal ranks: the first row (stack-health, with its live probe) still wins
    out = ps.dedupe_by_job([{"name": "asia", "job": "asia-registry", "group": "frame", "ms": 40},
                            {"name": "ASIA registry", "job": "asia-registry", "group": "frame"}], "EU", "eu")
    assert [x["name"] for x in out] == ["asia"]
