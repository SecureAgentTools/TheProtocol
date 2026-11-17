"""V0665 the contributor track (order gwo_5e0701efdef9d3989491bc37; room seq 4063, 4070, 4081; design
sessionlogs2026/DESIGN_2026-11-14_CONTRIBUTOR_TRACK.md): unlock records for the new badges, rings and titles, earned from governed-code
events only.

THE RULES, each one a test here:
  - earned only: ONE writer of the unlock table (services/contributor_track), nothing else inserts, no route grants, no shop sells;
  - no value moves (no TEG call, no emit in the module);
  - the old badges and rings stay exactly as they are (tests/test_flare_catalog_pinned_v0665.py pins them);
  - COMMANDER is one of one: the commander flare tier only, no unlock row;
  - a condition with no signal yet is shown as "comes later", never invented.
Red before this order: there was no module, no table, no title column.
"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import pathlib
import re

import pytest

from agentvault_registry.core import registry_identity as ri
from agentvault_registry.services import contributor_track as ct

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _change(cid, dev, *, state="proposed", sensitive=False, paths=("views/A.vue",), merged_at=None, passed=False, vf=0, va=0):
    return {"id": cid, "proposer_developer_id": dev, "state": state, "sensitive": sensitive, "paths": list(paths),
            "merged_at": merged_at, "passed": passed, "votes_for": vf, "votes_against": va}


def _month(y, m, d=3):
    return dt.datetime(y, m, d, 9, 0, tzinfo=UTC)


def _facts(changes=(), reviews=(), ballots=()):
    return ct.facts_from(list(changes), list(reviews), list(ballots))


def _keys(facts, wins=None):
    return {(i.kind, i.key) for i in ct.earned(facts, wins or {})}


# --- the catalogs ----------------------------------------------------------------------------------------------------

def test_every_item_of_the_track_is_a_key_of_the_registry_catalogs():
    for i in ct.TRACK:
        if i.kind == "title":
            assert i.key in ri.FLARE_TITLES, i.key
        elif i.kind == "corner":
            assert i.key in ri.FLARE_CORNER_VARIANTS, i.key
        elif i.kind == "encirclement":
            assert i.key in ri.FLARE_ENCIRCLEMENT_VARIANTS, i.key
        else:
            raise AssertionError(i.kind)


def test_the_earned_only_set_is_exactly_the_new_keys_and_no_old_key_is_in_it():
    new_rings = {"lantern", "ember", "eye-of-the-senate", "event-horizon", "abyss", "supernova", "ouroboros", "merkle-ring", "lattice",
                 "quantum-halo", "watcher", "solar-flare", "singularity", "eclipse"}
    new_badges = {"initiate", "architect-prime", "keystone", "founders-seal", "crown-of-the-commons", "gatekeeper", "ledger-seal", "quill",
                  "anvil", "lantern-key"}
    assert ri.EARNED_ENCIRCLEMENTS == frozenset(new_rings)
    assert ri.EARNED_CORNERS == frozenset(new_badges)
    assert ri.EARNED_ONLY == frozenset(("encirclement", k) for k in new_rings) | frozenset(("corner", k) for k in new_badges) | \
        frozenset(("title", k) for k in ri.FLARE_TITLES)
    # an old key is never earned-only: the old badges and rings stay as they are, bought or granted as before
    assert not (ri.EARNED_ENCIRCLEMENTS & {"sauron", "void", "blackhole", "phoenix", "inferno"})


def test_the_commander_plate_is_not_a_title_anyone_can_earn():
    assert "commander" not in ri.FLARE_TITLES
    assert not any(i.key == "commander" for i in ct.TRACK)


def test_the_four_extra_titles_ship_with_their_conditions():
    for k, cond in (("dead-letter-whisperer", "stalled"), ("rollback-ready", "sensitive_tested"), ("quorum-maker", "quorum_ballots"), ("clean-checkout", "clean_first")):
        assert k in ri.FLARE_TITLES
        it = next(i for i in ct.TRACK if i.key == k)
        assert it.cond == cond and not it.later and it.sentence


PASS_LADDER = [   # (tier, key): ONE rising ladder of 40 tiers (the Commander's word on the preview, room seq 4592; session-lead seq 4594 and 4607)
    (1, "initiate"), (2, "lantern"), (3, "architect-prime"), (3, "first-light"), (4, "ember"), (5, "lantern-key"), (6, "quantum-halo"), (7, "keystone"), (7, "patchwright"),
    (8, "quill"), (9, "ballot-bearer"), (10, "founders-seal"), (10, "second-pair-of-eyes"), (11, "lattice"), (12, "mutually-trusted"), (13, "gatekeeper"), (14, "eye-of-the-senate"),
    (15, "solar-flare"), (16, "off-by-one"), (17, "ouroboros"), (18, "anvil"), (19, "ledger-seal"), (20, "clean-checkout"), (21, "dead-letter-whisperer"), (22, "exactly-once"),
    (23, "bug-slayer"), (24, "it-works-on-my-frame"), (25, "watcher"), (26, "senate-scribe"), (27, "quorum-maker"), (28, "keeper-of-delta-zero"), (29, "event-horizon"),
    (30, "abyss"), (31, "rollback-ready"), (32, "eclipse"), (33, "merkle-ring"), (34, "beast-tamer"), (35, "the-eye-sees-all"), (36, "architect-of-the-beast"), (37, "singularity"),
    (38, "event-horizon"), (39, "crown-of-the-commons"), (39, "supernova"), (40, "founder-of-the-commons"),
]
LUCK = ("off-by-one", "ledger-seal", "dead-letter-whisperer", "it-works-on-my-frame")


def test_the_pass_is_one_rising_ladder_of_forty_tiers_in_this_order():
    assert [(i.tier, i.key) for i in ct.TRACK] == PASS_LADDER
    assert sorted({i.tier for i in ct.TRACK}) == list(range(1, 41))
    assert len(ct.TRACK) == 44


def test_items_with_the_same_condition_share_a_tier():
    for pair in (("architect-prime", "first-light"), ("keystone", "patchwright"), ("founders-seal", "second-pair-of-eyes"), ("crown-of-the-commons", "supernova")):
        rows = [i for i in ct.TRACK if i.key in pair]
        assert len(rows) == 2 and rows[0].tier == rows[1].tier and (rows[0].cond, rows[0].n) == (rows[1].cond, rows[1].n)


def test_the_season_win_is_near_the_end_and_the_founder_is_last():
    assert max(i.tier for i in ct.TRACK) == 40 and [i.key for i in ct.TRACK if i.tier == 40] == ["founder-of-the-commons"]
    assert {i.key for i in ct.TRACK if i.tier == 39} == {"crown-of-the-commons", "supernova"}


def test_nothing_restarts_at_easy_after_a_harder_item_by_the_count_it_wants():
    # the ladder rises by effort: a count-of-merged chain never goes down, and a ballot or review count never goes down either
    for cond in ("merged", "ballots", "reviews"):
        ns = [i.n for i in ct.TRACK if i.cond == cond]
        assert ns == sorted(ns), (cond, ns)


def test_the_luck_items_come_after_effort_items_of_similar_weight():
    tier = {i.key: i.tier for i in ct.TRACK}
    assert min(tier[k] for k in LUCK) >= 16                                        # not at the bottom of the pass: "Next on the pass" is not stuck on luck early
    assert tier["off-by-one"] > tier["solar-flare"] and tier["ledger-seal"] > tier["anvil"]
    assert tier["dead-letter-whisperer"] > tier["clean-checkout"] and tier["it-works-on-my-frame"] > tier["bug-slayer"]


def test_the_whole_track_is_earnable_on_the_pass_nothing_waits_and_nothing_is_off_to_the_side():
    assert all(i.tier is not None for i in ct.TRACK)
    assert not [i.key for i in ct.TRACK if i.later or i.side or i.cond == "later"]
    assert {(i.kind, i.key) for i in ct.TRACK} == {("encirclement", k) for k in ri.EARNED_ENCIRCLEMENTS} | {("corner", k) for k in ri.EARNED_CORNERS} | {("title", k) for k in ri.FLARE_TITLES}
    assert len(ct.TRACK) == 44                                                                # the seeded 44: no key is new, so the seed stays as it is
    for i in ct.TRACK:
        assert i.sentence.strip() and i.cond


# --- the conditions the data decides today ----------------------------------------------------------------------------

def test_nothing_unlocks_without_an_event():
    assert _keys(_facts()) == set()


def test_the_first_proposal_unlocks_tier_one_only():
    f = _facts([_change("a", 1)])
    assert _keys(f) == {("corner", "initiate")}
    assert _keys(f, wins=None) == {("corner", "initiate")}


def test_a_first_review_of_someone_elses_change_unlocks_the_lantern_and_a_review_of_your_own_does_not():
    other = _facts([_change("a", 2)], [{"change_id": "a", "reviewer_developer_id": 1, "verdict": "approve"}])
    assert ("encirclement", "lantern") in _keys(other)
    own = _facts([_change("a", 1)], [{"change_id": "a", "reviewer_developer_id": 1, "verdict": "approve"}])
    assert ("encirclement", "lantern") not in _keys(own)


def test_the_first_merge_unlocks_architect_prime_and_first_light():
    f = _facts([_change("a", 1, state="merged", merged_at=_month(2026, 11))])
    got = _keys(f)
    assert ("corner", "architect-prime") in got and ("title", "first-light") in got
    assert ("corner", "keystone") not in got


def test_five_merged_changes_unlock_keystone_and_patchwright():
    changes = [_change(f"c{i}", 1, state="merged", merged_at=_month(2026, 11, i + 1)) for i in range(5)]
    got = _keys(_facts(changes))
    assert ("corner", "keystone") in got and ("title", "patchwright") in got
    got4 = _keys(_facts(changes[:4]))
    assert ("corner", "keystone") not in got4 and ("title", "patchwright") not in got4


def test_three_ballots_on_code_changes_unlock_ember_and_ten_the_ballot_bearer():
    three = _facts(ballots=[{"voter_developer_id": 5, "proposal_id": i} for i in range(3)])
    assert ("encirclement", "ember") in _keys(three) and ("title", "ballot-bearer") not in _keys(three)
    ten = _facts(ballots=[{"voter_developer_id": 5, "proposal_id": i} for i in range(10)])
    assert ("title", "ballot-bearer") in _keys(ten)


def test_a_ballot_counts_once_per_proposal():
    f = _facts(ballots=[{"voter_developer_id": 5, "proposal_id": 1}] * 9)
    assert f[5].ballots == 1


def test_a_sensitive_change_passed_by_ballot_unlocks_the_eye_of_the_senate():
    f = _facts([_change("a", 1, sensitive=True, passed=True, state="passed")])
    assert ("encirclement", "eye-of-the-senate") in _keys(f)
    plain = _facts([_change("a", 1, sensitive=False, passed=True, state="passed")])
    assert ("encirclement", "eye-of-the-senate") not in _keys(plain)
    open_ = _facts([_change("a", 1, sensitive=True, passed=False, state="balloting")])
    assert ("encirclement", "eye-of-the-senate") not in _keys(open_)


def test_ten_reviews_unlock_the_seal_and_second_pair_of_eyes():
    changes = [_change(f"c{i}", 2) for i in range(10)]
    reviews = [{"change_id": f"c{i}", "reviewer_developer_id": 1, "verdict": "approve"} for i in range(10)]
    got = _keys(_facts(changes, reviews))
    assert ("corner", "founders-seal") in got and ("title", "second-pair-of-eyes") in got
    got9 = _keys(_facts(changes[:9], reviews[:9]))
    assert ("corner", "founders-seal") not in got9


def test_a_review_counts_once_per_change_and_never_for_your_own_change():
    changes = [_change("c1", 2), _change("mine", 1)]
    reviews = [{"change_id": "c1", "reviewer_developer_id": 1, "verdict": "changes"},
               {"change_id": "c1", "reviewer_developer_id": 1, "verdict": "approve"},
               {"change_id": "mine", "reviewer_developer_id": 1, "verdict": "approve"}]
    assert _facts(changes, reviews)[1].reviews == 1


def test_twenty_five_merged_unlock_the_event_horizon_ring_and_a_hundred_the_title():
    c25 = [_change(f"c{i}", 1, state="merged", merged_at=_month(2026, 1 + i % 10, 1 + i // 10)) for i in range(25)]
    got = _keys(_facts(c25))
    assert ("encirclement", "event-horizon") in got and ("title", "event-horizon") not in got
    c100 = [_change(f"c{i}", 1, state="merged", merged_at=_month(2026, 1 + i % 10, 1 + i // 10)) for i in range(100)]
    assert ("title", "event-horizon") in _keys(_facts(c100))


def test_twelve_different_months_unlock_the_abyss_and_eleven_do_not():
    twelve = [_change(f"c{m}", 1, state="merged", merged_at=_month(2025 if m > 9 else 2026, 1 + (m - 1) % 12)) for m in range(1, 13)]
    assert ("encirclement", "abyss") in _keys(_facts(twelve))
    assert ("encirclement", "abyss") not in _keys(_facts(twelve[:11]))
    same_month_many = [_change(f"c{i}", 1, state="merged", merged_at=_month(2026, 11, 1 + i)) for i in range(20)]
    assert ("encirclement", "abyss") not in _keys(_facts(same_month_many))


def test_months_are_utc_calendar_months():
    f = _facts([_change("a", 1, state="merged", merged_at=dt.datetime(2026, 11, 30, 23, 59, tzinfo=UTC)),
                _change("b", 1, state="merged", merged_at=dt.datetime(2026, 12, 1, 0, 0, tzinfo=UTC))])
    assert f[1].merge_months == {"2026-11", "2026-12"}


def test_senate_scribe_needs_twenty_five_ballots_and_ten_proposals():
    ballots = [{"voter_developer_id": 1, "proposal_id": i} for i in range(25)]
    ten = [_change(f"c{i}", 1) for i in range(10)]
    assert ("title", "senate-scribe") in _keys(_facts(ten, ballots=ballots))
    assert ("title", "senate-scribe") not in _keys(_facts(ten[:9], ballots=ballots))
    assert ("title", "senate-scribe") not in _keys(_facts(ten, ballots=ballots[:24]))


def test_beast_tamer_needs_a_sensitive_pass_and_twenty_five_merged():
    changes = [_change(f"c{i}", 1, state="merged", merged_at=_month(2026, 1 + i % 10, 1 + i // 10)) for i in range(25)]
    changes[0] = _change("c0", 1, state="merged", sensitive=True, passed=True, merged_at=_month(2026, 1))
    assert ("title", "beast-tamer") in _keys(_facts(changes))
    assert ("title", "beast-tamer") not in _keys(_facts(changes[1:]))


def test_architect_of_the_beast_is_fifty_merged():
    c = [_change(f"c{i}", 1, state="merged", merged_at=_month(2026, 1 + i % 10, 1 + i // 10)) for i in range(50)]
    assert ("title", "architect-of-the-beast") in _keys(_facts(c))
    assert ("title", "architect-of-the-beast") not in _keys(_facts(c[:49]))


def test_off_by_one_is_a_ballot_passed_by_a_single_vote():
    one = _facts([_change("a", 1, state="passed", passed=True, vf=4, va=3)])
    assert ("title", "off-by-one") in _keys(one)
    two = _facts([_change("a", 1, state="passed", passed=True, vf=5, va=3)])
    assert ("title", "off-by-one") not in _keys(two)
    failed = _facts([_change("a", 1, state="failed", passed=False, vf=4, va=3)])
    assert ("title", "off-by-one") not in _keys(failed)


# --- the six conditions that used to wait now read the governed-code tables -------------------------------------------------------

def _rv(cid, dev, verdict="approve", commit="c1"):
    return {"change_id": cid, "reviewer_developer_id": dev, "verdict": verdict, "commit": commit}


def _mc(cid, dev, month=11, day=3, title="A clearer page", commit="c1", **kw):
    return {**_merged(cid, dev, month, day, **kw), "title": title, "commit": commit, "merged_commit": commit}


def test_exactly_once_is_ten_merged_changes_that_exactly_one_reviewer_approved():
    ch = [_mc(f"a{i}", 1) for i in range(10)]
    one = [_rv(f"a{i}", 2) for i in range(10)]
    assert ("title", "exactly-once") in _keys(_facts(ch, one))
    assert ("title", "exactly-once") not in _keys(_facts(ch[:9], one[:9]))
    two = one + [_rv(f"a{i}", 3) for i in range(10)]                                          # a second approver on each: not exactly once
    assert ("title", "exactly-once") not in _keys(_facts(ch, two))
    asked = [_rv(f"a{i}", 2, "changes") for i in range(10)]                                   # a reviewer's latest word counts: not an approval
    assert ("title", "exactly-once") not in _keys(_facts(ch, asked))


def test_mutually_trusted_is_five_people_who_reviewed_yours_and_five_whose_changes_you_reviewed():
    mine = [_mc("a1", 1)]
    theirs = [_mc(f"p{i}", 11 + i) for i in range(5)]
    by_five = [_rv("a1", 2 + i) for i in range(5)]                                      # five different people review my change
    of_five = [_rv(f"p{i}", 1) for i in range(5)]                                       # and I review five different people's changes
    assert ("title", "mutually-trusted") in _keys(_facts(mine + theirs, by_five + of_five))
    assert ("title", "mutually-trusted") not in _keys(_facts(mine + theirs, by_five + of_five[:-1]))   # four reviewed: not enough
    assert ("title", "mutually-trusted") not in _keys(_facts(mine + theirs, by_five[:-1] + of_five))   # reviewed by four: not enough
    assert ("title", "mutually-trusted") not in _keys(_facts(mine + theirs, [_rv("a1", 2)] * 5 + of_five))   # one reviewer five times is one person
    assert ("title", "mutually-trusted") not in _keys(_facts([_mc("s", 1)], [_rv("s", 1)] * 5))       # reviewing your own change is not trust


def test_the_five_and_five_needs_no_pairs_so_there_is_nothing_to_trade():
    src = open(ct.__file__).read()
    assert "pairs.add" not in src and "mutual_count" not in src and "(b_, a_) in pairs" not in src    # the review-trading incentive of the three-pairs reading is gone


def test_keeper_of_delta_zero_is_twenty_merged_changes_no_reviewer_had_to_ask_changes_on():
    ch = [_mc(f"k{i}", 1) for i in range(20)]
    ok = [_rv(f"k{i}", 2) for i in range(20)]
    assert ("title", "keeper-of-delta-zero") in _keys(_facts(ch, ok))
    assert ("title", "keeper-of-delta-zero") not in _keys(_facts(ch[:19], ok[:19]))
    asked = ok[:19] + [_rv("k19", 2, "changes", "c0"), _rv("k19", 2)]                           # one asked first, then approved: it does not count
    assert ("title", "keeper-of-delta-zero") not in _keys(_facts(ch, asked))


def test_bug_slayer_is_ten_merged_changes_whose_title_says_fix():
    titles = ["Fix the order page", "fixes the label", "Fixed overflow", "bugfix: the pill", "BUG: the tab", "  Fix  spacing", "fix", "Fix a", "Fixes b", "Fixed c"]
    ch = [_mc(f"f{i}", 1, title=t) for i, t in enumerate(titles)]
    assert ("title", "bug-slayer") in _keys(_facts(ch))
    assert ("title", "bug-slayer") not in _keys(_facts(ch[:9]))
    other = [_mc(f"g{i}", 1, title=t) for i, t in enumerate(["Fixture loader", "Prefix the name", "A clearer fix", "Hotfix", "Suffix"] * 2)]
    assert ("title", "bug-slayer") not in _keys(_facts(other))                                # a word that only starts or contains fix is not a fix


def test_the_eye_sees_all_is_fifty_reviews_each_on_the_commit_that_was_finally_merged():
    ch = [_mc(f"e{i}", 1) for i in range(50)]
    rv = [_rv(f"e{i}", 3) for i in range(50)]
    assert ("title", "the-eye-sees-all") in _keys(_facts(ch, rv))
    assert ("title", "the-eye-sees-all") not in _keys(_facts(ch[:49], rv[:49]))
    stale = rv[:49] + [_rv("e49", 3, commit="old")]                                           # a review of an earlier commit is not the final one
    assert ("title", "the-eye-sees-all") not in _keys(_facts(ch, stale))
    twice = rv[:49] + [_rv("e48", 3)]                                                         # once per change
    assert ("title", "the-eye-sees-all") not in _keys(_facts(ch, twice))


def test_it_works_on_my_frame_is_a_change_merged_after_one_of_yours_was_refused():
    early, late = _month(2026, 8, 1), _month(2026, 9, 1)
    for state in ("failed", "vetoed", "withdrawn"):
        refused = {**_change("r", 1, state=state), "created_at": early}
        merged = {**_mc("m", 1), "created_at": late}
        assert ("title", "it-works-on-my-frame") in _keys(_facts([refused, merged])), state
    refused = {**_change("r", 1, state="failed"), "created_at": late}
    merged = {**_mc("m", 1), "created_at": early}
    assert ("title", "it-works-on-my-frame") not in _keys(_facts([refused, merged]))          # the refusal came after the merge: not a comeback
    assert ("title", "it-works-on-my-frame") not in _keys(_facts([{**_change("r", 1, state="failed"), "created_at": early}]))      # no merge at all


def test_the_loader_reads_the_title_the_fix_title_needs():
    txt = (SRC / "services" / "contributor_track.py").read_text()
    load = txt.split("async def load(", 1)[1].split("async def season_counts", 1)[0]
    assert '"title": c.title' in load


LADDER = {
    "solar-flare": "merged", "watcher": "reviews", "merkle-ring": "ballots", "ouroboros": "streak", "lattice": "areas", "quantum-halo": "quantum", "singularity": "merged",
    "eclipse": "sensitive_passed", "quill": "docs", "anvil": "tests", "gatekeeper": "asked_changes", "lantern-key": "lantern_key", "ledger-seal": "unanimous",
}


def test_the_thirteen_other_items_each_have_their_ladder_condition_and_none_is_later():
    for k, cond in LADDER.items():
        it = next(i for i in ct.TRACK if i.key == k)
        assert it.cond == cond and not it.later and it.sentence


def _merged(cid, dev, month, day=3, paths=("views/A.vue",), sensitive=False, passed=False, **kw):
    return _change(cid, dev, state="merged", merged_at=_month(2026, month, day), paths=paths, sensitive=sensitive, passed=passed, **kw)


def test_solar_flare_ten_merged_and_singularity_seventy_five():
    ten = [_merged(f"c{i}", 1, 1 + i % 10, 1 + i // 10) for i in range(10)]
    assert ("encirclement", "solar-flare") in _keys(_facts(ten)) and ("encirclement", "solar-flare") not in _keys(_facts(ten[:9]))
    many = [_merged(f"c{i}", 1, 1 + i % 10, 1 + i // 10) for i in range(75)]
    assert ("encirclement", "singularity") in _keys(_facts(many)) and ("encirclement", "singularity") not in _keys(_facts(many[:74]))


def test_watcher_is_twenty_five_reviews_of_other_peoples_changes():
    changes = [_change(f"c{i}", 2) for i in range(25)]
    reviews = [{"change_id": f"c{i}", "reviewer_developer_id": 1, "verdict": "approve"} for i in range(25)]
    assert ("encirclement", "watcher") in _keys(_facts(changes, reviews)) and ("encirclement", "watcher") not in _keys(_facts(changes[:24], reviews[:24]))


def test_merkle_ring_is_fifty_ballots():
    b = [{"voter_developer_id": 1, "proposal_id": i} for i in range(50)]
    assert ("encirclement", "merkle-ring") in _keys(_facts(ballots=b)) and ("encirclement", "merkle-ring") not in _keys(_facts(ballots=b[:49]))


def test_ouroboros_is_three_months_in_a_row_and_a_gap_breaks_it():
    run = [_merged("a", 1, 3), _merged("b", 1, 4), _merged("c", 1, 5)]
    assert ("encirclement", "ouroboros") in _keys(_facts(run))
    gap = [_merged("a", 1, 3), _merged("b", 1, 4), _merged("c", 1, 6)]
    assert ("encirclement", "ouroboros") not in _keys(_facts(gap))
    year = [_change("a", 1, state="merged", merged_at=_month(2025, 11)), _change("b", 1, state="merged", merged_at=_month(2025, 12)), _change("c", 1, state="merged", merged_at=_month(2026, 1))]
    assert ("encirclement", "ouroboros") in _keys(_facts(year))                        # December to January is consecutive


def test_lattice_is_five_areas_of_the_tree():
    PRE = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/"
    areas = ["views/A.vue", "components/B.vue", "stores/c.ts", "services/d.ts", "assets/docs/e.md"]
    ch = [_merged(f"c{i}", 1, 1 + i, paths=(PRE + p,)) for i, p in enumerate(areas)]
    assert ("encirclement", "lattice") in _keys(_facts(ch)) and ("encirclement", "lattice") not in _keys(_facts(ch[:4]))
    assert _facts(ch)[1].areas == {"views", "components", "stores", "services", "docs"}


def test_quantum_halo_is_a_merged_change_to_a_quantum_page():
    assert ("encirclement", "quantum-halo") in _keys(_facts([_merged("a", 1, 3, paths=("views/QuantumWorkloads.vue",))]))
    assert ("encirclement", "quantum-halo") in _keys(_facts([_merged("a", 1, 3, paths=("assets/docs/quantum-intro.md",))]))
    assert ("encirclement", "quantum-halo") not in _keys(_facts([_merged("a", 1, 3, paths=("views/A.vue",))]))


def test_eclipse_is_five_sensitive_changes_passed_by_ballot():
    five = [_merged(f"c{i}", 1, 1 + i, sensitive=True, passed=True) for i in range(5)]
    assert ("encirclement", "eclipse") in _keys(_facts(five)) and ("encirclement", "eclipse") not in _keys(_facts(five[:4]))


def test_quill_is_five_merged_documentation_changes():
    d = [_merged(f"c{i}", 1, 1 + i, paths=("assets/docs/p.md",)) for i in range(5)]
    assert ("corner", "quill") in _keys(_facts(d)) and ("corner", "quill") not in _keys(_facts(d[:4]))
    assert ("corner", "quill") not in _keys(_facts([_merged(f"c{i}", 1, 1 + i) for i in range(5)]))


def test_anvil_is_ten_merged_changes_that_carry_their_own_tests():
    t = [_merged(f"c{i}", 1, 1 + i % 10, 1 + i // 10, paths=("views/A.vue", "views/A.test.ts")) for i in range(10)]
    assert ("corner", "anvil") in _keys(_facts(t)) and ("corner", "anvil") not in _keys(_facts(t[:9]))
    py = [_merged(f"c{i}", 1, 1 + i % 10, 1 + i // 10, paths=("tests/test_a.py",)) for i in range(10)]
    assert ("corner", "anvil") in _keys(_facts(py))


def test_gatekeeper_is_ten_changes_where_the_reviewer_asked_for_changes():
    ch = [_change(f"c{i}", 2) for i in range(10)]
    rv = [{"change_id": f"c{i}", "reviewer_developer_id": 1, "verdict": "changes", "commit": "a"} for i in range(10)]
    assert ("corner", "gatekeeper") in _keys(_facts(ch, rv)) and ("corner", "gatekeeper") not in _keys(_facts(ch[:9], rv[:9]))
    twice = [{"change_id": "c0", "reviewer_developer_id": 1, "verdict": "changes", "commit": c} for c in "abcdefghijk"]
    assert _facts(ch, twice)[1].asked_changes == 1                                    # one change, however many times it was asked


def test_lantern_key_is_changes_asked_then_a_different_commit_approved():
    ch = [_change("c", 2)]
    ok = [{"change_id": "c", "reviewer_developer_id": 1, "verdict": "changes", "commit": "a"}, {"change_id": "c", "reviewer_developer_id": 1, "verdict": "approve", "commit": "b"}]
    assert ("corner", "lantern-key") in _keys(_facts(ch, ok))
    same = [{"change_id": "c", "reviewer_developer_id": 1, "verdict": "changes", "commit": "a"}, {"change_id": "c", "reviewer_developer_id": 1, "verdict": "approve", "commit": "a"}]
    assert ("corner", "lantern-key") not in _keys(_facts(ch, same))
    backwards = [ok[1], ok[0]]
    assert ("corner", "lantern-key") not in _keys(_facts(ch, backwards))


def test_ledger_seal_is_a_unanimous_pass_with_at_least_five_votes():
    assert ("corner", "ledger-seal") in _keys(_facts([_change("a", 1, state="passed", passed=True, vf=5, va=0)]))
    assert ("corner", "ledger-seal") not in _keys(_facts([_change("a", 1, state="passed", passed=True, vf=4, va=0)]))
    assert ("corner", "ledger-seal") not in _keys(_facts([_change("a", 1, state="passed", passed=True, vf=9, va=1)]))


# --- seasons --------------------------------------------------------------------------------------------------------------

def test_a_quarter_is_won_by_the_most_merged_changes_and_only_once_it_is_closed():
    q3 = [_change(f"a{i}", 1, state="merged", merged_at=_month(2026, 7, 1 + i)) for i in range(3)] + \
         [_change("b", 2, state="merged", merged_at=_month(2026, 8, 5))]
    assert ct.season_wins(q3, NOW) == {1: ["2026Q3"]}
    q4_open = [_change("a", 1, state="merged", merged_at=_month(2026, 11, 2))]
    assert ct.season_wins(q4_open, NOW) == {}                                          # Q4 2026 is still running


def test_a_tie_goes_to_the_earlier_last_merge():
    ch = [_change("a1", 1, state="merged", merged_at=_month(2026, 7, 1)), _change("a2", 1, state="merged", merged_at=_month(2026, 7, 5)),
          _change("a3", 1, state="merged", merged_at=_month(2026, 9, 20)),
          _change("b1", 2, state="merged", merged_at=_month(2026, 7, 2)), _change("b2", 2, state="merged", merged_at=_month(2026, 7, 6)),
          _change("b3", 2, state="merged", merged_at=_month(2026, 8, 20))]
    assert ct.season_wins(ch, NOW) == {2: ["2026Q3"]}


# --- the season floor (session-lead's decision, seq 4360): a quarter is not won by one lonely change ----------------

def _q(dev, n, month=7, prefix=None):
    return [_change(f"{prefix or dev}{i}", dev, state="merged", merged_at=_month(2026, month, 1 + i)) for i in range(n)]


def test_a_season_needs_three_merged_changes_from_the_winner():
    assert ct.season_wins(_q(1, 2) + _q(2, 1), NOW) == {}                              # two merged changes is not enough
    assert ct.season_wins(_q(1, 3) + _q(2, 1), NOW) == {1: ["2026Q3"]}


def test_a_season_needs_two_people_who_merged_something():
    assert ct.season_wins(_q(1, 5), NOW) == {}                                         # alone in the quarter: nobody wins it
    assert ct.season_wins(_q(1, 5) + _q(2, 1), NOW) == {1: ["2026Q3"]}


def test_a_quarter_nobody_wins_does_not_stop_the_next_one_being_won():
    ch = _q(1, 2) + _q(2, 1) + _q(3, 3, month=10, prefix="x") + _q(4, 1, month=10, prefix="y")      # Q3 fails the floor, Q4 is open
    assert ct.season_wins(ch, NOW) == {}                                               # NOW is in Q4: it is not closed yet
    later = dt.datetime(2027, 1, 5, tzinfo=UTC)
    assert ct.season_wins(ch, later) == {3: ["2026Q4"]}


def test_the_floor_is_named_in_the_public_words_of_the_track():
    words = ct.public_track()["seasons"]
    assert "three" in words and "two people" in words


def test_a_closed_quarters_winner_unlocks_tier_ten_and_two_unlock_the_founder_title():
    one = _facts(wins := [])
    wins = {1: ["2026Q2"]}
    f = _facts([_change("a", 1, state="merged", merged_at=_month(2026, 5))])
    assert {("corner", "crown-of-the-commons"), ("encirclement", "supernova")} <= _keys(f, wins=wins)
    assert ("title", "founder-of-the-commons") not in _keys(f, wins=wins)
    assert ("title", "founder-of-the-commons") in _keys(f, wins={1: ["2026Q2", "2026Q3"]})


def test_quarters_are_utc_calendar_quarters():
    assert ct.quarter_of(dt.datetime(2026, 3, 31, 23, 59, tzinfo=UTC)) == "2026Q1"
    assert ct.quarter_of(dt.datetime(2026, 4, 1, 0, 0, tzinfo=UTC)) == "2026Q2"
    assert ct.quarter_of(dt.datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == "2026Q4"


# --- progress shown to the person -----------------------------------------------------------------------------------------

def test_progress_says_n_of_m_and_which_are_unlocked():
    f = _facts([_change("a", 1)], ballots=[{"voter_developer_id": 1, "proposal_id": 1}])
    view = {(r["kind"], r["key"]): r for r in ct.progress(f.get(1, ct.Facts()), {}, unlocked={("corner", "initiate")})}
    assert view[("encirclement", "ember")]["progress"] == {"n": 1, "of": 3}
    assert view[("corner", "initiate")]["unlocked"] is True
    assert view[("encirclement", "ember")]["unlocked"] is False
    assert not view[("title", "bug-slayer")]["later"]                                          # nothing waits any more


# --- the tracker: one writer, idempotent -----------------------------------------------------------------------------------

class FakeStore:
    def __init__(self, changes=(), reviews=(), ballots=()):
        self.changes, self.reviews, self.ballots = list(changes), list(reviews), list(ballots)
        self.rows = {}                       # (dev, kind, key) -> row
        self.inserts = 0

    async def load(self, developer_ids):
        return self.changes, self.reviews, self.ballots

    async def season_counts(self):
        return ct.season_counts_from(self.changes)

    async def existing(self, developer_ids):
        return {k for k in self.rows}

    async def insert(self, rows):
        for r in rows:
            self.rows.setdefault((r["developer_id"], r["kind"], r["item_key"]), r)
            self.inserts += 1

    async def ledgers_zero(self):
        return None


def test_the_tracker_writes_each_unlock_once_and_a_second_run_writes_nothing():
    st = FakeStore([_change("a", 1, state="merged", merged_at=_month(2026, 11))])
    t = ct.Tracker(st)
    wrote = asyncio.run(t.evaluate([1], source="code_change:a", now=NOW))
    assert {(k, i) for (_, k, i) in st.rows} == {("corner", "initiate"), ("corner", "architect-prime"), ("title", "first-light")}
    before = st.inserts
    assert asyncio.run(t.evaluate([1], source="code_change:a", now=NOW)) == []
    assert st.inserts == before and len(wrote) == 3


def test_an_unlock_records_its_tier_and_the_event_that_unlocked_it():
    st = FakeStore([_change("a", 1)])
    asyncio.run(ct.Tracker(st).evaluate([1], source="code_change:a", now=NOW))
    row = st.rows[(1, "corner", "initiate")]
    assert row["tier"] == 1 and row["source"] == "code_change:a"


def test_the_backfill_walks_every_proposer_reviewer_and_voter():
    st = FakeStore([_change("a", 1), _change("b", 2)], [{"change_id": "a", "reviewer_developer_id": 3, "verdict": "approve"}],
                   [{"voter_developer_id": 4, "proposal_id": 1}])
    wrote = asyncio.run(ct.Tracker(st).backfill(now=NOW))
    devs = {r["developer_id"] for r in wrote}
    assert devs == {1, 2, 3}                                                           # 4 cast one ballot: nothing yet


def test_a_closed_quarter_is_written_by_the_tracker_with_its_season_as_the_source():
    st = FakeStore(_q(1, 3, month=5) + _q(2, 1, month=5))
    asyncio.run(ct.Tracker(st).evaluate([1], source="backfill", now=NOW))
    assert st.rows[(1, "corner", "crown-of-the-commons")]["source"] == "season:2026Q2"


def test_a_winner_of_a_closed_quarter_is_unlocked_by_ANY_evaluation_not_only_their_own_next_step():
    """Finding 7 (session-volume): the crown waited for the winner's next governed-code step, which can be months."""
    st = FakeStore(_q(1, 3, month=5) + _q(2, 1, month=5))
    asyncio.run(ct.Tracker(st).evaluate([2], source="code_change:z", now=NOW))        # somebody ELSE's step
    assert (1, "corner", "crown-of-the-commons") in st.rows and st.rows[(1, "corner", "crown-of-the-commons")]["source"] == "season:2026Q2"
    n = st.inserts
    asyncio.run(ct.Tracker(st).evaluate([2], source="code_change:z", now=NOW))
    assert st.inserts == n                                                             # and still written once


