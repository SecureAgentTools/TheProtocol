"""V0665 the contributor track (order gwo_5e0701efdef9d3989491bc37; room seq 4063, 4070, 4081). THE DESIGN:
sessionlogs2026/DESIGN_2026-11-14_CONTRIBUTOR_TRACK.md.

Corner badges, rings and titles that are EARNED by governed-code events and by nothing else. This module is the ONE writer of the
`cosmetic_unlocks` table (a test greps the tree for a second one): no route grants an item, no shop sells one, nothing transfers one.
No value moves here (no TEG call, no event): Δ is untouched by construction. The old badges and rings are not in this module's reach:
they stay exactly as they are (tests/test_flare_catalog_pinned_v0665.py).

Three layers:
  - pure: `facts_from` turns the governed-code rows into per-developer facts, `season_wins` names the closed quarters' top contributors,
    `earned` and `progress` read the facts against the track;
  - `Tracker`: loads through a store, writes the unlock rows idempotently (a row exists once), once per event, in the caller's transaction;
  - `DbTrackStore`: the SQL behind the store (the only place that inserts).

The pass is ONE ladder of forty tiers, rising by effort, and every item on it can be earned today: its condition reads the governed-code tables
(a count of merged changes, reviews, ballots, months, areas, sensitive passes or season wins) and nothing waits for a signal that does not exist.
An item whose condition could not be read from those tables would be shown as "comes later" with its reason and never unlock (`later`), and nothing
here invents a condition; no item is in that state now.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

UTC = dt.timezone.utc

# --- the track ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    kind: str                     # corner | encirclement | title  (overlay is in the table's vocabulary, the art draws none)
    key: str
    tier: Optional[int]           # the item's tier on the pass, 1 to 40 (items with the same condition share a tier; None: off the pass)
    cond: str                     # the condition's name ("later": no signal or no condition yet)
    n: int                        # the count the condition wants
    sentence: str                 # the condition in one sentence, for the person
    side: bool = False            # a side quest, off the main row
    later: Optional[str] = None   # why it cannot be earned yet (the sentence beside it on the track)


def _i(kind, key, tier, cond, n, sentence, **kw) -> Item:
    return Item(kind, key, tier, cond, n, sentence, **kw)


TRACK: Tuple[Item, ...] = (
    # ONE rising ladder of 40 tiers (the Commander's word on the preview, room seq 4592; session-lead seq 4594 and 4607). The ten items of the first table are spread among the
    # others by effort and keep their order; items with the same condition share a tier; the items that turn on luck more than on effort come after effort items of similar
    # weight; the season win comes near the end and the founder's title last. Every condition reads the governed-code tables; nothing waits for a signal.
    _i("corner", "initiate", 1, "proposals", 1, "Propose your first change."),
    _i("encirclement", "lantern", 2, "reviews", 1, "Review someone else's change."),
    _i("corner", "architect-prime", 3, "merged", 1, "Have your first change merged."),
    _i("title", "first-light", 3, "merged", 1, "Have your first change merged."),
    _i("encirclement", "ember", 4, "ballots", 3, "Cast three ballots on code changes."),
    _i("corner", "lantern-key", 5, "lantern_key", 1, "Ask for changes in a review, then approve the fixed commit of the same change."),
    _i("encirclement", "quantum-halo", 6, "quantum", 1, "Have a change to a quantum page (console or docs) merged."),
    _i("corner", "keystone", 7, "merged", 5, "Have five changes merged."),
    _i("title", "patchwright", 7, "merged", 5, "Have five changes merged."),
    _i("corner", "quill", 8, "docs", 5, "Have five documentation changes merged."),
    _i("title", "ballot-bearer", 9, "ballots", 10, "Cast ten ballots on code changes."),
    _i("corner", "founders-seal", 10, "reviews", 10, "Review ten changes."),
    _i("title", "second-pair-of-eyes", 10, "reviews", 10, "Review ten changes."),
    _i("encirclement", "lattice", 11, "areas", 5, "Have merged changes in five areas of the tree (views, components, stores, services, docs)."),
    _i("title", "mutually-trusted", 12, "mutual", 5, "Have your changes reviewed by five different people, and review the changes of five different people."),
    _i("corner", "gatekeeper", 13, "asked_changes", 10, "Write ten reviews that ask for changes."),
    _i("encirclement", "eye-of-the-senate", 14, "sensitive_passed", 1, "Have a change on a sensitive path pass the members' ballot."),
    _i("encirclement", "solar-flare", 15, "merged", 10, "Have ten changes merged."),
    _i("title", "off-by-one", 16, "one_vote", 1, "Have a change pass the ballot by a single vote."),
    _i("encirclement", "ouroboros", 17, "streak", 3, "Have changes merged in three months in a row."),
    _i("corner", "anvil", 18, "tests", 10, "Have ten merged changes that carry their own tests."),
    _i("corner", "ledger-seal", 19, "unanimous", 1, "Have a change pass the ballot unanimously, with at least five votes."),
    _i("title", "clean-checkout", 20, "clean_first", 10, "Have ten changes merged on their first commit."),
    _i("title", "dead-letter-whisperer", 21, "stalled", 1, "Have a change merged more than thirty days after it was proposed."),
    _i("title", "exactly-once", 22, "single_review", 10, "Have ten merged changes that exactly one reviewer approved."),
    _i("title", "bug-slayer", 23, "fixes", 10, "Have ten merged changes whose title starts with Fix (the title is read for the word, nothing else marks a fix)."),
    _i("title", "it-works-on-my-frame", 24, "comebacks", 1, "Have a change merged after one of yours was vetoed, withdrawn or failed its ballot."),
    _i("encirclement", "watcher", 25, "reviews", 25, "Review twenty-five changes of other people's."),
    _i("title", "senate-scribe", 26, "senate", 25, "Cast twenty-five ballots and propose ten changes."),
    _i("title", "quorum-maker", 27, "quorum_ballots", 25, "Cast ballots on twenty-five code changes that reached their quorum."),
    _i("title", "keeper-of-delta-zero", 28, "no_asks", 20, "Have twenty changes merged that no reviewer had to ask changes on."),
    _i("encirclement", "event-horizon", 29, "merged", 25, "Have twenty-five changes merged."),
    _i("encirclement", "abyss", 30, "months", 12, "Have changes merged in twelve different months."),
    _i("title", "rollback-ready", 31, "sensitive_tested", 5, "Have five sensitive changes merged, each carrying its own tests."),
    _i("encirclement", "eclipse", 32, "sensitive_passed", 5, "Have five changes on a sensitive path pass the members' ballot."),
    _i("encirclement", "merkle-ring", 33, "ballots", 50, "Cast fifty ballots on code changes."),
    _i("title", "beast-tamer", 34, "tamer", 25, "Have a sensitive change pass the ballot, and have twenty-five changes merged."),
    _i("title", "the-eye-sees-all", 35, "reviews_final", 50, "Review fifty changes, each on the commit that was finally merged."),
    _i("title", "architect-of-the-beast", 36, "merged", 50, "Have fifty changes merged."),
    _i("encirclement", "singularity", 37, "merged", 75, "Have seventy-five changes merged."),
    _i("title", "event-horizon", 38, "merged", 100, "Have a hundred changes merged."),
    _i("corner", "crown-of-the-commons", 39, "seasons", 1, "Be a season's top contributor (a season is a calendar quarter): at least three merged changes in it, and at least two people who merged something."),
    _i("encirclement", "supernova", 39, "seasons", 1, "Be a season's top contributor (a season is a calendar quarter): at least three merged changes in it, and at least two people who merged something."),
    _i("title", "founder-of-the-commons", 40, "seasons", 2, "Be a season's top contributor twice (each season needs at least three merged changes and two people who merged something)."),
)


# --- the facts ---------------------------------------------------------------------------------------------------------

@dataclass
class Facts:
    proposals: int = 0
    reviews: int = 0                       # changes of OTHER people this developer reviewed, once each
    merged: int = 0
    ballots: int = 0                       # code-change ballots cast, once per proposal
    sensitive_passed: int = 0
    merge_months: Set[str] = field(default_factory=set)
    one_vote: int = 0                      # changes that passed by a single vote
    single_review: int = 0                 # merged changes whose merged commit exactly one reviewer approved (a reviewer's latest word counts)
    fixes: int = 0                         # merged changes whose title says fix
    comebacks: int = 0                     # 1 once a change of this developer merged after another of theirs was vetoed, withdrawn or failed
    no_asks: int = 0                       # merged changes no reviewer had to ask changes on (at any commit)
    reviews_final: int = 0                 # changes of other people's reviewed on the commit that was finally merged, once each
    reviewed_by: Set[int] = field(default_factory=set)      # the other developers who reviewed a change of this one's
    reviewed_others: Set[int] = field(default_factory=set)  # the other developers whose changes this one reviewed
    areas: Set[str] = field(default_factory=set)   # of views, components, stores, services, docs: the areas merged changes touched
    docs: int = 0                          # merged changes touching documentation
    tests: int = 0                         # merged changes with a test file among their paths
    quantum: int = 0                       # merged changes touching a quantum page
    asked_changes: int = 0                 # changes (of other people's) where this reviewer asked for changes
    lantern_key: int = 0                   # changes where this reviewer asked for changes and later approved ANOTHER commit
    unanimous: int = 0                     # passed changes with no vote against and at least five for
    stalled: int = 0                       # merged more than thirty days after they were proposed
    sensitive_tested: int = 0              # merged sensitive changes with a test file among their paths
    quorum_ballots: int = 0                # code-change ballots cast on proposals whose tally reached the quorum
    clean_first: int = 0                   # merged on their first commit: every review and the checker on the commit that merged

    @property
    def streak(self) -> int:
        """The longest run of consecutive calendar months with a merged change."""
        nums = sorted({int(m[:4]) * 12 + int(m[5:7]) - 1 for m in self.merge_months})
        best = run = 0
        prev = None
        for n in nums:
            run = run + 1 if prev is not None and n == prev + 1 else 1
            best, prev = max(best, run), n
        return best

    @property
    def areas_count(self) -> int:
        return len(self.areas)



# a change title that says fix: the first word is fix, fixes, fixed, bugfix or bug (a word that only contains fix, as in fixture or hotfix, is not a fix)
_FIX_TITLE = re.compile(r"^\s*(fix|fixes|fixed|bugfix|bug)\b", re.I)


_AREAS = ("views", "components", "stores", "services")
_TEST = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|\.(test|spec)\.[a-z]+$", re.I)


def _rel(path: str, open_prefixes: Sequence[str]) -> str:
    for p in open_prefixes:
        if p and path.startswith(p):
            return path[len(p):]
    return path


def _area(rel: str) -> Optional[str]:
    """A change's path by its first segment: views, components, stores, services; documentation lives under assets/docs."""
    if rel.startswith("assets/docs/") or rel.startswith("docs/"):
        return "docs"
    first = rel.split("/", 1)[0]
    return first if first in _AREAS else None