# --- the one-writer rule, read from the source -------------------------------------------------------------------------------

def _py_files():
    for p in SRC.rglob("*.py"):
        yield p


def test_nothing_but_the_evaluator_writes_the_unlock_table():
    writers = []
    for p in _py_files():
        if p.name == "contributor_track.py" or p.name == "models.py":
            continue
        txt = p.read_text(errors="ignore")
        if re.search(r"CosmeticUnlock\s*\(", txt) or re.search(r"(INSERT\s+INTO|insert\(|UPDATE|DELETE\s+FROM)\s+cosmetic_unlocks", txt, re.I):
            writers.append(str(p.relative_to(SRC)))
    assert writers == []


def test_the_tracker_module_moves_no_value():
    txt = (SRC / "services" / "contributor_track.py").read_text()
    for bad in ("teg_integration", "/teg/", "emit_event", "emit(", "treasury_fund", "httpx.post"):
        assert bad not in txt, bad


def test_the_commander_title_and_plate_have_no_unlock_path():
    txt = (SRC / "services" / "contributor_track.py").read_text()
    assert "'commander'" not in txt.replace('"', "'") or "commander" in txt.split("def ")[0]   # only named in the module's own docstring


# --- the hooks: after each state change, inside the same transaction ---------------------------------------------------------

def test_the_governed_code_store_calls_the_evaluator_before_it_commits():
    tree = ast.parse((SRC / "services" / "code_changes.py").read_text())
    store = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DbStore")
    for name in ("insert", "add_review", "update"):
        fn = next(n for n in store.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
        names = [getattr(c.func, "attr", getattr(c.func, "id", "")) for c in calls]
        assert "_track" in names, name
        # the evaluator runs before the commit that ends the step: same transaction
        order = [getattr(c.func, "attr", getattr(c.func, "id", "")) for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]
        assert order.index("_track") < order.index("commit"), name


# --- the migration ------------------------------------------------------------------------------------------------------------

def test_the_migration_creates_the_table_with_its_check_and_the_title_column():
    mig = [p for p in ALEMBIC.glob("*contributor*")]
    assert len(mig) == 1
    txt = mig[0].read_text()
    assert "cosmetic_unlocks" in txt and "flare_title" in txt
    assert re.search(r"CheckConstraint|CHECK \(", txt) and "corner" in txt and "encirclement" in txt and "overlay" in txt and "title" in txt
    assert "UniqueConstraint" in txt or "UNIQUE" in txt
    rev = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', txt, re.M).group(1)
    assert len(rev) <= 32
    down = re.search(r'^down_revision\s*=\s*["\']([^"\']+)["\']', txt, re.M).group(1)
    assert (ALEMBIC / f"{down}.py").exists()


def test_the_model_matches_the_migration():
    from agentvault_registry import models
    cols = {c.name for c in models.CosmeticUnlock.__table__.columns}
    assert {"developer_id", "kind", "item_key", "tier", "unlocked_at", "source"} <= cols
    assert "flare_title" in {c.name for c in models.Developer.__table__.columns}


# --- the earned item travels: the sidecar, the shop, the equip gate --------------------------------------------------------------

def test_a_worn_earned_ring_is_exported_with_no_flare_tier_and_never_on_a_sovereign_agent():
    # V0666: an agent exports the earned ring and badge IT wears (tests/test_flare_agent_earned_wear_v0666.py); the developer's own wear is not shipped on every agent
    from types import SimpleNamespace as NS
    from agentvault_registry.routers.federation_sync import _build_flare_sidecar
    dev = NS(flare_tier=None, flare_encirclement_variant="ember", flare_corner_variant="initiate", flare_encirclement_overlay=None,
             selected_corner_flare=None, selected_encirclement_flare=None, flare_id=None, flare_display_name=None, flare_tagline=None,
             flare_logo_url=None, flare_link_url=None, flare_cause=None, flare_accent_color=None, flare_granted_at=None)
    agent = NS(flare_tier=None, bears_corner_flare=False, bears_encirclement_flare=False, flare_encirclement_variant="ember",
               flare_encirclement_overlay=None, flare_corner_variant="initiate")
    side = asyncio.run(_build_flare_sidecar(agent, dev, "spiffe://x"))
    assert side and side["encirclement_variant"] == "ember" and side["corner_variant"] == "initiate"
    sov = NS(**{**agent.__dict__, "flare_tier": "sovereign", "flare_encirclement_variant": None, "flare_corner_variant": None})
    side2 = asyncio.run(_build_flare_sidecar(sov, dev, "spiffe://x"))
    assert side2["encirclement_variant"] is None and side2["corner_variant"] is None
    plain = NS(**{**agent.__dict__, "flare_encirclement_variant": "sauron", "flare_corner_variant": None})
    assert asyncio.run(_build_flare_sidecar(plain, dev, "spiffe://x")) is None                  # an old variant with no tier still exports nothing


def test_the_shop_never_lists_an_earned_key():
    txt = (SRC / "routers" / "flare_shop.py").read_text()
    assert "FLARE_ENCIRCLEMENT_VARIANTS - EARNED_ENCIRCLEMENTS" in txt and "FLARE_CORNER_VARIANTS - EARNED_CORNERS" in txt
    assert "sorted(FLARE_ENCIRCLEMENT_VARIANTS)" not in txt and "sorted(FLARE_CORNER_VARIANTS)" not in txt


def test_the_customize_route_asks_for_the_unlock_row_for_an_earned_item():
    txt = (SRC / "routers" / "fiat_onramp.py").read_text()
    assert 'require_unlocked(db, current_dev.id, "encirclement", new_variant)' in txt
    assert 'require_unlocked(db, current_dev.id, "corner", new_cv)' in txt
    assert "touch_native_card_no_commit" in txt.split("async def update_my_flare_selection", 1)[1].split("@router", 1)[0]


def test_require_unlocked_refuses_with_the_sentence_of_what_unlocks_it():
    from fastapi import HTTPException

    class Db:
        async def execute(self, *_a, **_k):
            class R:
                def all(self):
                    return []
            return R()

    with pytest.raises(HTTPException) as e:
        asyncio.run(ct.require_unlocked(Db(), 7, "encirclement", "ember"))
    assert e.value.status_code == 403 and "Cast three ballots" in e.value.detail and "'ember'" in e.value.detail


# --- the routes and the MCP tools -----------------------------------------------------------------------------------------

def test_the_three_mcp_tools_are_wired_in_every_place():
    mcp = SRC / "mcp"
    server, audit, cats = (mcp / "server.py").read_text(), (mcp / "audit.py").read_text(), (mcp / "tool_categories.py").read_text()
    for name in ("getContributorTrack", "getMyContributorTrack", "equipTitle"):
        assert f'"theprotocol_{name}"' in server and f'"theprotocol_{name}"' in audit, name
        assert f'"{name}"' in cats, name
    schemas = (mcp / "tools_discovery.py").read_text() + (mcp / "tools_developer.py").read_text()
    for name in ("getContributorTrack", "getMyContributorTrack", "equipTitle"):
        assert f'"name": "theprotocol_{name}"' in schemas, name
    contracts = (SRC / "api_tests" / "contracts" / "mcp_contracts.py").read_text()
    for name in ("getContributorTrack", "getMyContributorTrack", "equipTitle"):
        assert f'"theprotocol_{name}": McpContract(' in contracts, name


def test_the_mcp_tools_call_the_routes_that_exist():
    routes = (SRC / "routers" / "contributor_track.py").read_text()
    for path in ("/api/v1/public/contributor-track", "/api/v1/developers/me/contributor-track", "/api/v1/developers/me/flare/title"):
        assert path in routes, path
    dev = (SRC / "mcp" / "tools_developer.py").read_text()
    assert '"PUT", "/api/v1/developers/me/flare/title", json_body={"title_key": title_key}' in dev


def test_the_router_is_mounted_and_has_no_grant_route():
    assert "_contributor_track_router.router" in (SRC / "main.py").read_text()
    routes = (SRC / "routers" / "contributor_track.py").read_text()
    methods = re.findall(r"@router\.(get|put|post|delete|patch)\(", routes)
    assert sorted(methods) == ["get", "get", "get", "put"]                     # no POST, no DELETE: nothing is granted or taken by a route


def test_equipping_a_title_asks_for_the_unlock_row_and_the_catalog():
    routes = (SRC / "routers" / "contributor_track.py").read_text()
    assert "FLARE_TITLES" in routes and 'require_unlocked(db, dev.id, "title", key)' in routes


def test_the_backfill_is_a_script_that_goes_through_the_tracker_and_never_through_boot():
    s = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "contributor_track_backfill.py").read_text()
    assert "Tracker(" in s and "backfill()" in s and "CosmeticUnlock" not in s and "INSERT INTO" not in s.upper() and "pg_insert" not in s
    main_txt = (SRC / "main.py").read_text()
    assert "contributor_track_backfill" not in main_txt and ".backfill(" not in main_txt