def _open_prefixes() -> List[str]:
    try:
        from .code_changes import open_paths
        return [p for v in open_paths().values() for p in v]
    except Exception:                                                   # noqa: BLE001: the path rules fall back to "none open"
        return []


def quarter_of(when: dt.datetime) -> str:
    when = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
    return f"{when.year}Q{(when.month - 1) // 3 + 1}"


def _quarter_end(q: str) -> dt.datetime:
    y, n = int(q[:4]), int(q[5])
    month = n * 3 + 1
    return dt.datetime(y + (month > 12), 1 if month > 12 else month, 1, tzinfo=UTC)


def facts_from(changes: Sequence[Dict[str, Any]], reviews: Sequence[Dict[str, Any]], ballots: Sequence[Dict[str, Any]]) -> Dict[int, Facts]:
    """Per developer, from the governed-code rows. changes: {id, proposer_developer_id, state, sensitive, paths, merged_at, passed,
    votes_for, votes_against}; reviews: {change_id, reviewer_developer_id, verdict}; ballots: {voter_developer_id, proposal_id}."""
    out: Dict[int, Facts] = {}
    pre = _open_prefixes()

    def of(dev: int) -> Facts:
        return out.setdefault(dev, Facts())

    by_id = {c["id"]: c for c in changes}
    rv_by_change: Dict[Any, List[Dict[str, Any]]] = {}
    for r in reviews:
        rv_by_change.setdefault(r.get("change_id"), []).append(r)
    for c in changes:
        dev = c.get("proposer_developer_id")
        if dev is None:
            continue
        f = of(dev)
        f.proposals += 1
        if c.get("sensitive") and c.get("passed"):
            f.sensitive_passed += 1
        if c.get("passed") and (c.get("votes_for", 0) or 0) - (c.get("votes_against", 0) or 0) == 1:
            f.one_vote += 1
        if c.get("passed") and (c.get("votes_against", 0) or 0) == 0 and (c.get("votes_for", 0) or 0) >= 5:
            f.unanimous += 1
        if c.get("state") == "merged":
            f.merged += 1
            when = c.get("merged_at")
            if isinstance(when, dt.datetime):
                w = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
                f.merge_months.add(f"{w.year:04d}-{w.month:02d}")
            paths = [p for p in (c.get("paths") or []) if isinstance(p, str)]
            rels = [_rel(p, pre) for p in paths]
            for r in rels:
                a_ = _area(r)
                if a_:
                    f.areas.add(a_)
            if any(_area(r) == "docs" for r in rels):
                f.docs += 1
            if any(_TEST.search(r) for r in rels):
                f.tests += 1
            if any("quantum" in r.lower() for r in rels):
                f.quantum += 1
            has_test = any(_TEST.search(r) for r in rels)
            if c.get("sensitive") and has_test:
                f.sensitive_tested += 1
            made = c.get("created_at")
            if isinstance(when, dt.datetime) and isinstance(made, dt.datetime):
                w2 = when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
                m2 = made.astimezone(UTC) if made.tzinfo else made.replace(tzinfo=UTC)
                if w2 - m2 > dt.timedelta(days=30):
                    f.stalled += 1
            mine = rv_by_change.get(c.get("id"), [])
            rv_commits = {r.get("commit") for r in mine if r.get("commit") is not None}
            tip = c.get("commit")
            if tip and c.get("merged_commit") == tip and c.get("acceptance_commit") in (None, tip) and rv_commits <= {tip}:
                f.clean_first += 1
            if not any(r.get("verdict") == "changes" for r in mine):
                f.no_asks += 1
            if _FIX_TITLE.search(str(c.get("title") or "")):
                f.fixes += 1
            # exactly one reviewer approved the commit that merged: each reviewer's LATEST word on it counts
            latest: Dict[Any, str] = {}
            for r in mine:
                if r.get("commit") == c.get("merged_commit") and r.get("reviewer_developer_id") != dev:
                    latest[r.get("reviewer_developer_id")] = r.get("verdict")
            if sum(1 for v in latest.values() if v == "approve") == 1:
                f.single_review += 1
    # a comeback: a change of theirs merged after another of theirs was vetoed, withdrawn or failed its ballot (the order is the changes' creation)
    refused_at: Dict[int, dt.datetime] = {}
    for c in changes:
        dev, made = c.get("proposer_developer_id"), c.get("created_at")
        if dev is not None and isinstance(made, dt.datetime) and c.get("state") in ("failed", "vetoed", "withdrawn"):
            m_ = _utc(made)
            refused_at[dev] = min(refused_at[dev], m_) if dev in refused_at else m_
    for c in changes:
        dev, made = c.get("proposer_developer_id"), c.get("created_at")
        if dev in refused_at and c.get("state") == "merged" and isinstance(made, dt.datetime) and _utc(made) > refused_at[dev]:
            of(dev).comebacks = 1
    seen: Set[Tuple[int, Any]] = set()
    asked: Set[Tuple[int, Any]] = set()
    final_seen: Set[Tuple[int, Any]] = set()
    history: Dict[Tuple[int, Any], List[Dict[str, Any]]] = {}
    for r in reviews:
        dev, cid = r.get("reviewer_developer_id"), r.get("change_id")
        ch = by_id.get(cid)
        if dev is None or ch is None or ch.get("proposer_developer_id") == dev:
            continue
        history.setdefault((dev, cid), []).append(r)
        if ch.get("proposer_developer_id") is not None:
            of(dev).reviewed_others.add(ch["proposer_developer_id"])
            of(ch["proposer_developer_id"]).reviewed_by.add(dev)
        if ch.get("state") == "merged" and r.get("commit") is not None and r.get("commit") == ch.get("merged_commit") and (dev, cid) not in final_seen:
            final_seen.add((dev, cid))
            of(dev).reviews_final += 1
        if (dev, cid) not in seen:
            seen.add((dev, cid))
            of(dev).reviews += 1
        if r.get("verdict") == "changes" and (dev, cid) not in asked:
            asked.add((dev, cid))
            of(dev).asked_changes += 1
    for (dev, cid), rows in history.items():
        # ask for changes, then approve a DIFFERENT commit of the same change (the rows are in the order they were written)
        asked_on = None
        for r in rows:
            if r.get("verdict") == "changes":
                asked_on = r.get("commit") if asked_on is None else asked_on
            elif r.get("verdict") == "approve" and asked_on is not None and r.get("commit") != asked_on:
                of(dev).lantern_key += 1
                break
    voted: Set[Tuple[int, Any]] = set()
    for b in ballots:
        dev, pid = b.get("voter_developer_id"), b.get("proposal_id")
        if dev is None or (dev, pid) in voted:
            continue
        voted.add((dev, pid))
        of(dev).ballots += 1
        if b.get("quorum_met") is True:
            of(dev).quorum_ballots += 1
    return out


# A season is not won by one lonely change: the winner has at least this many merged changes in the quarter, and at least this many people
# merged something in it (session-lead's decision, 2026-11-15); otherwise nobody wins that quarter.
SEASON_MIN_MERGED = 3
SEASON_MIN_PEOPLE = 2


def _utc(x: dt.datetime) -> dt.datetime:
    return x.astimezone(UTC) if x.tzinfo else x.replace(tzinfo=UTC)


def season_counts_from(changes: Sequence[Dict[str, Any]]) -> List[Tuple[str, int, int, dt.datetime]]:
    """(quarter, developer, merged changes, last merge) over the merged changes: the shape the database's one grouped query returns."""
    per: Dict[Tuple[str, int], List[dt.datetime]] = {}
    for c in changes:
        when, dev = c.get("merged_at"), c.get("proposer_developer_id")
        if c.get("state") != "merged" or not isinstance(when, dt.datetime) or dev is None:
            continue
        w = _utc(when)
        per.setdefault((quarter_of(w), dev), []).append(w)
    return [(q, dev, len(v), max(v)) for (q, dev), v in sorted(per.items())]


def season_wins_from(counts: Iterable[Tuple[str, int, int, dt.datetime]], now: dt.datetime) -> Dict[int, List[str]]:
    """The top contributor of each CLOSED calendar quarter (UTC): the most merged changes, ties to the earlier last merge; and only when the
    floor holds (SEASON_MIN_MERGED merged changes, SEASON_MIN_PEOPLE people who merged something that quarter)."""
    now = _utc(now)
    board: Dict[str, Dict[int, Tuple[int, dt.datetime]]] = {}
    for q, dev, n, last in counts:
        board.setdefault(q, {})[dev] = (n, _utc(last))
    wins: Dict[int, List[str]] = {}
    for q in sorted(board):
        if _quarter_end(q) > now:
            continue                                                    # a quarter is won only once it is closed
        if len(board[q]) < SEASON_MIN_PEOPLE:
            continue
        dev, (n, _last) = min(board[q].items(), key=lambda kv: (-kv[1][0], kv[1][1]))
        if n >= SEASON_MIN_MERGED:
            wins.setdefault(dev, []).append(q)
    return wins