# --- the four extra titles ----------------------------------------------------------------------------------------------------

def test_dead_letter_whisperer_is_a_change_merged_more_than_thirty_days_after_it_was_proposed():
    made = dt.datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    late = _merged("a", 1, 6, 2)
    late["created_at"] = made                                                          # proposed 2026-05-01, merged 2026-06-02: 32 days
    assert ("title", "dead-letter-whisperer") in _keys(_facts([late]))
    soon = _merged("b", 1, 5, 20)
    soon["created_at"] = made                                                          # 19 days
    assert ("title", "dead-letter-whisperer") not in _keys(_facts([soon]))
    border = _merged("d", 1, 5, 31)
    border["created_at"] = made                                                        # exactly thirty days: not more than thirty
    assert ("title", "dead-letter-whisperer") not in _keys(_facts([border]))
    assert ("title", "dead-letter-whisperer") not in _keys(_facts([_merged("e", 1, 6)]))   # no proposal time recorded: nothing is assumed


def test_rollback_ready_is_five_sensitive_merged_changes_each_with_its_own_tests():
    five = [_merged(f"c{i}", 1, 1 + i, sensitive=True, passed=True, paths=("views/A.vue", "views/A.test.ts")) for i in range(5)]
    assert ("title", "rollback-ready") in _keys(_facts(five)) and ("title", "rollback-ready") not in _keys(_facts(five[:4]))
    untested = [_merged(f"c{i}", 1, 1 + i, sensitive=True, passed=True) for i in range(5)]
    assert ("title", "rollback-ready") not in _keys(_facts(untested))
    plain = [_merged(f"c{i}", 1, 1 + i, paths=("views/A.vue", "views/A.test.ts")) for i in range(5)]
    assert ("title", "rollback-ready") not in _keys(_facts(plain))