def season_wins(changes: Sequence[Dict[str, Any]], now: dt.datetime) -> Dict[int, List[str]]:
    """season_wins_from over merged changes held in memory."""
    return season_wins_from(season_counts_from(changes), now)


def unlock_times(changes: Sequence[Dict[str, Any]], reviews: Sequence[Dict[str, Any]], ballots: Sequence[Dict[str, Any]],
                 dev: int) -> Dict[Tuple[str, str], dt.datetime]:
    """When each item one developer holds was FIRST satisfied, by replaying the rows as they stood at each of their own events (a change as
    it was then: merged only once merged_at had come, passed only once passed_at had). The backfill stamps these, so an old unlock carries the
    date of what unlocked it, not the date the script ran. A row with no time counts as always there. Items whose time cannot be found are
    absent: the caller falls back to the run's own time."""
    def when(x: Any) -> Optional[dt.datetime]:
        return _utc(x) if isinstance(x, dt.datetime) else None

    stamps: Set[dt.datetime] = set()
    for c in changes:
        if c.get("proposer_developer_id") == dev:
            stamps |= {t for t in (when(c.get(k)) for k in ("created_at", "merged_at", "passed_at")) if t}
    stamps |= {t for t in (when(r.get("created_at")) for r in reviews if r.get("reviewer_developer_id") == dev) if t}
    stamps |= {t for t in (when(b.get("created_at")) for b in ballots if b.get("voter_developer_id") == dev) if t}
    out: Dict[Tuple[str, str], dt.datetime] = {}
    for t in sorted(stamps):
        cs: List[Dict[str, Any]] = []
        for c in changes:
            made = when(c.get("created_at"))
            if made and made > t:
                continue
            cc = dict(c)
            merged = when(c.get("merged_at"))
            if c.get("state") == "merged" and merged and merged > t:
                cc["state"], cc["merged_at"] = "proposed", None
            passed = when(c.get("passed_at"))
            if c.get("passed") and passed and passed > t:
                cc["passed"] = False
            cs.append(cc)
        rs = [r for r in reviews if not when(r.get("created_at")) or when(r.get("created_at")) <= t]
        bs = [b for b in ballots if not when(b.get("created_at")) or when(b.get("created_at")) <= t]
        f = facts_from(cs, rs, bs).get(dev)
        if f is None:
            continue
        for it in earned_for(f, ()):
            out.setdefault((it.kind, it.key), t)
    return out


# --- reading the facts against the track ---------------------------------------------------------------------------------

def _measure(it: Item, f: Facts, wins: Sequence[str]) -> Tuple[bool, int, int]:
    """(done, n, of) for one item. 'later' never completes: no signal, no unlock."""
    c = it.cond
    if c == "later":
        return False, 0, it.n
    if c == "months":
        return len(f.merge_months) >= it.n, len(f.merge_months), it.n
    if c == "streak":
        return f.streak >= it.n, f.streak, it.n
    if c == "areas":
        return f.areas_count >= it.n, f.areas_count, it.n
    if c == "seasons":
        return len(wins) >= it.n, len(wins), it.n
    if c == "senate":
        ok = f.ballots >= 25 and f.proposals >= 10
        return ok, min(f.ballots, 25) + min(f.proposals, 10), 35
    if c == "mutual":
        ok = len(f.reviewed_by) >= it.n and len(f.reviewed_others) >= it.n
        return ok, min(len(f.reviewed_by), it.n) + min(len(f.reviewed_others), it.n), 2 * it.n
    if c == "tamer":
        ok = f.sensitive_passed >= 1 and f.merged >= it.n
        return ok, f.merged, it.n
    n = getattr(f, c)
    return n >= it.n, n, it.n


def earned_for(f: Facts, wins: Sequence[str]) -> List[Item]:
    """The items one developer's facts satisfy."""
    return [it for it in TRACK if _measure(it, f, wins)[0]]


def earned(facts: Dict[int, Facts], wins: Optional[Dict[int, List[str]]] = None) -> List[Item]:
    """Every item some developer in the map has earned (the pure reading; the Tracker keeps who)."""
    out: List[Item] = []
    for dev, f in facts.items():
        out.extend(earned_for(f, (wins or {}).get(dev, ())))
    return out