def test_quorum_maker_is_ballots_on_twenty_five_changes_that_reached_their_quorum():
    yes = [{"voter_developer_id": 1, "proposal_id": i, "quorum_met": True} for i in range(25)]
    assert ("title", "quorum-maker") in _keys(_facts(ballots=yes)) and ("title", "quorum-maker") not in _keys(_facts(ballots=yes[:24]))
    mixed = yes[:20] + [{"voter_developer_id": 1, "proposal_id": 100 + i, "quorum_met": False} for i in range(10)]
    assert ("title", "quorum-maker") not in _keys(_facts(ballots=mixed))
    unknown = [{"voter_developer_id": 1, "proposal_id": i, "quorum_met": None} for i in range(30)]     # not yet tallied: nothing counted
    assert ("title", "quorum-maker") not in _keys(_facts(ballots=unknown))


def _first(cid, dev, month, **kw):
    c = _merged(cid, dev, month, 1 + int(cid[1:]) % 25, **kw)
    c.update(commit="aa", merged_commit="aa", acceptance_commit="aa")
    return c


def test_clean_checkout_is_ten_changes_merged_on_their_first_commit():
    ten = [_first(f"c{i}", 1, 1 + i % 10) for i in range(10)]
    reviews = [{"change_id": f"c{i}", "reviewer_developer_id": 2, "verdict": "approve", "commit": "aa"} for i in range(10)]
    assert ("title", "clean-checkout") in _keys(_facts(ten, reviews)) and ("title", "clean-checkout") not in _keys(_facts(ten[:9], reviews[:9]))
    moved = [dict(c) for c in ten]
    moved[0]["acceptance_commit"] = "bb"                                               # the checker read another commit than the one merged
    assert ("title", "clean-checkout") not in _keys(_facts(moved, reviews))
    reviewed_old = reviews + [{"change_id": "c1", "reviewer_developer_id": 3, "verdict": "changes", "commit": "zz"}]   # a review on an earlier commit
    assert ("title", "clean-checkout") not in _keys(_facts(ten, reviewed_old))


# --- the backfill stamps the time of the event (finding 2) ----------------------------------------------------------------------

def test_the_backfill_stamps_each_unlock_with_the_time_of_its_event_not_the_time_it_ran():
    made, merged = _month(2026, 8, 1), _month(2026, 9, 9)
    st = FakeStore([{**_change("a", 1, state="merged", merged_at=merged), "created_at": made}])
    asyncio.run(ct.Tracker(st).backfill(now=NOW))
    assert st.rows[(1, "corner", "initiate")]["unlocked_at"] == made                   # the first proposal
    assert st.rows[(1, "corner", "architect-prime")]["unlocked_at"] == merged         # the first merge
    assert st.rows[(1, "title", "first-light")]["unlocked_at"] == merged
    assert all(r["source"] == "backfill" for r in st.rows.values())


def test_a_backfilled_review_and_ballot_carry_their_own_times():
    t1, t2, t3 = _month(2026, 8, 2), _month(2026, 8, 20), _month(2026, 9, 1)
    st = FakeStore([{**_change("a", 1), "created_at": t1}],
                   [{"change_id": "a", "reviewer_developer_id": 3, "verdict": "approve", "created_at": t2}],
                   [{"voter_developer_id": 4, "proposal_id": 1, "created_at": t3}])
    asyncio.run(ct.Tracker(st).backfill(now=NOW))
    mine = [r for (d, k, i), r in st.rows.items() if d == 3]
    assert mine and all(r["unlocked_at"] == t2 for r in mine)                         # the first review is what unlocked them
    assert not [r for (d, k, i), r in st.rows.items() if d == 4]                       # one ballot unlocks nothing yet