def progress(f: Facts, wins: Sequence[str] = (), *, unlocked: Iterable[Tuple[str, str]] = ()) -> List[Dict[str, Any]]:
    """The track as one developer sees it: every item with its condition, progress (n of m), and whether it is unlocked."""
    have = set(unlocked)
    out = []
    for it in TRACK:
        done, n, of = _measure(it, f, wins)
        out.append({"kind": it.kind, "key": it.key, "tier": it.tier, "side": it.side, "condition": it.sentence,
                    "unlocked": (it.kind, it.key) in have, "progress": {"n": min(n, of), "of": of},
                    "later": it.later})
    return out


# --- the tracker: the one writer ------------------------------------------------------------------------------------------

class Tracker:
    """Writes the unlock rows. `store` offers load(ids) -> (changes, reviews, ballots) (only the rows of those developers: what they proposed,
    reviewed and voted on; None = everything), season_counts() -> (quarter, developer, merged, last merge) for the closed-quarter wins,
    existing(ids) -> {(dev, kind, key)} and insert(rows). A row exists once: a second run writes nothing."""

    def __init__(self, store: Any) -> None:
        self.s = store

    async def evaluate(self, developer_ids: Optional[Iterable[int]], *, source: str, now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
        now = now or dt.datetime.now(UTC)
        ids = None if developer_ids is None else {int(d) for d in developer_ids if d is not None}
        changes, reviews, ballots = await self.s.load(ids)
        facts = facts_from(changes, reviews, ballots)
        wins = season_wins_from(await self.s.season_counts(), now)
        devs = set(facts) if ids is None else set(facts) & ids
        devs |= set(wins)                                    # the winners of closed quarters join EVERY evaluation: the crown never waits for their next step
        if not devs:
            return []
        have = await self.s.existing(devs)
        rows: List[Dict[str, Any]] = []
        for dev in sorted(devs):
            f, w = facts.get(dev, Facts()), wins.get(dev, [])
            times = unlock_times(changes, reviews, ballots, dev) if source == "backfill" else {}
            for it in earned_for(f, w):
                if (dev, it.kind, it.key) in have:
                    continue
                src = f"season:{w[it.n - 1]}" if it.cond == "seasons" else source
                at = _quarter_end(w[it.n - 1]) if it.cond == "seasons" and source == "backfill" else times.get((it.kind, it.key), now)
                rows.append({"developer_id": dev, "kind": it.kind, "item_key": it.key, "tier": it.tier,
                             "unlocked_at": at, "source": src})
        if rows:
            await self.s.insert(rows)
        return rows

    async def backfill(self, *, now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
        """Once, as a script (never at boot): every developer the governed-code tables name. Every condition reads those tables, so a backfill
        finds what the rows already prove, each unlock stamped with the time of its event (unlock_times)."""
        return await self.evaluate(None, source="backfill", now=now)


# --- reads for the routes (no writes) -------------------------------------------------------------------------------------

def item_for(kind: str, key: str) -> Optional[Item]:
    return next((i for i in TRACK if i.kind == kind and i.key == key), None)


async def unlocked_set(db: Any, developer_id: int) -> Set[Tuple[str, str]]:
    """(kind, key) of what this developer has earned."""
    return {(k, i) for (_, k, i) in await DbTrackStore(db).existing([developer_id])}


async def require_unlocked(db: Any, developer_id: int, kind: str, key: str) -> None:
    """403 with the sentence of what unlocks the item, unless the developer holds its unlock row. Earning is the only gate: a flare tier
    bought or granted does not open an earned item, and an earned item needs no tier."""
    from fastapi import HTTPException
    if (kind, key) in await unlocked_set(db, developer_id):
        return
    it = item_for(kind, key)
    how = it.sentence if it else "It is earned through governed-code work."
    raise HTTPException(403, f"You have not unlocked the '{key}' {'title' if kind == 'title' else 'ring' if kind == 'encirclement' else 'badge'} yet. {how}")


def public_track() -> Dict[str, Any]:
    """The track itself, with no developer in it: every item, its tier, its condition, and why it cannot be earned yet."""
    return {"items": [{"kind": i.kind, "key": i.key, "tier": i.tier, "side": i.side, "condition": i.sentence, "later": i.later}
                      for i in TRACK],
            "seasons": "a season is a calendar quarter (UTC); the top contributor is the one with the most merged changes, a tie goes to "
                       "the earlier last merge; a season is decided once it is closed, and only when the winner merged at least three changes "
                       "in it and at least two people merged something: otherwise nobody wins that quarter",
            "rules": ["only governed-code work counts", "nothing is bought, granted by hand or transferred", "no value moves"]}


async def view_for(db: Any, developer_id: int, *, equipped_title: Optional[str] = None, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """One developer's track (their own page): every item with progress and unlock state. Reads only."""
    now = now or dt.datetime.now(UTC)
    store = DbTrackStore(db)
    changes, reviews, ballots = await store.load({developer_id})
    facts = facts_from(changes, reviews, ballots).get(developer_id, Facts())
    wins = season_wins_from(await store.season_counts(), now).get(developer_id, [])
    have = {(k, i): t for (_, k, i), t in [((d, k, i), None) for (d, k, i) in await store.existing([developer_id])]}
    return {"items": progress(facts, wins, unlocked=set(have)), "equipped_title": equipped_title, "season_wins": wins,
            "counts": {"proposals": facts.proposals, "reviews": facts.reviews, "merged": facts.merged, "ballots": facts.ballots}}


async def public_view_for(db: Any, developer_id: int, *, equipped_title: Optional[str] = None) -> Dict[str, Any]:
    """A developer's public face: what they have unlocked and the title they wear. Never progress, never counts."""
    from sqlalchemy import select
    from .. import models as m
    rows = (await db.execute(select(m.CosmeticUnlock.kind, m.CosmeticUnlock.item_key, m.CosmeticUnlock.tier)
                             .where(m.CosmeticUnlock.developer_id == developer_id).order_by(m.CosmeticUnlock.id))).all()
    return {"developer_id": developer_id, "unlocked": [{"kind": k, "key": i, "tier": t} for k, i, t in rows], "title": equipped_title}


# --- the database --------------------------------------------------------------------------------------------------------

class DbTrackStore:
    """The store on the registry database. THE ONLY INSERT of cosmetic_unlocks lives here. Reads and writes join the caller's session and
    do not commit: the caller's step commits (one transaction)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def load(self, developer_ids: Optional[Set[int]]):
        """The governed-code rows the facts of these developers need and no others: the changes they proposed or reviewed, the reviews they
        wrote or that were written on their changes (a change's review commits are read for its first-commit fact), and the ballots they cast.
        None reads everything (the backfill). The closed quarters' winners come from season_counts(), never from these rows."""
        from sqlalchemy import func, or_, select
        from .. import models as m
        ids = None if developer_ids is None else sorted(int(d) for d in developer_ids)
        q_ch = select(m.CodeChange)
        if ids is not None:
            reviewed = select(m.CodeChangeReview.code_change_id).where(m.CodeChangeReview.reviewer_developer_id.in_(ids))
            q_ch = q_ch.where(or_(m.CodeChange.proposer_developer_id.in_(ids), m.CodeChange.id.in_(reviewed)))
        ch = (await self.db.execute(q_ch)).scalars().all()
        votes: Dict[int, Tuple[int, int]] = {}
        pids = [c.proposal_id for c in ch if c.proposal_id is not None and c.passed_at is not None]
        if pids:
            rows = (await self.db.execute(select(m.Vote.proposal_id, m.Vote.vote, func.count())
                                          .where(m.Vote.proposal_id.in_(pids)).group_by(m.Vote.proposal_id, m.Vote.vote))).all()
            for pid, vote, n in rows:
                a, b = votes.get(pid, (0, 0))
                votes[pid] = (a + n, b) if vote else (a, b + n)
        changes = []
        for c in ch:
            merged = c.merged or {}
            at = None
            if merged.get("at"):
                try:
                    at = dt.datetime.fromisoformat(str(merged["at"]).replace("Z", "+00:00"))
                except ValueError:
                    at = None
            vf, va = votes.get(c.proposal_id, (0, 0))
            acc = (c.acceptance or {}).get("record") or {}
            changes.append({"id": c.id, "proposer_developer_id": c.proposer_developer_id, "state": c.state, "sensitive": bool(c.sensitive),
                            "paths": list(c.paths or []), "merged_at": at, "passed": c.passed_at is not None,
                            "votes_for": vf, "votes_against": va, "created_at": c.created_at, "passed_at": c.passed_at, "commit": c.commit, "title": c.title,
                            "merged_commit": merged.get("commit"), "acceptance_commit": acc.get("commit")})
        q_rv = select(m.CodeChangeReview.code_change_id, m.CodeChangeReview.reviewer_developer_id,
                      m.CodeChangeReview.verdict, m.CodeChangeReview.commit, m.CodeChangeReview.created_at)
        if ids is not None:
            mine = select(m.CodeChange.id).where(m.CodeChange.proposer_developer_id.in_(ids))
            q_rv = q_rv.where(or_(m.CodeChangeReview.reviewer_developer_id.in_(ids), m.CodeChangeReview.code_change_id.in_(mine)))
        rv = (await self.db.execute(q_rv.order_by(m.CodeChangeReview.id))).all()
        reviews = [{"change_id": a, "reviewer_developer_id": b, "verdict": c, "commit": k, "created_at": t} for a, b, c, k, t in rv]
        q_bl = (select(m.Agent.creator_developer_id, m.Vote.proposal_id, m.GovernanceProposal.tally_quorum_met, m.Vote.created_at)
                .join(m.Vote, m.Vote.voter_did == m.Agent.did)
                .join(m.GovernanceProposal, m.GovernanceProposal.id == m.Vote.proposal_id)
                .where(m.GovernanceProposal.proposal_type == "code_change"))
        if ids is not None:
            q_bl = q_bl.where(m.Agent.creator_developer_id.in_(ids))
        bl = (await self.db.execute(q_bl)).all()
        ballots = [{"voter_developer_id": d, "proposal_id": p, "quorum_met": q, "created_at": t} for d, p, q, t in bl]
        return changes, reviews, ballots

    async def season_counts(self) -> List[Tuple[str, int, int, dt.datetime]]:
        """(quarter, developer, merged changes, last merge) for every developer and quarter: ONE grouped query over the merged changes, so
        the closed quarters' winners never need the whole table in memory. A merged change whose time is not an ISO time is not counted."""
        from sqlalchemy import DateTime, cast, func, select
        from .. import models as m
        at_text = m.CodeChange.merged["at"].as_string()
        at = cast(at_text, DateTime(timezone=True))
        quarter = func.date_trunc("quarter", func.timezone("UTC", at))
        rows = (await self.db.execute(
            select(quarter, m.CodeChange.proposer_developer_id, func.count(), func.max(at))
            .where(m.CodeChange.state == "merged", at_text.op("~")(r"^\d{4}-\d{2}-\d{2}T"))
            .group_by(quarter, m.CodeChange.proposer_developer_id))).all()
        return sorted((f"{q.year}Q{(q.month - 1) // 3 + 1}", dev, int(n), last) for q, dev, n, last in rows if q is not None and dev is not None)

    async def existing(self, developer_ids: Iterable[int]) -> Set[Tuple[int, str, str]]:
        """V0667 the passport: a negative id is a contributor from another registry (services/code_passport.contributor_key), whose
        unlocks live in code_contributor_unlocks (cosmetic_unlocks references developers); answered under the same negative id."""
        from sqlalchemy import select
        from .. import models as m
        ids = list(developer_ids)
        q = select(m.CosmeticUnlock.developer_id, m.CosmeticUnlock.kind, m.CosmeticUnlock.item_key)
        if ids:
            q = q.where(m.CosmeticUnlock.developer_id.in_([i for i in ids if i > 0]))
        out = {(d, k, i) for d, k, i in (await self.db.execute(q)).all()}
        elsewhere = [-i for i in ids if i < 0]
        if elsewhere or not ids:
            U = m.CodeContributorUnlock
            qc = select(U.contributor_id, U.kind, U.item_key)
            if ids:
                qc = qc.where(U.contributor_id.in_(elsewhere))
            out |= {(-c, k, i) for c, k, i in (await self.db.execute(qc)).all()}
        return out

    async def insert(self, rows: List[Dict[str, Any]]) -> None:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from .. import models as m
        mine = [r for r in rows if r["developer_id"] > 0]
        if mine:
            stmt = pg_insert(m.CosmeticUnlock).values(mine).on_conflict_do_nothing(index_elements=["developer_id", "kind", "item_key"])
            await self.db.execute(stmt)
        elsewhere = [{**{k: v for k, v in r.items() if k != "developer_id"}, "contributor_id": -r["developer_id"]}
                     for r in rows if r["developer_id"] < 0]
        if elsewhere:                                                 # V0667: a contributor from another registry (see existing())
            await self.db.execute(pg_insert(m.CodeContributorUnlock).values(elsewhere)
                                  .on_conflict_do_nothing(index_elements=["contributor_id", "kind", "item_key"]))


async def track_ballot(db: Any, proposal_id: int, voter_did: str) -> List[Dict[str, Any]]:
    """The call the vote route makes once a vote is stored: when the proposal is a code change, its voter's developer is evaluated at once,
    so "N ballots cast" counts the moment a vote is cast, passed or not. Commits what it wrote; never raises into the vote."""
    try:
        from sqlalchemy import select
        from .. import models as m
        kind = (await db.execute(select(m.GovernanceProposal.proposal_type).where(m.GovernanceProposal.id == proposal_id))).scalar_one_or_none()
        if kind != "code_change":
            return []
        dev = (await db.execute(select(m.Agent.creator_developer_id).where(m.Agent.did == voter_did))).scalar_one_or_none()
        if dev is None:
            return []
        rows = await track_event(db, [dev], f"ballot:{proposal_id}")
        await db.commit()
        return rows
    except Exception:                                                # noqa: BLE001
        logger.warning("[track] ballot evaluation failed for proposal %s", proposal_id, exc_info=True)
        return []


async def track_event(db: Any, developer_ids: Iterable[int], source: str) -> List[Dict[str, Any]]:
    """The call the governed-code store makes inside a step's transaction (before its commit). Never raises into the step: a failure here is
    logged and the step goes on (a cosmetic must not hold a merge hostage); the backfill repairs a missed one."""
    ids = [d for d in developer_ids if d is not None]
    if not ids:
        return []
    try:
        async with db.begin_nested():                                # a savepoint: a failure here cannot poison the step's transaction
            return await Tracker(DbTrackStore(db)).evaluate(ids, source=source)
    except Exception:                                                # noqa: BLE001
        logger.warning("[track] unlock evaluation failed for %s (%s)", ids, source, exc_info=True)
        return []