def test_a_season_is_stamped_with_the_day_its_quarter_closed():
    st = FakeStore(_q(1, 3, month=5) + _q(2, 1, month=5))
    asyncio.run(ct.Tracker(st).backfill(now=NOW))
    assert st.rows[(1, "corner", "crown-of-the-commons")]["unlocked_at"] == dt.datetime(2026, 7, 1, tzinfo=UTC)


def test_a_live_evaluation_still_stamps_now():
    st = FakeStore([_change("a", 1)])
    asyncio.run(ct.Tracker(st).evaluate([1], source="code_change:a", now=NOW))
    assert st.rows[(1, "corner", "initiate")]["unlocked_at"] == NOW


def test_a_row_with_no_time_falls_back_to_the_time_of_the_run():
    st = FakeStore([_change("a", 1)])                                                  # no created_at in the loaded row
    asyncio.run(ct.Tracker(st).backfill(now=NOW))
    assert st.rows[(1, "corner", "initiate")]["unlocked_at"] == NOW


# --- casting a ballot evaluates (finding 6) -----------------------------------------------------------------------------------

class _R:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v


class _Db:
    def __init__(self, answers, boom=False):
        self.answers, self.committed, self.boom = list(answers), 0, boom

    async def execute(self, q):
        if self.boom:
            raise RuntimeError("database away")
        return _R(self.answers.pop(0))

    async def commit(self):
        self.committed += 1


def test_casting_a_ballot_on_a_code_change_evaluates_the_voter_at_once(monkeypatch):
    calls = []

    async def fake(db, ids, source):
        calls.append((list(ids), source))
        return []
    monkeypatch.setattr(ct, "track_event", fake)
    db = _Db(["code_change", 7])
    asyncio.run(ct.track_ballot(db, 12, "did:theprotocol:v"))
    assert calls == [([7], "ballot:12")] and db.committed == 1


def test_a_ballot_on_anything_else_or_by_a_voter_with_no_developer_evaluates_nobody(monkeypatch):
    calls = []

    async def fake(db, ids, source):
        calls.append(ids)
        return []
    monkeypatch.setattr(ct, "track_event", fake)
    for answers in (["parameter"], [None], ["code_change", None]):
        db = _Db(answers)
        assert asyncio.run(ct.track_ballot(db, 13, "did:x")) == []
        assert db.committed == 0
    assert calls == []


def test_a_failure_in_the_ballot_hook_never_reaches_the_vote():
    db = _Db([], boom=True)
    assert asyncio.run(ct.track_ballot(db, 14, "did:x")) == []


def test_the_vote_route_calls_the_ballot_hook_after_the_vote_is_stored_and_before_it_answers():
    tree = ast.parse((SRC / "routers" / "governance.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "cast_vote")
    calls = sorted([c for c in ast.walk(fn) if isinstance(c, ast.Call)], key=lambda c: (c.lineno, c.col_offset))
    names = [getattr(c.func, "attr", getattr(c.func, "id", "")) for c in calls]
    assert "track_ballot" in names
    assert names.index("track_ballot") > names.index("cast_vote"), "the ballot is evaluated only after crud_governance.cast_vote stored it"
    ret = [r for r in ast.walk(fn) if isinstance(r, ast.Return) and getattr(getattr(r.value, "func", None), "id", "") == "VoteResponse"]
    assert ret and min(c.lineno for c in calls if getattr(c.func, "attr", getattr(c.func, "id", "")) == "track_ballot") < ret[0].lineno


# --- the store reads only what it needs (finding 5) ---------------------------------------------------------------------------

def test_the_store_filters_by_the_developers_and_reads_the_seasons_with_one_grouped_query():
    tree = ast.parse((SRC / "services" / "contributor_track.py").read_text())
    store = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DbTrackStore")
    load = next(n for n in store.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "load")
    assert any(isinstance(n, ast.Name) and n.id == "developer_ids" for n in ast.walk(load))
    src = ast.get_source_segment((SRC / "services" / "contributor_track.py").read_text(), store)
    assert "async def season_counts" in src and "group_by" in src
    text = (SRC / "services" / "contributor_track.py").read_text()
    assert text.count("await self.s.season_counts()") == 1 and text.count("await store.season_counts()") == 1   # the tracker and the view


def test_a_model_comment_names_the_migration_that_exists():
    assert "Migration 0229" not in (SRC / "models.py").read_text()                     # the title column came with 0230
