"""V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79; sessionlogs2026/DESIGN_2026-11-13_GOVERNED_CODE.md
with his decisions D1 to D8, room seq 3108): a change to the code base proposed, delivered, checked, reviewed, voted on
by the frame's members and merged on the ballot's result.

The flow, and where each step lives:
  1. Propose: a member's agent names a repository, the paths, the problem, and either a branch it wrote or a bounty.
     A bounty is a normal Guild order (routers/guild.post_order: the existing escrow; no new money path).
  2. Deliver: a worker bids, is awarded and hands in its commits through the Guild, as for any order.
  3. Accept: an independent platform admin posts the HOST CHECKER's signed record for a commit (V0664,
     services/code_change_checker: the checker reads the repository on the host, the CI state of that exact commit, the
     paths it touches against a release branch, a secret scan of their text, and signs; the frame holds only its public
     key, so no repository credential lives on any frame). The registry verifies it, checks its facts
     (acceptance_verdict) and keeps it whatever it says. The paths the commit touches decide whether the change is
     sensitive; a failing check voids an earlier acceptance and an open ballot (F5); an older record never replaces a
     newer one.
  4. Review: independent members approve or ask for changes on that commit (reviews_verdict), before the ballot.
  5. Vote: the server opens a governance proposal of type code_change (as the federation ballot is opened), the frame
     policy's thresholds (thresholds); members vote and the existing auto tally closes it.
  6. Veto and merge: his veto and his go during the beta (D4), his alone (CODE_CHANGES_MAINTAINER; F3); a session
     records the merge of the voted commit into a release branch that holds it, on the checker's signed word that it
     does (merge_allowed: the reviewed tree is the merged tree, D6; CODE_CHANGES_RELEASE_BRANCHES, F8). The money follows
     the record through the Guild (slice 2).
This module holds the rules (pure) and the record's reads and writes; routers/code_changes holds the routes.

The first phase's limits (D5): only the open prefixes (CODE_CHANGE_OPEN_PATHS, default the console, whose doc folder is
the documentation's one source); never a secret, a key, a build or a dependency file; a change touching auth, admin,
money or federation trust is sensitive: two approving reviews and the policy_change pair of thresholds (D3).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import code_change_checker

REPOSITORY = "theprotocol/AgentVault"
CONSOLE_PREFIX = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/"
DEFAULT_OPEN_PATHS: Dict[str, List[str]] = {REPOSITORY: [CONSOLE_PREFIX]}
MAX_PATHS = 50
MAX_PATH_LEN = 300
DEFAULT_VETO_HOURS = 24          # session-lead, room seq 3407: 24 h after PASSED, or his explicit go

# never open to a vote in this phase: secrets and keys, and the files that decide what code runs or what it depends on
_FORBIDDEN = re.compile(
    r"(^|/)\.env|\.pem$|\.key$|\.p12$|\.crt$|secret|credential|password|(^|/)keys?/|"
    r"(^|/)package(-lock)?\.json$|(^|/)\.npmrc$|(^|/)Dockerfile|(^|/)vite\.config|(^|/)tsconfig[^/]*\.json$",
    re.IGNORECASE)
# THE POLICY BACKSTOP (V0666 OPA phase 2 step 1, close R1; DESIGN_2026-11-15_OPA_BACKSTOP.md sections 3 and 10): never open
# to a vote or a distribution line, by name and whatever CODE_CHANGE_OPEN_PATHS says (the narrow default open set is a
# default, not a gate). OPA's policies; the code that asks OPA and keeps its answer; the simulator whose replay is a policy
# change's proof; this rail's own guard with the gate's files (catch B: otherwise a governed change could edit its own
# guard or list itself as an exception); and layer C's independent verifier, its rules and its tests (V0666 step 2: a verifier a
# change could edit is not a third party). They change only on the platform maintainer's approval card.
_BACKSTOP = re.compile(
    r"(^|/)identity-fabric/|\.rego$|"
    r"(^|/)agentvault_registry/(opa_shadow|opa_client|security)\.py$|"
    r"(^|/)agentvault_registry/middleware/|(^|/)agentvault_registry/core/[^/]*_gate\.py$|"
    r"(^|/)agentvault_registry/routers/(admin_opa|code_changes|code_distributions)\.py$|"
    r"(^|/)agentvault_registry/services/(code_changes|code_change_checker|code_distributions)\.py$|"
    r"(^|/)agentvault_registry/verifier/|"
    r"(^|/)tests/(test_opa_decision_gate_v0666|test_opa_backstop_paths_v0666)\.py$|(^|/)tests/opa_gate/|"
    r"(^|/)tests/(test_opa_verifier\w*|_opa_verifier_facts)\.py$")
_BACKSTOP_WHY = ("the policy backstop: OPA's policies, the code that asks them and this rail's own guard change only on the "
                 "platform maintainer's approval card, never by a vote")
# a change here needs a second reviewer and the policy_change thresholds (D3): auth, admin, money, federation trust
_SENSITIVE = re.compile(
    r"auth|admin|wallet|fiat|treasury|payment|escrow|stake|bond|federation|signing|(^|/)router/|"
    r"services/api/client\.ts$|safeUrl",
    re.IGNORECASE)
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

STATES = ("proposed", "accepted", "balloting", "passed", "failed", "vetoed", "merged", "withdrawn")
# slice 2: why a bounty returns (the Guild's cancelled event and the bidders' notice carry it)
RETURN_REASONS = {"failed": "the members' ballot did not pass", "vetoed": "the maintainer vetoed the merge",
                  "withdrawn": "the change was withdrawn"}
ACTIVE_STATES = ("proposed", "accepted", "balloting", "passed")
# V0666 (gwo_b4ab7b9b7b3595d6dad05e6b): the states whose order's money the code-change sweep owns besides the active ones: a
# failed change's bounty is returned by the sweep, or held for the bootstrap go, so the Guild reaper never takes its order
# for an abandoned one
SWEEP_OWNED_STATES = ACTIVE_STATES + ("failed",)
MAX_TOUCHED = 100                # the checker reports too_many_touched at this many files (a compare may be cut short)


# --- paths -------------------------------------------------------------------------------------------------------

def open_paths() -> Dict[str, List[str]]:
    raw = (os.getenv("CODE_CHANGE_OPEN_PATHS") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and all(isinstance(v, list) for v in parsed.values()):
                return {str(k): [str(p) for p in v] for k, v in parsed.items()}
        except ValueError:
            pass
    return DEFAULT_OPEN_PATHS


@dataclass
class PathCheck:
    ok: bool
    reason: Optional[str] = None
    sensitive: bool = False
    paths: List[str] = field(default_factory=list)


def _malformed(p: Any) -> bool:
    if not isinstance(p, str) or not p or len(p) > MAX_PATH_LEN:
        return True
    if p.startswith("/") or "\\" in p or "//" in p:
        return True
    return any(seg in ("..", ".") for seg in p.split("/"))


def is_backstop(path: str) -> bool:
    return bool(_BACKSTOP.search(path))


def is_forbidden(path: str) -> bool:
    return bool(_FORBIDDEN.search(path)) or is_backstop(path)


def is_sensitive(path: str) -> bool:
    return bool(_SENSITIVE.search(path))


def check_paths(repository: str, paths: Sequence[Any]) -> PathCheck:
    """Whether a change may name these paths in this phase, and whether it is sensitive. Refusals say why."""
    prefixes = open_paths().get(repository)
    if prefixes is None:
        return PathCheck(False, f"the repository {repository!r} is not open to proposals in this phase")
    if not paths:
        return PathCheck(False, "no paths: name the files or directories the change touches")
    if len(paths) > MAX_PATHS:
        return PathCheck(False, f"more than {MAX_PATHS} paths")
    if len(set(paths)) != len(paths):
        return PathCheck(False, "a path is named twice")
    for p in paths:
        if _malformed(p):
            return PathCheck(False, f"a malformed path: {str(p)[:80]!r} (relative, forward slashes, no '..')")
        if is_backstop(p):
            return PathCheck(False, f"a forbidden path: {p} ({_BACKSTOP_WHY})")
        if is_forbidden(p):
            return PathCheck(False, f"a forbidden path: {p} (secrets, keys, build and dependency files are never voted on)")
        if not any(p == pre.rstrip("/") or p.startswith(pre if pre.endswith("/") else pre + "/") for pre in prefixes):
            return PathCheck(False, f"{p} is not open in this phase (open: {', '.join(prefixes)})")
    return PathCheck(True, None, any(is_sensitive(p) for p in paths), list(paths))


def path_inside(touched: str, declared: Iterable[str]) -> bool:
    """A touched path is a declared file, or sits under a declared directory."""
    for d in declared:
        d = d.rstrip("/")
        if touched == d or touched.startswith(d + "/"):
            return True
    return False


# --- acceptance --------------------------------------------------------------------------------------------------

def acceptance_verdict(repository: str, record: Dict[str, Any], declared: Sequence[str]) -> Tuple[bool, List[str]]:
    """(accepted, reasons): CI green on the commit, every touched path inside the declared paths and open, no secret
    findings. Every reason is listed, not only the first. The record is the server's own (CodeChangeFlow.
    record_acceptance reads it from the repository); the whole-suite figure a caller once asserted is no longer asked
    for (V0663 fixes, F2)."""
    reasons: List[str] = []
    commit = str(record.get("commit") or "")
    if not _SHA.match(commit):
        reasons.append("the commit is not a full commit id")
    ci = record.get("ci") if isinstance(record.get("ci"), dict) else {}
    if str(ci.get("status") or "").lower() != "success":
        reasons.append(f"CI is not green on the tip ({ci.get('status') or 'no status'})")
    touched = record.get("touched") if isinstance(record.get("touched"), list) else []
    if record.get("too_many_touched"):
        reasons.append(f"the commit touches {MAX_TOUCHED} files or more: too many to check in this phase")
    if not touched:
        reasons.append("no touched paths were recorded")
    for t in touched:
        if not isinstance(t, str) or not path_inside(t, declared):
            reasons.append(f"{t} is outside the declared paths")
        if isinstance(t, str) and is_forbidden(t):
            reasons.append(f"{t} is a forbidden path")
        elif isinstance(t, str) and not check_paths(repository, [t]).ok:
            reasons.append(f"{t} is not open in this phase")
    findings = record.get("secret_findings")
    if not isinstance(findings, int) or findings != 0:
        reasons.append(f"the secret scan did not come back clean ({findings!r} finding(s))")
    return (not reasons), reasons


# --- review ------------------------------------------------------------------------------------------------------

@dataclass
class ReviewVerdict:
    ok: bool
    approvals: int
    needed: int
    blockers: List[int]


def reviews_verdict(reviews: Iterable[Dict[str, Any]], commit: str, *, sensitive: bool,
                    excluded: Set[int]) -> ReviewVerdict:
    """Independent reviews of THIS commit: each reviewer's latest word; one asking for changes holds the ballot."""
    latest: Dict[int, Dict[str, Any]] = {}
    for r in reviews:
        dev = r.get("reviewer_developer_id")
        if r.get("commit") != commit or dev is None or dev in excluded:
            continue
        if dev not in latest or (r.get("at") or 0) >= (latest[dev].get("at") or 0):
            latest[dev] = r
    approvals = sorted(d for d, r in latest.items() if r.get("verdict") == "approve")
    blockers = sorted(d for d, r in latest.items() if r.get("verdict") == "changes")
    needed = 2 if sensitive else 1
    return ReviewVerdict(ok=len(approvals) >= needed and not blockers, approvals=len(approvals), needed=needed,
                         blockers=blockers)


# --- the ballot ----------------------------------------------------------------------------------------------------

def thresholds(policy: Dict[str, Any], *, sensitive: bool) -> Tuple[float, float]:
    """(quorum, pass) percent from the frame policy (D3): the policy_change pair for a sensitive change."""
    if sensitive:
        return (float(policy.get("governance.policy_change_quorum_percent", 20.0)),
                float(policy.get("governance.policy_change_pass_percent", 66.0)))
    return (float(policy.get("governance.standard_quorum_percent", 10.0)),
            float(policy.get("governance.standard_pass_percent", 50.0)))


DEFAULT_BOOTSTRAP_MEMBERS = 10   # the maintainer's word, room seq 4404, 4424 and 4431 (V0666): build through Code changes while members are few


DEFAULT_BOOTSTRAP_HOLD_HOURS = 72.0


def bootstrap_hold_hours() -> float:
    """V0666 (gwo_b4ab7b9b7b3595d6dad05e6b): how long a bounty stays in escrow after its ballot failed only for lack of quorum while
    the bootstrap rule applies, counted from the tally, so the maintainer's go can still pass the change and the merge pay its
    worker. Env CODE_CHANGES_BOOTSTRAP_HOLD_HOURS, default 72; 0 returns the bounty at once (the behaviour before); a bad or
    negative value is the default."""
    raw = (os.getenv("CODE_CHANGES_BOOTSTRAP_HOLD_HOURS") or "").strip()
    if not raw:
        return DEFAULT_BOOTSTRAP_HOLD_HOURS
    try:
        h = float(raw)
    except ValueError:
        return DEFAULT_BOOTSTRAP_HOLD_HOURS
    return h if h >= 0 else DEFAULT_BOOTSTRAP_HOLD_HOURS


def bootstrap_members() -> int:
    """The number of REAL members (members that are not the frame's service accounts: services/membership.real_member_ids) below which a change whose
    ballot missed its quorum may pass on the maintainer's go. Env CODE_CHANGES_BOOTSTRAP_MEMBERS, default 10; 0 turns the rule off; a bad value is the default."""
    raw = (os.getenv("CODE_CHANGES_BOOTSTRAP_MEMBERS") or "").strip()
    if not raw:
        return DEFAULT_BOOTSTRAP_MEMBERS
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_BOOTSTRAP_MEMBERS
    return n if n >= 0 else DEFAULT_BOOTSTRAP_MEMBERS


def veto_window_hours() -> int:
    try:
        h = int(os.getenv("CODE_CHANGE_VETO_HOURS", "") or DEFAULT_VETO_HOURS)
    except ValueError:
        return DEFAULT_VETO_HOURS
    return h if h >= 0 else DEFAULT_VETO_HOURS


# --- the merge -----------------------------------------------------------------------------------------------------

def merge_allowed(*, state: str, proposal_status: Optional[str], passed_at: Optional[dt.datetime], now: dt.datetime,
                  vetoed: bool, go: bool, voted_commit: Optional[str], merge_commit: Optional[str],
                  window_hours: int, bootstrap: bool = False) -> Tuple[bool, Optional[str]]:
    """(allowed, why not): the voted commit only, after a PASSED ballot, never after his veto, once his veto window
    has closed or he said go (D4, D6). V0666: a change that passed on the maintainer's go while members were few (bootstrap)
    has no PASSED ballot behind it: the go is its pass."""
    if state == "merged":
        return False, "already merged"
    if vetoed or state == "vetoed":
        return False, "the maintainer vetoed this change"
    if proposal_status != "PASSED" and not bootstrap:
        return False, f"the ballot did not pass ({proposal_status or 'no ballot'})"
    if not merge_commit or merge_commit != voted_commit:
        return False, "only the commit that was voted may be merged (the reviewed tree is the merged tree)"
    if not go:
        if passed_at is None:
            return False, "the ballot's pass time is unknown, so the veto window cannot be counted"
        closes = passed_at + dt.timedelta(hours=window_hours)
        if now < closes:
            return False, f"the maintainer's veto window is open until {closes.isoformat()}"
    return True, None


# --- V0663 fixes (gwo_3b9568ce2782ea55437bcdbc): the maintainer and the release line ---------------------------------

def maintainer() -> Optional[str]:
    """The maintainer's account (F3): his go and his veto during the beta are his alone. A developer id (digits) or the
    account's email; unset, nobody goes, vetoes or records a merge."""
    return (os.getenv("CODE_CHANGES_MAINTAINER") or "").strip() or None


def is_maintainer(actor: Dict[str, Any]) -> bool:
    m = maintainer()
    if not m:
        return False
    if m.isdigit():
        return actor.get("developer_id") == int(m)
    email = str(actor.get("email") or "").strip().lower()
    return bool(email) and email == m.lower()


def release_branches() -> List[str]:
    """The branches a voted commit may be merged into (F8), and the ones a checker's record may have read a commit's
    touched paths against (F1, F2). Comma separated, default main."""
    raw = os.getenv("CODE_CHANGES_RELEASE_BRANCHES") or "main"
    out = [b.strip() for b in raw.split(",") if b.strip()]
    return out or ["main"]


# --- the flow ------------------------------------------------------------------------------------------------------

class CodeChangeRefusal(Exception):
    """A refusal the route answers with its status, a short code and a sentence."""

    def __init__(self, status: int, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.status, self.code, self.sentence = status, code, sentence


def ballot_days() -> int:
    try:
        d = int(os.getenv("CODE_CHANGE_BALLOT_DAYS", "") or 7)
    except ValueError:
        return 7
    return min(max(d, 1), 30)


_LINE_FIELDS = ("code_distribution_id", "ballot_rule", "ballot_ends", "ballot_result", "org_go")
# V0666 D3: the room a line's change is announced in, its card's message and the state that room last saw (the rail's own
# bookkeeping, never shown: a public read names no room; it says only whether the change is announced in one)
_ROOM_FIELDS = ("announce_conversation_id", "announce_message_id", "announce_state")
# V0667 D4: the history a change carries upstream (on the main-line change), and the mark a line's own copy gets once it landed there
_UPSTREAM_FIELDS = ("upstream_of", "provenance", "upstream_since")


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.datetime) else v


# V0668 (order gwo_2d51e1af1b2a21a0bcdff5e7; found retaking journal 55's hero, cc_f2bee2d81b67f9791cb21331): A DECIDED BALLOT'S
# OUTCOME, IN ONE SHAPE FOR THE MAIN LINE AND A LINE'S OWN BALLOT. The record said DID NOT PASS beside its tally while the tally
# knew why; these name the reason, the numbers it was decided on and when it was tallied. Nothing is recounted here: the main
# line reads what crud_governance.tally_proposal kept (mig 0185) and the votes' own weight, a line what its close wrote.
_UNIT_WORDS = {"member": "members' points", "lock": "voting power"}


def _num(x: Any) -> str:
    v = round(float(x), 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0").rstrip(".")


def ballot_outcome(p: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A main-line ballot's outcome from its governance proposal, or None while it is open (or for one cancelled before a
    tally). The reason is the tally's own: quorum_not_met, rejected (quorum met, not enough in favour), passed; a tally that
    kept no numbers (before mig 0185) claims no reason ("unknown") and no tally time."""
    status = str((p or {}).get("status") or "").upper()
    if status not in ("PASSED", "FAILED"):
        return None
    f, a = float(p.get("votes_for") or 0), float(p.get("votes_against") or 0)
    cast = f + a
    met = p.get("tally_quorum_met")
    mode = p.get("tally_weight_mode") if p.get("tally_weight_mode") in _UNIT_WORDS else None
    unit = _UNIT_WORDS.get(mode or "", "weight")
    required = float(p["tally_quorum_required"]) if p.get("tally_quorum_required") is not None else None
    network = float(p["tally_network_power"]) if p.get("tally_network_power") is not None else None
    qp = float(p["quorum_percent"]) if p.get("quorum_percent") is not None else None
    pp = float(p["pass_percent"]) if p.get("pass_percent") is not None else 50.0
    share = round(f * 100.0 / cast, 1) if cast > 0 else None
    if status == "PASSED":
        reason = "passed"
        sentence = (f"passed: {_num(share or 0)} percent in favour of {_num(cast)} {unit} cast"
                    + (f", the quorum of {_num(required)} met" if required is not None else ""))
    elif met is False:
        reason = "quorum_not_met"
        sentence = (f"the ballot missed its quorum: {_num(cast)} of the {_num(required)} {unit} required took part"
                    if required is not None else f"the ballot missed its quorum: {_num(cast)} {unit} took part")
        if qp is not None and network is not None:
            sentence += f" ({_num(qp)} percent of {_num(network)})"
    elif met is True:
        reason = "rejected"
        sentence = (f"the members decided against it: {_num(share or 0)} percent in favour, {_num(pp)} percent needed to pass")
    else:
        reason = "unknown"
        sentence = "the tally kept no reason (it ran before the registry stored one)"
    return {"status": status, "reason": reason, "unit": mode, "took_part": cast, "required": required, "quorum_percent": qp,
            "network": network, "for": f, "against": a, "share_for": share, "pass_percent": pp, "pass_rule": None,
            "tallied_at": _iso(p.get("tallied_at")) if reason != "unknown" else None,
            "ended_at": _iso(p.get("end_timestamp")), "sentence": sentence}


def line_ballot_outcome(res: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A line's own ballot outcome, in the same shape, from the result its close wrote (code_distributions.tally plus
    closed_at): the deciders are the unit; the quorum needs ceil(deciders x percent / 100) of them."""
    if not isinstance(res, dict) or res.get("status") not in ("PASSED", "FAILED"):
        return None
    n, counted = int(res.get("deciders") or 0), int(res.get("counted") or 0)
    yes, no = int(res.get("for") or 0), int(res.get("against") or 0)
    qp = res.get("quorum_percent")
    required = -(-n * int(qp) // 100) if (n and qp is not None) else None
    if res["status"] == "PASSED":
        reason = "passed"
    elif n == 0:
        reason = "no_deciders"
    elif res.get("quorum_met") is False:
        reason = "quorum_not_met"
    else:
        reason = "rejected"
    return {"status": res["status"], "reason": reason, "unit": "deciders", "took_part": counted, "required": required,
            "quorum_percent": qp, "network": n, "for": yes, "against": no,
            "share_for": round(yes * 100.0 / counted, 1) if counted else None, "pass_percent": None,
            "pass_rule": res.get("pass_rule"), "tallied_at": res.get("closed_at"), "ended_at": None,
            "sentence": res.get("sentence")}


def order_spec(repository: str, paths: Sequence[str], problem: str, sensitive: bool) -> str:
    """The Guild order's text for a bounty: what to change, and how the change is decided and paid."""
    lines = ["A governed code change (sessionlogs DESIGN_2026-11-13_GOVERNED_CODE).",
             f"Repository: {repository}", "Paths:", *[f"- {p}" for p in paths], "", "Problem:", problem.strip(), "",
             "Deliver with the Guild submit, naming the repository and the commit. A checker signs what the "
             "repository says of the commit (its CI state, the paths it touches, a secret scan), members who did not write "
             "it review it "
             f"({'two reviewers: a sensitive path' if sensitive else 'one reviewer, two if it touches a sensitive path'}"
             ") and the members' ballot decides it; the order settles once the merge of the voted commit is recorded."]
    return "\n".join(lines)[:8000]


class CodeChangeFlow:
    """The steps of a code change against a store (DbStore on the database; an in-memory one in the tests). Actors are
    dicts: an agent {did, developer_id}, a developer {developer_id}, a platform admin {developer_id, admin: True}."""

    def __init__(self, store: Any) -> None:
        self.s = store

    # -- guards --
    async def _member(self, developer_id: Optional[int]) -> None:
        if not await self.s.member_mode():
            raise CodeChangeRefusal(409, "no_members", "code changes are decided by the members' ballot, and this "
                                                       "registry has no members")
        if developer_id is None or not await self.s.is_member(developer_id):
            raise CodeChangeRefusal(403, "not_a_member", "only a member of this registry may do this")

    @staticmethod
    def _admin(actor: Dict[str, Any]) -> None:
        if not actor.get("admin"):
            raise CodeChangeRefusal(403, "admin_only", "this step is a platform admin's")

    @staticmethod
    def _maintainer(actor: Dict[str, Any]) -> None:
        """F3: his go and his veto during the beta are the maintainer's account's, not any platform admin's."""
        if not maintainer():
            raise CodeChangeRefusal(403, "no_maintainer", "no maintainer is named on this registry "
                                                          "(CODE_CHANGES_MAINTAINER): nobody goes or vetoes")
        if not is_maintainer(actor):
            raise CodeChangeRefusal(403, "not_maintainer", "the go and the veto are the maintainer's alone")

    async def _own_bounty(self, row: Dict[str, Any], order: Optional[Dict[str, Any]]) -> bool:
        """Slice 2 and F6: whether the order would pay the proposer's own developer: its worker, its payee agent, or
        the organization it pays (owned by the proposer's developer)."""
        if not order:
            return False
        mine = row.get("proposer_developer_id")
        if mine is None:
            return False
        for did in (order.get("worker_did"), order.get("payee_did")):
            if did and await self.s.developer_of_agent(did) == mine:
                return True
        org = order.get("payee_org_id")
        return bool(org) and await self.s.org_owner(org) == mine

    async def _row(self, cid: str) -> Dict[str, Any]:
        row = await self.s.get(cid)
        if not row:
            raise CodeChangeRefusal(404, "not_found", "no code change with that id")
        return row

    async def _excluded(self, row: Dict[str, Any]) -> Set[int]:
        out = {row["proposer_developer_id"]}
        if row.get("order_id"):
            order = await self.s.order(row["order_id"])
            worker = (order or {}).get("worker_did")
            dev = await self.s.developer_of_agent(worker) if worker else None
            if dev is not None:
                out.add(dev)
        return out

    async def _line(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """V0666 D1: the code distribution a change belongs to, or None for the main line. A line's change answers 404
        while CODE_DISTRIBUTIONS_ENABLED is off (nothing of a line is served then)."""
        if not row.get("code_distribution_id"):
            return None
        from . import code_distributions as cd
        cd.require_enabled()
        dist = await self.s.distribution(row["code_distribution_id"])
        if not dist:
            raise CodeChangeRefusal(404, "not_found", "no code distribution for this change")
        return dist

    @staticmethod
    def _line_active(dist: Dict[str, Any], step: str) -> None:
        if dist.get("state") != "active":
            raise CodeChangeRefusal(409, "line_paused", f"the platform paused this line ({dist.get('paused_reason')}): "
                                                        f"it takes no {step} until it is resumed")

    async def _line_synced(self, row: Dict[str, Any], dist: Dict[str, Any]) -> Dict[str, Any]:
        """V0666 D1: a line's own ballot closes at its end, or early once EVERY current decider has voted; the result is
        written once (ballot_result), counted by code_distributions.tally on the rule snapshotted at the open."""
        from . import code_distributions as cd
        if row["state"] != "balloting":
            return row
        now = self.s.now()
        ends = row.get("ballot_ends")
        if isinstance(ends, dt.datetime) and ends.tzinfo is None:
            ends = ends.replace(tzinfo=dt.timezone.utc)
        votes = await self.s.distribution_votes(row["id"])
        rule = row.get("ballot_rule") or cd.rule_of(dist)
        who, why = await cd.deciders(self.s, dist, rule)
        at_end = isinstance(ends, dt.datetime) and now >= ends
        if not (at_end or cd.everyone_voted(votes, who)):
            return row
        res = cd.tally(rule, votes, who, why)
        res.update(closed_at=_iso(now), early=not at_end)
        try:
            if res["status"] == "PASSED":
                await self.s.update(row["id"], state="passed", passed_at=now, ballot_result=res, updated_at=now)
            else:
                await self.s.update(row["id"], state="failed", ballot_result=res, updated_at=now)
        except CodeChangeRefusal as r:
            if r.code != "code_change_not_governed_here":        # V0666: a registry that does not govern only READS: the record is shown as it stands
                raise
            return row
        return await self._row(row["id"])

    async def _synced(self, cid: str) -> Dict[str, Any]:
        """The record, moved on by its ballot's result (the existing auto tally closes the proposal)."""
        row = await self._row(cid)
        dist = await self._line(row)
        if dist is not None:
            return await self._line_synced(row, dist)
        if row["state"] == "balloting" and row.get("proposal_id"):
            p = await self.s.proposal(row["proposal_id"])
            try:
                # V0668: the record's own time moves when its ballot's result reaches it (it stood at the ballot's opening)
                if p and p.get("status") == "PASSED":
                    await self.s.update(cid, state="passed", passed_at=p.get("tallied_at") or p.get("end_timestamp"),
                                        updated_at=self.s.now())
                elif p and p.get("status") == "FAILED":
                    await self.s.update(cid, state="failed", updated_at=self.s.now())
            except CodeChangeRefusal as r:
                if r.code != "code_change_not_governed_here":       # V0666: a registry that does not govern only READS: a record it holds is shown as it stands
                    raise
            row = await self._row(cid)
        return row

    # -- the steps --
    async def _governing(self) -> None:
        """V0666: a registry that is not the governing one writes nothing (services/code_authority). The production store enforces it; an in-memory store has no authority."""
        gate = getattr(self.s, "check_governing", None)
        if gate is not None:
            res = gate()
            if hasattr(res, "__await__"):
                await res

    async def propose(self, actor: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()      # V0666: only the governing registry proposes (services/code_authority)
        dist = None
        if body.get("code_distribution") not in (None, ""):
            # V0666 D1: a change into an organization's line: its members propose (never a guest), the line active, its
            # paths inside the line's and the platform's open paths; the frame's members do not decide it
            from . import code_distributions as cd
            cd.require_enabled()
            dist = await self.s.distribution_by_slug(str(body.get("code_distribution")))
            if not dist:
                raise CodeChangeRefusal(404, "not_found", "no code distribution with that name")
            self._line_active(dist, "proposal")
            role = (await self.s.org_members(dist["organization_id"])).get(actor.get("developer_id"))
            if role not in cd.ORG_PROPOSING_ROLES:
                raise CodeChangeRefusal(403, "not_org_member", "a member of the line's organization proposes into it "
                                                               "(not a guest)")
        elif not actor.get("contributor"):
            # V0667 the passport: a contributor from another registry is not a member here; the governing registry verified their
            # home's signed card, their standing and the home's licence before the step (services/code_passport.accept)
            await self._member(actor.get("developer_id"))
        room = str(body.get("room_id") or "").strip() or None
        if room is not None:
            # V0666 D3: a line's change may be announced in one room of the line's organization (its live card and its
            # state lines); checked before anything is written or locked
            if dist is None:
                raise CodeChangeRefusal(409, "main_line_room", "a main-line change is announced on the Code changes page, "
                                                               "not in a room: name a release line to announce in its room")
            why = await self.s.room_refusal(room, actor.get("did"), dist["organization_id"])
            if why:
                raise CodeChangeRefusal(422, "room", why)
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 160:
            raise CodeChangeRefusal(422, "title", "a title of 1 to 160 characters")
        problem = str(body.get("problem") or "").strip()
        if not problem or len(problem) > 6000:
            raise CodeChangeRefusal(422, "problem", "the problem, in 1 to 6000 characters")
        repository = str(body.get("repository") or "")
        pc = check_paths(repository, list(body.get("paths") or []))
        if not pc.ok:
            raise CodeChangeRefusal(422, "path_refused", pc.reason or "a path is refused")
        if dist is not None:
            from . import code_distributions as cd
            why = cd.paths_inside_line(pc.paths, dist)
            if why:
                raise CodeChangeRefusal(422, "path_refused", why)
        bounty, branch, commit = body.get("bounty"), body.get("branch"), body.get("commit")
        has_bounty = bounty not in (None, "", 0)
        has_branch = bool(str(branch or "").strip())
        if has_bounty == has_branch:
            raise CodeChangeRefusal(422, "bounty_or_branch", "either a bounty (the code to be written) or a branch "
                                                             "with its commit (the code written), not both")
        if has_bounty and actor.get("contributor"):
            raise CodeChangeRefusal(422, "contributor_branch_only", "a contributor from another registry proposes a branch with its "
                                                                     "commit: a bounty is posted and paid by this registry's members")
        if has_branch:
            if not _SHA.match(str(commit or "")):
                raise CodeChangeRefusal(422, "bad_commit", "a branch names its full commit id")
            if len(str(branch)) > 200:
                raise CodeChangeRefusal(422, "bad_branch", "a branch name of at most 200 characters")
        else:
            try:
                bounty = float(bounty)
            except (TypeError, ValueError):
                raise CodeChangeRefusal(422, "bounty_or_branch", "the bounty is a positive amount")
            if bounty <= 0:
                raise CodeChangeRefusal(422, "bounty_or_branch", "the bounty is a positive amount")
        order_id = None
        if has_bounty:
            order_id = await self.s.post_bounty_order(
                actor, title=f"Code change: {title}"[:200], spec=order_spec(repository, pc.paths, problem, pc.sensitive),
                bounty=bounty, currency=body.get("currency"))
        cid = "cc_" + secrets.token_hex(12)
        now = self.s.now()
        line = {"code_distribution_id": dist["id"]} if dist is not None else {}
        if room is not None:
            line["announce_conversation_id"] = room
        await self.s.insert({**line,
            "id": cid, "repository": repository, "paths": pc.paths, "title": title, "problem": problem,
            "mode": "branch" if has_branch else "bounty", "branch": str(branch).strip() if has_branch else None,
            "commit": str(commit) if has_branch else None, "order_id": order_id, "proposer_did": actor.get("did"),
            "proposer_developer_id": actor.get("developer_id"), "sensitive": pc.sensitive, "state": "proposed",
            "acceptance": None, "proposal_id": None, "passed_at": None, "veto": None, "go": None, "merged": None,
            "created_at": now, "updated_at": now})
        return await self.view(cid)

    def _verified(self, signed: Any, *, kind: str, cid: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """V0664: the host checker's record, verified against its public key for this change and repository (an
        unsigned body is 422, no key configured is 503, anything else refused is 409, each with its reason)."""
        if not isinstance(signed, dict):
            raise CodeChangeRefusal(422, "unsigned", "send the host checker's signed record (\"signed\")")
        rec, code, why = code_change_checker.verify_record(signed, kind=kind, change_id=cid, repository=row["repository"],
                                                           now=self.s.now())
        if rec is None:
            raise CodeChangeRefusal(503 if code == "no_checker" else 422 if code == "unsigned" else 409, code, why)
        return rec

    async def record_acceptance(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """V0663 fixes (F1, F2, F5, F6) and V0664: an independent platform admin posts the host checker's signed record
        for a commit ({"signed": record}); the frame verifies it (services/code_change_checker) and keeps it whatever it
        says. Nothing else is read from the caller. A record older than the last one taken for this change is refused, so
        a replayed pass cannot undo a later fail. A passing check accepts the commit and sets the change's sensitivity
        from the paths it touches; a failing one voids an earlier acceptance and an open ballot."""
        await self._governing()
        self._admin(actor)
        row = await self._row(cid)
        if actor.get("developer_id") in await self._excluded(row):
            raise CodeChangeRefusal(403, "not_independent", "the proposer and the worker do not ask for the check of "
                                                            "their own change")
        if row["state"] not in ("proposed", "accepted", "balloting"):
            raise CodeChangeRefusal(409, "wrong_state", f"a change in state {row['state']} takes no new acceptance")
        rec = self._verified((body or {}).get("signed"), kind="acceptance", cid=cid, row=row)
        # V0667 follow-up: a LINE's change is built on the line's own branch and merges into it (record_merge), so its record reads it against that branch; the platform's release
        # branches are the main line's rule. A record against the other kind of branch, or another line's, is refused naming the branch this change expects.
        dist = await self._line(row)
        if dist is not None:
            from . import code_distributions as cd
            expected, what = [cd.branch_name(dist)], "the line's branch"
        else:
            expected, what = release_branches(), "a release branch"
        if rec.get("base") not in expected:
            raise CodeChangeRefusal(409, "base", f"the record read the commit against {str(rec.get('base'))[:80]!r}, "
                                                 f"not {what} ({', '.join(expected)})")
        last = code_change_checker.parse_time(((row.get("acceptance") or {}).get("record") or {}).get("issued_at"))
        if last is not None and code_change_checker.parse_time(rec["issued_at"]) <= last:
            raise CodeChangeRefusal(409, "stale_record", "the record is not newer than the last one taken for this "
                                                         "change: ask the checker again")
        commit = str(rec["commit"])
        delivered: Optional[List[str]] = None
        if row["mode"] == "bounty":
            order = await self.s.order(row["order_id"]) if row.get("order_id") else None
            if not order or order.get("status") != "submitted":
                raise CodeChangeRefusal(409, "not_delivered", "the Guild order has no delivery to check yet")
            commits = ((order.get("deliverable") or {}).get("commits") or [])
            delivered = [str(c.get("commit")) for c in commits if isinstance(c, dict)]
            # slice 2 (session-lead, room seq 3523) and F6: a bounty is for someone else's work; a settle would fold the
            # proposer's own reputation from one of their agents to another, or pay their own treasury
            if await self._own_bounty(row, order):
                raise CodeChangeRefusal(409, "own_bounty", "the order pays the proposer's own developer (its worker, "
                                                           "its payee agent or the organization it pays): a bounty "
                                                           "pays someone else's work. Propose your own code as a "
                                                           "branch with its commit, and withdraw this change to take "
                                                           "the bounty back")
        touched = rec.get("touched") if isinstance(rec.get("touched"), list) else []
        kept = {"commit": commit, "ci": {"status": rec.get("ci_state")}, "touched": touched,
                "secret_findings": rec.get("secret_findings"),
                "secret_paths": rec.get("secret_paths") if isinstance(rec.get("secret_paths"), list) else [],
                "too_many_touched": rec.get("too_many_touched") is True, "base": rec.get("base"),
                "issued_at": rec["issued_at"], "checker_kid": rec.get("checker_kid"), "read_from": "checker"}
        ok, reasons = acceptance_verdict(row["repository"], kept, row["paths"])
        if delivered is not None and commit not in delivered:
            ok = False
            reasons.append(f"{commit} is not one the worker delivered")
        now = self.s.now()
        fields: Dict[str, Any] = {"acceptance": {"record": kept, "ok": ok, "reasons": reasons,
                                                 "by": actor.get("developer_id"), "at": _iso(now)},
                                  "updated_at": now}
        if ok and row["state"] == "balloting" and commit != row.get("commit"):
            # a failing check of any commit voids the ballot (below); a passing one of another commit does not move it
            raise CodeChangeRefusal(409, "ballot_open", f"the members are voting on {row.get('commit')}: another "
                                                        f"commit is checked once that ballot ends or is voided")
        if ok:
            touched = kept.get("touched") or []
            fields.update(state="accepted" if row["state"] != "balloting" else "balloting", commit=commit,
                          sensitive=any(is_sensitive(x) for x in list(row["paths"]) + list(touched)))
        elif row["state"] in ("accepted", "balloting"):
            # F5: a failing check of a later commit (or of the voted one) leaves nothing accepted and no ballot open
            if row["state"] == "balloting" and row.get("proposal_id") is not None:
                await self.s.void_proposal(row["proposal_id"])
            fields.update(state="proposed", proposal_id=None)
        await self.s.update(cid, **fields)
        return await self.view(cid)

    async def review(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()
        row = await self._row(cid)
        verdict = body.get("verdict")
        if verdict not in ("approve", "changes"):
            raise CodeChangeRefusal(422, "verdict", "the verdict is approve or changes")
        dev = actor.get("developer_id")
        if dev in await self._excluded(row):
            raise CodeChangeRefusal(403, "not_independent", "the proposer and the worker do not review their own change")
        dist = await self._line(row)
        if dist is not None:
            from . import code_distributions as cd
            if (await self.s.org_members(dist["organization_id"])).get(dev) not in cd.ORG_PROPOSING_ROLES:
                raise CodeChangeRefusal(403, "not_org_member", "another developer of the line's organization reviews "
                                                               "its changes (not a guest)")
        elif not actor.get("contributor"):
            await self._member(dev)          # V0667: a contributor from another registry was verified by code_passport.accept
        if row["state"] != "accepted":
            raise CodeChangeRefusal(409, "wrong_state", "a change is reviewed once its commit is accepted, before its ballot")
        if body.get("commit") != row.get("commit"):
            raise CodeChangeRefusal(409, "not_the_accepted_commit", f"review the accepted commit, {row.get('commit')}")
        findings = str(body.get("findings") or "")[:4000]
        await self.s.add_review({"code_change_id": cid, "reviewer_developer_id": dev, "verdict": verdict,
                                 "commit": row["commit"], "findings": findings, "at": self.s.now().timestamp()})
        return await self.view(cid)

    async def open_ballot(self, actor: Dict[str, Any], cid: str) -> Dict[str, Any]:
        await self._governing()
        row = await self._row(cid)
        if not (actor.get("admin") or (actor.get("did") and actor.get("did") == row.get("proposer_did"))):
            raise CodeChangeRefusal(403, "not_yours", "the proposer or a platform admin opens the ballot")
        if row["state"] != "accepted":
            raise CodeChangeRefusal(409, "wrong_state", f"a ballot opens on an accepted change (this one is {row['state']})")
        if not self._acceptance_holds(row):
            raise CodeChangeRefusal(409, "acceptance", "the checker's record does not hold for the accepted commit: "
                                                       "ask for the check again")
        reviews = await self.s.reviews(cid)
        rv = reviews_verdict(reviews, row["commit"], sensitive=bool(row["sensitive"]), excluded=await self._excluded(row))
        if not rv.ok:
            held = f"; held by reviewer(s) asking for changes: {rv.blockers}" if rv.blockers else ""
            raise CodeChangeRefusal(409, "reviews_short", f"{rv.approvals} of {rv.needed} independent approval(s) on "
                                                          f"the accepted commit{held}")
        dist = await self._line(row)
        if dist is not None:
            # V0666 D1: the line's own ballot, its rule snapshotted now (a later PATCH changes later ballots only); no
            # governance proposal, so the frame's governance tally is not touched
            from . import code_distributions as cd
            self._line_active(dist, "ballot")
            now = self.s.now()
            await self.s.update(cid, state="balloting", ballot_rule=cd.rule_of(dist),
                                ballot_ends=now + dt.timedelta(days=ballot_days()), updated_at=now)
            return await self.view(cid)
        quorum, pass_percent = thresholds(await self.s.frame_policy(), sensitive=bool(row["sensitive"]))
        ends = self.s.now() + dt.timedelta(days=ballot_days())
        diff = {"code_change_id": cid, "repository": row["repository"], "paths": row["paths"], "commit": row["commit"],
                "branch": row.get("branch"), "order_id": row.get("order_id"), "sensitive": bool(row["sensitive"]),
                "acceptance": {"ok": True, "ci": ((row.get("acceptance") or {}).get("record") or {}).get("ci")},
                "reviews": [{"reviewer_developer_id": r["reviewer_developer_id"], "verdict": r["verdict"]}
                            for r in reviews if r.get("commit") == row["commit"]]}
        description = (f"A code change to {row['repository']}, commit {row['commit']}.\n\nProblem: {row['problem']}\n\n"
                       f"Paths: {', '.join(row['paths'])}\n\nChecked against the repository by a signed checker (the CI "
                       f"state of the commit, the paths it touches, a secret scan) and reviewed ({rv.approvals} "
                       f"independent approval(s)). A pass lets a session merge exactly this commit into the release "
                       f"line after the maintainer's veto window; production still goes through the release.")[:6000]
        pid = await self.s.create_proposal(title=f"Code change: {row['title']}"[:200], description=description, diff=diff,
                                           quorum=quorum, pass_percent=pass_percent, ends=ends)
        await self.s.update(cid, state="balloting", proposal_id=pid, updated_at=self.s.now())
        return await self.view(cid)

    async def veto(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()
        self._admin(actor)
        self._maintainer(actor)
        row = await self._synced(cid)
        if row["state"] != "passed":
            raise CodeChangeRefusal(409, "wrong_state", f"only a passed change is vetoed (this one is {row['state']})")
        closes = self._window_closes(row)
        if closes is not None and self.s.now() >= closes:
            raise CodeChangeRefusal(409, "window_closed", f"the veto window closed at {closes.isoformat()}")
        await self.s.update(cid, state="vetoed", updated_at=self.s.now(),
                            veto={"by": actor.get("developer_id"), "at": _iso(self.s.now()),
                                  "reason": str(body.get("reason") or "")[:1000]})
        await self.close_money(cid)
        return await self.view(cid)

    async def withdraw(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Slice 2: the proposer's agent (or a platform admin) takes the change back before the members vote on it;
        a bounty returns to its poster through the Guild."""
        await self._governing()
        row = await self._synced(cid)
        mine = bool(actor.get("did")) and actor.get("did") == row.get("proposer_did")
        if not (actor.get("admin") or mine):
            raise CodeChangeRefusal(403, "not_yours", "the proposer or a platform admin withdraws a change")
        if row["state"] not in ("proposed", "accepted"):
            raise CodeChangeRefusal(409, "wrong_state", f"a change is withdrawn before its ballot (this one is "
                                                        f"{row['state']}: the members decide it now)")
        # F4: as the Guild's cancel, a bounty returns only while its order is open; once a worker has it, the work is
        # theirs to finish. The own-bounty case (a worker or payee of the proposer's own) is the one the acceptance
        # sends to withdraw, so it still returns from awarded or submitted.
        order = await self.s.order(row["order_id"]) if row.get("order_id") else None
        status = (order or {}).get("status")
        if status not in (None, "open", "cancelled", "expired"):
            if not (status in ("awarded", "submitted") and await self._own_bounty(row, order)):
                raise CodeChangeRefusal(409, "work_taken", f"the Guild order is {status}: a worker holds it, so the "
                                                           f"change is not withdrawn (as an order is not cancelled "
                                                           f"once awarded)")
        why = " ".join(str(body.get("reason") or "").split())[:400]
        who = "the proposer" if mine else "a platform admin"
        await self.s.update(cid, state="withdrawn", updated_at=self.s.now())
        await self.close_money(cid, reason=f"{who} withdrew the change" + (f": {why}" if why else ""))
        return await self.view(cid)

    async def go(self, actor: Dict[str, Any], cid: str) -> Dict[str, Any]:
        await self._governing()
        self._admin(actor)
        self._maintainer(actor)
        row = await self._synced(cid)
        if row["state"] == "failed" and row.get("code_distribution_id"):
            raise CodeChangeRefusal(409, "rejected_by_vote", "a line's ballot is its deciders': the go does not "
                                                             "override it (the bootstrap rule is the main line's)")
        if row["state"] == "failed":
            return await self._bootstrap_go(actor, row)
        if row["state"] != "passed":
            raise CodeChangeRefusal(409, "wrong_state", f"only a passed change gets a go, or while the frame has few members one whose "
                                                        f"ballot missed its quorum (this one is {row['state']})")
        await self.s.update(cid, go={"by": actor.get("developer_id"), "at": _iso(self.s.now())}, updated_at=self.s.now())
        return await self.view(cid)

    async def _bootstrap_go(self, actor: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
        """V0666, the bootstrap rule: while the frame has fewer than bootstrap_members() real members, a change whose ballot ended WITHOUT its quorum
        passes on the maintainer's go. The checks and the reviews stay required (re-read now), a ballot the members rejected (quorum met, not enough
        in favour) is never overridden, and the record keeps the count, the threshold and who did vote. At and above the threshold it is off by itself."""
        cid = row["id"]
        p = await self.s.proposal(row["proposal_id"]) if row.get("proposal_id") else None
        if not p or p.get("status") != "FAILED" or p.get("tally_quorum_met") is not False:
            raise CodeChangeRefusal(409, "rejected_by_vote", "this ballot did not fail for lack of a quorum: the members decided, and the go does "
                                                             "not override a ballot the members rejected")
        threshold = bootstrap_members()
        count = getattr(self.s, "real_member_count", None)
        n = await count() if count is not None else None
        if n is None or not n < threshold:
            raise CodeChangeRefusal(409, "bootstrap_closed", f"the frame has {n if n is not None else 'an unknown number of'} real members, not fewer than "
                                                             f"{threshold}: the members' ballot decides")
        if row.get("order_id"):
            # V0666 (gwo_b4ab7b9b): a bounty change passes only while its order still holds the bounty (the hold after the
            # tally, bootstrap_hold_hours); once it went back to its poster, a pass would merge work nobody pays
            order = await self.s.order(row["order_id"]) or {}
            if order.get("status") != "submitted":
                raise CodeChangeRefusal(409, "bounty_returned", f"the bounty of this change was returned to its poster (its order is "
                                                                f"{order.get('status') or 'gone'}): propose the change again, or post a "
                                                                f"new bounty for it")
        if not self._acceptance_holds(row):
            raise CodeChangeRefusal(409, "acceptance", "the checker's record does not hold for the accepted commit: ask for the check again")
        rv = reviews_verdict(await self.s.reviews(cid), row["commit"], sensitive=bool(row["sensitive"]), excluded=await self._excluded(row))
        if not rv.ok:
            held = f"; held by reviewer(s) asking for changes: {rv.blockers}" if rv.blockers else ""
            raise CodeChangeRefusal(409, "reviews_short", f"{rv.approvals} of {rv.needed} independent approval(s) on the accepted commit{held}")
        votes_of = getattr(self.s, "ballot_votes", None)
        voted = await votes_of(row["proposal_id"]) if votes_of is not None else []
        now = self.s.now()
        rec = {"members": n, "threshold": threshold, "by": actor.get("developer_id"), "at": _iso(now), "voted": voted,
               "sentence": f"passed on the maintainer's go: the frame has {n} members, fewer than {threshold}"}
        await self.s.update(cid, state="passed", passed_at=now, updated_at=now,
                            go={"by": actor.get("developer_id"), "at": _iso(now), "bootstrap": rec})
        return await self.view(cid)

    # -- V0667 D4: upstream -------------------------------------------------------------------------------------------------------

    async def _upstream_view(self, cid: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A line change's proposal upstream: the change, its state as the record now reads it, and when it landed (the line's own mark)."""
        found = await self.s.upstream_for(cid)
        if not found:
            return None
        up = await self._synced(found["id"])
        since = row.get("upstream_since") if isinstance(row.get("upstream_since"), dict) else None
        return {"change_id": found["id"], "state": up["state"], "since": since.get("at") if since else None}

    async def propose_upstream(self, actor: Dict[str, Any], cid: str) -> Dict[str, Any]:
        """V0667 D4 (DESIGN section 4): "propose upstream" on a change MERGED in an organization's line. It creates a normal Code change on the
        main line for the same commit, its provenance kept (the line, its ballot and result, its reviews, the checker's record, as they stand now):
        the checker signs the commit again, then the reviews, the frame's ballot or his go, the merge record; nothing is carried over as
        accepted. Who may: the line's deciders (D1's one rule), through one of their agents. A line change goes upstream once. Not a line's own
        work: a pause on the line does not stop it (what the line merged is the main code's to look at)."""
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        from . import code_distributions as cd
        cd.require_enabled()
        row = await self._row(cid)
        dist = await self._line(row)
        if dist is None:
            raise CodeChangeRefusal(409, "main_line", "only a change merged in an organization's release line goes upstream: a main-line "
                                                      "change is already the main code's")
        if row["state"] != "merged":
            raise CodeChangeRefusal(409, "not_merged", f"only a merged change goes upstream (this one is {row['state']})")
        who, why = await cd.deciders(self.s, dist, row.get("ballot_rule"))
        if actor.get("developer_id") not in who:
            raise CodeChangeRefusal(403, "not_a_decider", why or "only the line's deciders propose its merged change upstream (its "
                                                                 "organization's owners and admins and its deciding team's leads)")
        again = await self.s.upstream_for(cid)
        if again:
            raise CodeChangeRefusal(409, "already_upstream", f"this change went upstream as {again['id']} ({again['state']}): a line "
                                                              f"change goes upstream once")
        pc = check_paths(row["repository"], list(row["paths"] or []))
        if not pc.ok:
            raise CodeChangeRefusal(422, "path_refused", f"the main code does not open these paths now: {pc.reason or 'a path is refused'}")
        merged = row.get("merged") if isinstance(row.get("merged"), dict) else {}
        commit = str(merged.get("commit") or row.get("commit") or "")
        if not _SHA.match(commit):
            raise CodeChangeRefusal(409, "no_commit", "the line's record names no merged commit to propose")
        reviews = await self.s.reviews(cid)
        line = (await cd.named(self.s, [dist]))[0]
        provenance = {
            "line": {"id": dist["id"], "slug": line["slug"], "title": line["title"], "base_release": dist["base_release"],
                     "organization_id": dist["organization_id"], "organization_name": line["organization_name"],
                     "branch": line["branch"]},
            "line_change": {"id": cid, "title": row["title"], "problem": row["problem"], "branch": row.get("branch"),
                            "commit": row.get("commit"), "paths": list(row["paths"] or []), "proposer_did": row["proposer_did"],
                            "proposer_developer_id": row["proposer_developer_id"], "merged": row.get("merged")},
            "ballot": {"rule": row.get("ballot_rule"), "ends": _iso(row.get("ballot_ends")), "result": row.get("ballot_result"),
                       "org_go": row.get("org_go")},
            "reviews": [{k: (_iso(r.get(k)) if k == "at" and not isinstance(r.get(k), (int, float)) else r.get(k))
                         for k in ("reviewer_developer_id", "verdict", "commit", "findings", "at")} for r in reviews],
            "checker": row.get("acceptance"),
        }
        ucid = "cc_" + secrets.token_hex(12)
        now = self.s.now()
        note = f"\n\nProposed upstream from the release line {line['title']} ({line['slug']}); its ballot, reviews and the checker's record travel with it."
        problem = (str(row["problem"]).strip()[:6000 - len(note)] + note)
        await self.s.insert({
            "id": ucid, "repository": row["repository"], "paths": pc.paths, "title": str(row["title"])[:160], "problem": problem,
            "mode": "branch", "branch": row.get("branch") or merged.get("into"), "commit": commit, "order_id": None,
            "proposer_did": actor.get("did"), "proposer_developer_id": actor.get("developer_id"), "sensitive": pc.sensitive,
            "state": "proposed", "acceptance": None, "proposal_id": None, "passed_at": None, "veto": None, "go": None, "merged": None,
            "upstream_of": cid, "provenance": provenance, "created_at": now, "updated_at": now})
        await self.s.update(cid, updated_at=now)       # the line's card in its room says it went upstream (a refresh after a committed write)
        return await self.view(ucid)

    async def line_vote(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """V0666 D1: a decider's vote on a line's change, through one of the developer's agents (the main line's agent
        gate, gov.vote, is the route's): one per developer, never changed; counted only if the developer still decides at
        the close."""
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        from . import code_distributions as cd
        row = await self._synced(cid)
        dist = await self._line(row)
        if dist is None:
            raise CodeChangeRefusal(409, "main_line", "a main-line change is decided by the members' governance vote")
        self._line_active(dist, "vote")
        if row["state"] != "balloting":
            raise CodeChangeRefusal(409, "wrong_state", f"the line's ballot is not open (this change is {row['state']})")
        vote = body.get("vote")
        if not isinstance(vote, bool):
            raise CodeChangeRefusal(422, "vote", "the vote is true (for) or false (against)")
        dev = actor.get("developer_id")
        who, why = await cd.deciders(self.s, dist, row.get("ballot_rule"))
        if dev not in who:
            raise CodeChangeRefusal(403, "not_a_decider", why or "only the line's deciders vote (its organization's "
                                                                 "owners and admins and its deciding team's leads)")
        if any(v["developer_id"] == dev for v in await self.s.distribution_votes(cid)):
            raise CodeChangeRefusal(409, "already_voted", "this developer has voted on this change (a vote is not changed)")
        await self.s.add_distribution_vote({"code_change_id": cid, "developer_id": dev, "vote": vote,
                                            "agent_did": actor.get("did"), "cast_at": self.s.now()})
        return await self.view(cid, actor.get("developer_id"))

    async def line_owner_veto(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """V0666 D1: the organization owner's veto inside its line, in the same window as the platform maintainer's."""
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        row, dist = await self._owner_step(actor, cid)
        closes = self._window_closes(row)
        if closes is not None and self.s.now() >= closes:
            raise CodeChangeRefusal(409, "window_closed", f"the veto window closed at {closes.isoformat()}")
        await self.s.update(cid, state="vetoed", updated_at=self.s.now(),
                            veto={"by": actor.get("developer_id"), "as": "organization_owner", "at": _iso(self.s.now()),
                                  "reason": str(body.get("reason") or "")[:1000]})
        await self.close_money(cid)
        return await self.view(cid, actor.get("developer_id"))

    async def line_owner_go(self, actor: Dict[str, Any], cid: str) -> Dict[str, Any]:
        """V0666 D1: the organization owner's go, recorded and shown; it never shortens the platform's veto window (only
        the platform maintainer's go does: session-lead, room seq 4637)."""
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        await self._owner_step(actor, cid)
        await self.s.update(cid, org_go={"by": actor.get("developer_id"), "at": _iso(self.s.now())}, updated_at=self.s.now())
        return await self.view(cid, actor.get("developer_id"))

    async def _owner_step(self, actor: Dict[str, Any], cid: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        row = await self._synced(cid)
        dist = await self._line(row)
        if dist is None:
            raise CodeChangeRefusal(409, "main_line", "the organization owner's go and veto are a line's, not the main line's")
        if actor.get("developer_id") is None or await self.s.org_owner(dist["organization_id"]) != actor.get("developer_id"):
            raise CodeChangeRefusal(403, "not_org_owner", "the line's organization owner goes or vetoes here")
        if row["state"] != "passed":
            raise CodeChangeRefusal(409, "wrong_state", f"only a passed change gets a go or a veto (this one is {row['state']})")
        return row, dist

    async def record_merge(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()
        self._admin(actor)
        if not maintainer():
            raise CodeChangeRefusal(409, "no_maintainer", "no maintainer is named on this registry "
                                                          "(CODE_CHANGES_MAINTAINER): with no veto possible, nothing "
                                                          "merges")
        row = await self._synced(cid)
        dist = await self._line(row)
        p = await self.s.proposal(row["proposal_id"]) if row.get("proposal_id") else None
        commit, into = str(body.get("commit") or ""), str(body.get("into") or "").strip()
        if not into or len(into) > 200:
            raise CodeChangeRefusal(422, "into", "name the branch it was merged into")
        status = (p or {}).get("status")
        if dist is not None:
            from . import code_distributions as cd
            self._line_active(dist, "merge")
            why = cd.paths_inside_line(row["paths"], dist)
            if why:
                raise CodeChangeRefusal(409, "path_refused", f"the change's paths at the merge: {why}")
            status = (row.get("ballot_result") or {}).get("status")
        ok, why = merge_allowed(state=row["state"], proposal_status=status,
                                passed_at=row.get("passed_at"), now=self.s.now(), vetoed=row.get("veto") is not None,
                                go=row.get("go") is not None, voted_commit=row.get("commit"), merge_commit=commit,
                                window_hours=veto_window_hours(), bootstrap=bool((row.get("go") or {}).get("bootstrap")))
        if not ok:
            raise CodeChangeRefusal(409, "merge_refused", why or "the merge is refused")
        if not self._acceptance_holds(row):
            raise CodeChangeRefusal(409, "acceptance", "the checker's record does not hold for the voted commit")
        # F8: the merge names a release branch, and the repository says that branch holds the voted commit; V0664: the
        # host checker says so in a signed release_line record, since the frame reads no repository
        if dist is not None:
            from . import code_distributions as cd
            if into != cd.branch_name(dist):
                raise CodeChangeRefusal(409, "not_release_line", f"a change of this line merges into {cd.branch_name(dist)}")
        elif into not in release_branches():
            raise CodeChangeRefusal(409, "not_release_line", f"{into} is not a release branch "
                                                             f"({', '.join(release_branches())})")
        rec = self._verified((body or {}).get("signed"), kind="release_line", cid=cid, row=row)
        if rec["commit"] != commit:
            raise CodeChangeRefusal(409, "commit", "the checker's record is about another commit than the voted one")
        if rec.get("branch") != into:
            raise CodeChangeRefusal(409, "branch", f"the checker's record is about {str(rec.get('branch'))[:80]!r}, "
                                                   f"not {into!r}")
        if rec.get("contains") is not True:
            raise CodeChangeRefusal(409, "not_on_release_line", f"{into} does not hold {commit}: merge it first, then "
                                                                f"record the merge")
        await self.s.update(cid, state="merged", updated_at=self.s.now(),
                            merged={"commit": commit, "into": into, "by": actor.get("developer_id"),
                                    "at": _iso(self.s.now())})
        if row.get("upstream_of"):
            # V0667 D4: the line's own copy says it is upstream since this change (what the next carry-forward reads); its room's card says so too
            await self.s.update(row["upstream_of"], upstream_since={"change_id": cid, "at": _iso(self.s.now())},
                                updated_at=self.s.now())
        await self.close_money(cid)
        return await self.view(cid)

    # -- slice 2: the money follows the record, through the Guild only --
    async def close_money(self, cid: str, *, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """A merged change settles its order to the worker; a failed, vetoed or withdrawn one returns the bounty to
        its poster. The Guild moves the money (routers/guild.settle_submitted_order, return_order_bounty: its own legs,
        each transition claimed first); this reads the order first and asks only when that order still holds the
        bounty, so a second call moves nothing. A settle the Guild refuses (a cross-registry worker, paid through the
        poster's verify) is kept on the record and tried again by the sweep. None when nothing was asked."""
        row = await self._row(cid)
        oid = row.get("order_id")
        if not oid:
            return None
        order = await self.s.order(oid) or {}
        status = order.get("status")
        actor = f"code-change:{cid}"
        if row["state"] == "merged" and status == "submitted":
            out = await self.s.settle_order(oid, actor=actor)
            await self.s.update(cid, merged={**(row.get("merged") or {}), "settlement": out}, updated_at=self.s.now())
            return out
        if row["state"] in RETURN_REASONS and status in ("open", "awarded", "submitted"):
            if row["state"] == "failed" and await self._bounty_hold_until(row) is not None:
                return None          # held: the maintainer's go may still pass the change (the bootstrap rule)
            return await self.s.return_order(oid, actor=actor, reason=reason or RETURN_REASONS[row["state"]])
        return None

    async def _bounty_hold_until(self, row: Dict[str, Any]) -> Optional[dt.datetime]:
        """V0666 (gwo_b4ab7b9b7b3595d6dad05e6b): until when a failed change's bounty stays in escrow, or None when it is not held.
        Held while all of it is true: the change failed and carries an order that still holds the bounty, its ballot ended
        without its quorum (a rejection is never held: the go never passes it), the bootstrap rule applies now (real members
        below bootstrap_members(), the rule and the hold on), and the hold, counted from the tally, has not run out."""
        if row.get("state") != "failed" or not row.get("order_id") or not row.get("proposal_id"):
            return None
        hours, threshold = bootstrap_hold_hours(), bootstrap_members()
        if hours <= 0 or threshold <= 0:
            return None
        p = await self.s.proposal(row["proposal_id"]) or {}
        if p.get("status") != "FAILED" or p.get("tally_quorum_met") is not False:
            return None
        ended = p.get("tallied_at") or p.get("end_timestamp")
        if not isinstance(ended, dt.datetime):
            return None
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=dt.timezone.utc)
        until = ended + dt.timedelta(hours=hours)
        now = self.s.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
        if now >= until:
            return None
        order = await self.s.order(row["order_id"]) or {}
        if order.get("status") not in ("open", "awarded", "submitted"):
            return None
        count = getattr(self.s, "real_member_count", None)
        n = await count() if count is not None else None
        if n is None or not n < threshold:
            return None
        return until

    @staticmethod
    def _acceptance_holds(row: Dict[str, Any]) -> bool:
        """The server's last check passed, and it was of the commit the change carries (F5)."""
        acc = row.get("acceptance") if isinstance(row.get("acceptance"), dict) else {}
        rec = acc.get("record") if isinstance(acc.get("record"), dict) else {}
        return acc.get("ok") is True and bool(row.get("commit")) and rec.get("commit") == row.get("commit")

    # -- the record, as shown --
    @staticmethod
    def _window_closes(row: Dict[str, Any]) -> Optional[dt.datetime]:
        passed = row.get("passed_at")
        if not isinstance(passed, dt.datetime):
            return None
        if passed.tzinfo is None:
            passed = passed.replace(tzinfo=dt.timezone.utc)
        return passed + dt.timedelta(hours=veto_window_hours())

    async def view(self, cid: str, reader_developer_id: Optional[int] = None) -> Dict[str, Any]:
        """The record in words. V0666 D2: on a line's change, the line's organization by name and the reader's own vote
        (`line_ballot.my_vote`: FOR, AGAINST or None for a reader who has not voted, or nobody signed in); never anyone
        else's vote. A main-line change reads exactly as before."""
        row = await self._synced(cid)
        reviews = await self.s.reviews(cid)
        rv = reviews_verdict(reviews, row.get("commit") or "", sensitive=bool(row["sensitive"]),
                             excluded=await self._excluded(row))
        closes = self._window_closes(row)
        out = {k: _iso(v) for k, v in row.items() if k not in _ROOM_FIELDS}
        for k in _UPSTREAM_FIELDS:               # V0667 D4: a change that is neither upstream nor carried upstream reads as it always did
            if out.get(k) is None:
                out.pop(k, None)
        dist = await self._line(row)
        if dist is None:
            for k in _LINE_FIELDS:               # V0666 D1: a main-line change reads exactly as before
                out.pop(k, None)
        else:
            from . import code_distributions as cd
            votes = await self.s.distribution_votes(cid)
            who, why = await cd.deciders(self.s, dist, row.get("ballot_rule"))
            line = (await cd.named(self.s, [dist]))[0]
            out["code_distribution"] = {k: line[k] for k in ("slug", "title", "release_name", "branch",
                                                             "organization_id", "organization_name", "state", "what")}
            mine = next((v for v in votes if reader_developer_id is not None and v["developer_id"] == reader_developer_id), None)
            out["line_ballot"] = {"rule": row.get("ballot_rule"), "ends": _iso(row.get("ballot_ends")),
                                  "result": row.get("ballot_result"), "votes": len(votes), "deciders_now": len(who),
                                  "deciders_note": why, "my_vote": None if mine is None else ("FOR" if mine["vote"] else "AGAINST"),
                                  # V0666 D3: whether the reader decides this ballot now (D1's deciders, as at the vote)
                                  "i_decide": reader_developer_id is not None and reader_developer_id in who}
            out["announced_in_room"] = bool(row.get("announce_conversation_id"))
            out["upstream"] = await self._upstream_view(cid, row)       # V0667 D4: the proposal upstream and its fate, or None
            # V0666 D3: whether the reader may review (review's own rule: a non-guest member of the organization who
            # neither proposed nor works it); the registry decides again at the review
            out["reader_may_review"] = bool(
                reader_developer_id is not None and reader_developer_id not in await self._excluded(row)
                and (await self.s.org_members(dist["organization_id"])).get(reader_developer_id) in cd.ORG_PROPOSING_ROLES)
        # V0668: a decided ballot's outcome (why, the numbers, when); an open ballot, or a change with none, carries no such key
        outcome = (line_ballot_outcome(row.get("ballot_result")) if dist is not None
                   else ballot_outcome(await self.s.proposal(row["proposal_id"])) if row.get("proposal_id") else None)
        if outcome is not None:
            out["ballot_outcome"] = outcome
        order = await self.s.order(row["order_id"]) if row.get("order_id") else None
        out.update(
            order_status=(order or {}).get("status"),
            settlement=(row.get("merged") or {}).get("settlement") if isinstance(row.get("merged"), dict) else None,
            reviews=[{k: r.get(k) for k in ("reviewer_developer_id", "verdict", "commit", "findings", "at")} for r in reviews],
            reviews_needed=rv.needed,
            review_verdict={"approvals": rv.approvals, "needed": rv.needed, "blockers": rv.blockers, "ok": rv.ok},
            veto_window_hours=veto_window_hours(),
            veto_window_closes_at=closes.isoformat() if closes else None,
            # V0666: a change that passed on the maintainer's go while members were few says so, in words, with the members who did vote
            bootstrap=(row.get("go") or {}).get("bootstrap") if isinstance(row.get("go"), dict) else None)
        # V0666 (gwo_b4ab7b9b): a failed change whose bounty is held for the maintainer's go says until when
        hold = await self._bounty_hold_until(row)
        out["bounty_hold_until"] = hold.isoformat() if hold else None
        names = getattr(self.s, "names", None)
        if names is not None:
            # V0665: the people by name, beside the ids (a store that knows no names reads as it always did)
            pkey = row.get("proposer_developer_id")
            # V0667 the passport: a contributor from another registry (a negative key, services/code_passport.contributor_key) has no agent
            # row here; their name is their contributor row's ("Ada (ASIA)") and they are gone only when that row is
            elsewhere = isinstance(pkey, int) and not isinstance(pkey, bool) and pkey < 0
            agents, devs = await names([row["proposer_did"]], [r.get("reviewer_developer_id") for r in reviews] + ([pkey] if elsewhere else []))
            if elsewhere:
                out["proposer_name"] = devs.get(pkey)
                out["proposer_gone"] = devs.get(pkey) is None
            else:
                out["proposer_name"] = agents.get(row["proposer_did"])
                gone = getattr(self.s, "gone", None)
                # "gone" is the agent itself being gone (no agent row, revoked): an agent with no name to show (its card briefly inactive or unnamed) is not
                out["proposer_gone"] = bool(await gone([row["proposer_did"]])) if gone is not None else out["proposer_name"] is None
            for item in out["reviews"]:
                item["reviewer_name"] = devs.get(item.get("reviewer_developer_id"))
        return out


# --- slice 2: the sweep (the guild order reaper runs it) -------------------------------------------------------------

async def sweep_ended(store: Any) -> int:
    """For every change whose ballot is open or whose money is not yet closed (store.ended()): follow the ballot's
    result, then close the money (CodeChangeFlow.close_money). A failed ballot is seen here, never in a read: a GET
    moves no money. Returns how many money steps moved. One change's failure is logged and the rest go on."""
    import logging
    log = logging.getLogger(__name__)
    flow = CodeChangeFlow(store)
    moved = 0
    rows = list(await store.ended())
    # V0666 D1: a line's open ballots close here too (they carry no governance proposal for the auto tally to close)
    lines = getattr(store, "open_distribution_ballots", None)
    if lines is not None:
        try:
            from . import code_distributions as _cd
            if _cd.enabled():
                seen = {r["id"] for r in rows}
                rows += [r for r in await lines() if r["id"] not in seen]
        except Exception:  # noqa: BLE001
            log.warning("[code-changes] sweep: the lines' open ballots could not be read", exc_info=True)
    for row in rows:
        try:
            await flow._synced(row["id"])
            out = await flow.close_money(row["id"])
            if out and out.get("ok"):
                moved += 1
        except Exception:  # noqa: BLE001
            log.warning("[code-changes] sweep: %s could not be closed", row.get("id"), exc_info=True)
    return moved


# --- the Guild verify waits for the merge --------------------------------------------------------------------------

async def settlement_gate(db: Any, order_id: str) -> None:
    """Called by routers/guild verify before it claims the money (after the quantum gate; session-watch, room seq 3409):
    an order that carries a code change settles only once the merge of the voted commit is recorded. An order that is
    not a code change reads one row and passes. The reject branch of verify (a dispute) is before this and untouched."""
    from fastapi import HTTPException
    from sqlalchemy import text
    row = (await db.execute(text(
        "SELECT id, state FROM code_changes WHERE order_id = :o ORDER BY created_at DESC LIMIT 1"),
        {"o": order_id})).mappings().first()
    if row is None:
        return
    if row["state"] != "merged":
        raise HTTPException(409, detail=(f"this order carries code change {row['id']}: it settles once the merge of "
                                         f"the voted commit is recorded (state now: {row['state']})"))


# --- the store on the database ---------------------------------------------------------------------------------------

def _row_dict(obj: Any) -> Dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def public_developer_name(display_name: Optional[str], developer_id: Optional[int]) -> Optional[str]:
    """A developer's PUBLIC name for a code change's page (read without a session): the display name they chose, else "Member #<id>" (it tells two
    people apart; the ids are public in the flare reads). NEVER the account name, and never an email address (a display name that is one is not shown).
    Nobody to name (no id) is None."""
    c = (display_name or "").strip()
    if c and "@" not in c:
        return c
    return f"Member #{developer_id}" if developer_id is not None else None


class DbStore:
    """CodeChangeFlow's store on the registry database. Writes commit as they go (each step is one act)."""

    async def check_governing(self) -> None:
        """V0666: only the governing registry (CODE_CHANGES_GOVERNING_REGISTRY, services/code_authority) writes through the rail. A refusal names that registry's console as its
        own card publishes it (read from the peer row's cached card), the network manifest the fallback."""
        from .code_authority import require_governing_async
        await require_governing_async(self.db)

    def __init__(self, db: Any, agent: Any = None) -> None:
        self.db, self.agent = db, agent
        self._agent_names: Dict[str, Optional[str]] = {}     # V0665: remembered for this request (a miss is remembered too)
        self._agent_gone: Dict[str, bool] = {}
        self._dev_names: Dict[int, Optional[str]] = {}

    async def names(self, dids: Sequence[str], developer_ids: Sequence[int]) -> Tuple[Dict[str, Optional[str]], Dict[int, Optional[str]]]:
        """V0665: the agents' names (the active card's name, else the latest card's; an agent with no card has none) and the developers' PUBLIC names (the
        display name, else "Member #<id>"), each in ONE statement for whatever this request has not asked yet. Whether an agent is gone is gone()'s."""
        from sqlalchemy import select
        from .. import models
        miss = sorted({d for d in dids if d and d not in self._agent_names})
        if miss:
            named: Dict[str, Tuple[bool, str]] = {}                 # did -> (card is active, name): an active card beats an inactive one
            exists: Dict[str, str] = {}
            for did, status, name, active in (await self.db.execute(
                    select(models.Agent.did, models.Agent.status, models.AgentCard.name, models.AgentCard.is_active)
                    .select_from(models.Agent).outerjoin(models.AgentCard, models.AgentCard.agent_did == models.Agent.did)
                    .where(models.Agent.did.in_(miss))
                    .order_by(models.AgentCard.created_at.desc()))).all():
                exists[did] = status
                if name and (did not in named or (bool(active) and not named[did][0])):
                    named[did] = (bool(active), name)
            for d in miss:
                self._agent_names[d] = named[d][1] if d in named else None
                self._agent_gone[d] = d not in exists or exists[d] == "revoked"
        missd = sorted({i for i in developer_ids if i is not None and i not in self._dev_names})
        if missd:
            got = {i: public_developer_name(dn, i) for i, dn in (await self.db.execute(
                select(models.Developer.id, models.Developer.display_name).where(models.Developer.id.in_([i for i in missd if i > 0])))).all()}
            # V0667 the passport: a negative id is a contributor from another registry (services/code_passport.contributor_key): their
            # public name and their home, never an account name ("Ada (ASIA)"; no name chosen: "Member #<their id at home> (ASIA)")
            elsewhere = [-i for i in missd if i < 0]
            if elsewhere:
                C = models.CodeContributor
                for cid, dn, home, ref in (await self.db.execute(select(C.id, C.display_name, C.home_registry, C.home_developer_id)
                                                                 .where(C.id.in_(elsewhere)))).all():
                    got[-cid] = f"{public_developer_name(dn, ref)} ({home})"
            for i in missd:
                self._dev_names[i] = got.get(i)
        return ({d: self._agent_names.get(d) for d in dids}, {i: self._dev_names.get(i) for i in developer_ids})

    async def gone(self, dids: Sequence[str]) -> Set[str]:
        """V0665: which of these agents are gone: no agent row at all, or revoked by the registry. A card that is inactive or has no name is not a gone agent."""
        await self.names(list(dids), [])
        return {d for d in dids if self._agent_gone.get(d)}

    async def prefetch(self, rows: Sequence[Dict[str, Any]]) -> None:
        """V0665: before a list of cards is viewed, read every name any of them will ask for: the reviewers' ids in one statement, then the names
        in two. A view of each card then finds its names remembered."""
        from sqlalchemy import select
        from .. import models
        ids = [r["id"] for r in rows if r.get("id")]
        reviewers: List[int] = []
        if ids:
            reviewers = [r[0] for r in (await self.db.execute(select(models.CodeChangeReview.reviewer_developer_id)
                                                              .where(models.CodeChangeReview.code_change_id.in_(ids)))).all()]
        await self.names([r["proposer_did"] for r in rows if r.get("proposer_did")], reviewers)

    async def real_member_count(self) -> int:
        """V0666: the members that are not the frame's service accounts (services/membership.real_member_count: the one place that says who is real)."""
        from . import membership
        return await membership.real_member_count(self.db)

    async def ballot_votes(self, proposal_id: int) -> List[Dict[str, Any]]:
        """V0666: who voted on a ballot, by developer (the vote's agent's creator), in the order they voted: the record of a bootstrap pass keeps it."""
        from sqlalchemy import select
        from .. import models
        rows = (await self.db.execute(select(models.Agent.creator_developer_id, models.Vote.vote)
                                      .join(models.Agent, models.Agent.did == models.Vote.voter_did)
                                      .where(models.Vote.proposal_id == proposal_id).order_by(models.Vote.id))).all()
        return [{"developer_id": d, "vote": bool(v)} for d, v in rows]

    async def member_mode(self) -> bool:
        from . import membership
        return membership.member_mode()

    async def is_member(self, developer_id: int) -> bool:
        from . import membership
        return (await membership.weight_points_for(self.db, developer_id)) > 0

    async def developer_of_agent(self, did: str) -> Optional[int]:
        from sqlalchemy import select
        from .. import models
        return (await self.db.execute(select(models.Agent.creator_developer_id)
                                      .where(models.Agent.did == did))).scalar_one_or_none()

    async def post_bounty_order(self, actor: Dict[str, Any], *, title: str, spec: str, bounty: float,
                                currency: Optional[str]) -> str:
        """A normal Guild order through the Guild's own post_order: its escrow, its fee, its board."""
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from ..routers.guild import OrderPostIn, post_order
        out = await post_order(OrderPostIn(title=title, spec=spec, bounty=bounty, currency=currency),
                               agent=self.agent, db=self.db)
        return out["order_id"]

    async def settle_order(self, oid: str, *, actor: str) -> Dict[str, Any]:
        """Slice 2: the Guild settles a submitted order to its worker (routers/guild.settle_submitted_order); a 409
        (not submitted, a cross-registry worker) is said, nothing moved."""
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from fastapi import HTTPException
        from ..routers.guild import settle_submitted_order
        try:
            out = await settle_submitted_order(self.db, oid, actor=actor, via="governed_code")
        except HTTPException as e:
            if e.status_code != 409:
                raise
            return {"ok": False, "why": str(e.detail)}
        return {"ok": True, "status": out.get("status"), "payout": out.get("payout"), "payee": out.get("payee")}

    async def return_order(self, oid: str, *, actor: str, reason: str) -> Dict[str, Any]:
        """Slice 2: the Guild returns the escrowed bounty to the poster (routers/guild.return_order_bounty); a 409
        (nothing held) is said, nothing moved."""
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from fastapi import HTTPException
        from ..routers.guild import return_order_bounty
        try:
            out = await return_order_bounty(self.db, oid, actor=actor, via="governed_code", reason=reason)
        except HTTPException as e:
            if e.status_code != 409:
                raise
            return {"ok": False, "why": str(e.detail)}
        return {"ok": True, "status": out.get("status"), "refund": out.get("refund")}

    async def ended(self) -> List[Dict[str, Any]]:
        """The changes the sweep looks at: a ballot still open, or an order that still holds a bounty the record
        says should move (merged and submitted; failed, vetoed or withdrawn and not yet returned)."""
        from sqlalchemy import text
        rows = (await self.db.execute(text(
            "SELECT c.id FROM code_changes c JOIN guild_work_orders o ON o.id = c.order_id "
            "WHERE c.state = 'balloting' "
            "OR (c.state = 'merged' AND o.status = 'submitted') "
            "OR (c.state IN ('failed', 'vetoed', 'withdrawn') AND o.status IN ('open', 'awarded', 'submitted')) "
            "ORDER BY c.created_at LIMIT 100"))).mappings().all()
        return [dict(r) for r in rows]

    async def order(self, oid: str) -> Optional[Dict[str, Any]]:
        from sqlalchemy import text
        row = (await self.db.execute(text(
            "SELECT id, status, worker_did, payee_did, payee_org_id, deliverable FROM guild_work_orders WHERE id = :o"),
            {"o": oid})
        ).mappings().first()
        return dict(row) if row else None

    # -- V0663 fixes (gwo_3b9568ce2782ea55437bcdbc) --
    async def org_owner(self, org_id: str) -> Optional[int]:
        """F6: the developer who owns an organization (a bounty paying it pays them)."""
        from sqlalchemy import select
        from .. import models
        return (await self.db.execute(select(models.Organization.owner_id)
                                      .where(models.Organization.id == org_id))).scalar_one_or_none()

    async def void_proposal(self, pid: int) -> None:
        """F5: a failing check cancels the open ballot (a proposal still VOTING; one tallied meanwhile keeps its
        result, and the change goes back to proposed either way, so it needs a new ballot)."""
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from sqlalchemy import update
        from .. import models
        await self.db.execute(update(models.GovernanceProposal)
                              .where(models.GovernanceProposal.id == pid, models.GovernanceProposal.status == "VOTING")
                              .values(status="CANCELLED"))
        await self.db.commit()

    async def _track(self, developer_ids: Any, source: str) -> None:
        """V0665 the contributor track: after a step's writes and BEFORE its commit, so the unlock records join the step's transaction
        (services/contributor_track is the one writer; a failure there is contained by a savepoint and never stops the step)."""
        from . import contributor_track
        await contributor_track.track_event(self.db, developer_ids, source)

    async def _involved(self, cid: str) -> List[int]:
        """The developers a change's step can move: its proposer, its reviewers, and the voters of its ballot."""
        from sqlalchemy import select
        from .. import models
        ch = await self.db.get(models.CodeChange, cid)
        if ch is None:
            return []
        ids = {ch.proposer_developer_id}
        ids.update((await self.db.execute(select(models.CodeChangeReview.reviewer_developer_id)
                                          .where(models.CodeChangeReview.code_change_id == cid))).scalars().all())
        if ch.proposal_id is not None:
            ids.update((await self.db.execute(select(models.Agent.creator_developer_id).join(
                models.Vote, models.Vote.voter_did == models.Agent.did).where(models.Vote.proposal_id == ch.proposal_id))).scalars().all())
        return sorted(i for i in ids if i is not None)

    async def insert(self, row: Dict[str, Any]) -> None:
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from .. import models
        self.db.add(models.CodeChange(**row))
        await self.db.flush()
        await self._track([row.get("proposer_developer_id")], f"code_change:{row.get('id')}")
        await self.db.commit()
        if row.get("announce_conversation_id"):
            await self._announce(str(row["id"]))

    async def get(self, cid: str) -> Optional[Dict[str, Any]]:
        from .. import models
        obj = await self.db.get(models.CodeChange, cid)
        if obj is not None:
            await self.db.refresh(obj)
        return _row_dict(obj) if obj is not None else None

    async def update(self, cid: str, **fields: Any) -> None:
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from sqlalchemy import update
        from .. import models
        await self.db.execute(update(models.CodeChange).where(models.CodeChange.id == cid).values(**fields))
        if "state" in fields or "merged" in fields:
            await self._track(await self._involved(cid), f"code_change:{cid}")
        await self.db.commit()
        await self._announce(cid)

    async def reviews(self, cid: str) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        rows = (await self.db.execute(select(models.CodeChangeReview)
                                      .where(models.CodeChangeReview.code_change_id == cid)
                                      .order_by(models.CodeChangeReview.id))).scalars().all()
        out = []
        for r in rows:
            d = _row_dict(r)
            d["at"] = r.created_at.timestamp() if r.created_at else 0
            out.append(d)
        return out

    async def add_review(self, row: Dict[str, Any]) -> None:
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from .. import models
        self.db.add(models.CodeChangeReview(**{k: row[k] for k in ("code_change_id", "reviewer_developer_id",
                                                                     "verdict", "commit", "findings")}))
        await self.db.flush()
        await self._track(await self._involved(row["code_change_id"]), f"code_change:{row['code_change_id']}")
        await self.db.commit()
        await self._announce(row["code_change_id"])

    async def frame_policy(self) -> Any:
        from .frame_policy import load
        return await load(self.db)

    async def create_proposal(self, *, title: str, description: str, diff: Dict[str, Any], quorum: float,
                              pass_percent: float, ends: dt.datetime) -> int:
        """A governance proposal of type code_change, opened by the registry itself (as the federation ballot's
        members' vote is), so the public create route keeps refusing the type."""
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from .. import models
        from .federation_ballot import own_identity
        p = models.GovernanceProposal(proposer_did=own_identity()["id"], title=title, description=description,
                                      status="VOTING", proposal_type="code_change", policy_diff=diff,
                                      quorum_percent=quorum, pass_percent=pass_percent, end_timestamp=ends)
        self.db.add(p)
        await self.db.commit()
        await self.db.refresh(p)
        return p.id

    async def proposal(self, pid: int) -> Optional[Dict[str, Any]]:
        from .. import models
        p = await self.db.get(models.GovernanceProposal, pid)
        if p is None:
            return None
        await self.db.refresh(p)
        # V0666 (gwo_b4ab7b9b): tally_quorum_met is what the bootstrap rule reads (a ballot that missed its quorum, not one the
        # members rejected); without it every go on a real registry answered rejected_by_vote
        # V0668 (gwo_2d51e1af): the numbers the tally kept and the votes' own weight, for the record's ballot_outcome
        from sqlalchemy import func, select
        weights = {bool(v): float(w or 0) for v, w in (await self.db.execute(
            select(models.Vote.vote, func.sum(models.Vote.voting_power)).where(models.Vote.proposal_id == pid)
            .group_by(models.Vote.vote))).all()}
        return {"id": p.id, "status": p.status, "tallied_at": getattr(p, "tallied_at", None),
                "end_timestamp": p.end_timestamp, "tally_quorum_met": getattr(p, "tally_quorum_met", None),
                "quorum_percent": getattr(p, "quorum_percent", None), "pass_percent": getattr(p, "pass_percent", None),
                "tally_weight_mode": getattr(p, "tally_weight_mode", None),
                "tally_network_power": getattr(p, "tally_network_power", None),
                "tally_quorum_required": getattr(p, "tally_quorum_required", None),
                "votes_for": weights.get(True, 0.0), "votes_against": weights.get(False, 0.0)}

    async def upstream_for(self, cid: str) -> Optional[Dict[str, Any]]:
        """V0667 D4: the main-line change that carries this line change upstream, if one does (`upstream_of` is unique)."""
        from sqlalchemy import select
        from .. import models
        r = (await self.db.execute(select(models.CodeChange).where(models.CodeChange.upstream_of == cid))).scalars().first()
        return _row_dict(r) if r is not None else None

    async def list(self, state: Optional[str], limit: int, code_distribution_id: Optional[str] = None,
                   upstream: bool = False) -> List[Dict[str, Any]]:
        """The main line's changes (V0666 D1: never a line's), or one line's when its id is given; with `upstream`, only the ones that carry a
        line's change upstream (V0667 D4: the admin inbox)."""
        from sqlalchemy import select
        from .. import models
        q = select(models.CodeChange).order_by(models.CodeChange.created_at.desc()).limit(limit)
        if state:
            q = q.where(models.CodeChange.state == state)
        if upstream:
            q = q.where(models.CodeChange.upstream_of.is_not(None))
        if code_distribution_id is None:
            q = q.where(models.CodeChange.code_distribution_id.is_(None))
        else:
            q = q.where(models.CodeChange.code_distribution_id == code_distribution_id)
        return [_row_dict(r) for r in (await self.db.execute(q)).scalars().all()]

    # -- V0666 D1, code distributions (services/code_distributions) --
    async def distribution(self, did: str) -> Optional[Dict[str, Any]]:
        from .. import models
        obj = await self.db.get(models.CodeDistribution, did)
        if obj is not None:
            await self.db.refresh(obj)
        return _row_dict(obj) if obj is not None else None

    async def distribution_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        obj = (await self.db.execute(select(models.CodeDistribution)
                                     .where(models.CodeDistribution.slug == slug))).scalar_one_or_none()
        return _row_dict(obj) if obj is not None else None

    async def distributions(self, org_id: Optional[str]) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        q = select(models.CodeDistribution).order_by(models.CodeDistribution.created_at.desc())
        if org_id is not None:
            q = q.where(models.CodeDistribution.organization_id == org_id)
        return [_row_dict(r) for r in (await self.db.execute(q)).scalars().all()]

    async def insert_distribution(self, row: Dict[str, Any]) -> None:
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from .. import models
        self.db.add(models.CodeDistribution(**row))
        await self.db.commit()

    async def update_distribution(self, did: str, **fields: Any) -> None:
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from sqlalchemy import update
        from .. import models
        await self.db.execute(update(models.CodeDistribution).where(models.CodeDistribution.id == did).values(**fields))
        await self.db.commit()

    async def room_refusal(self, room_id: str, proposer_did: Optional[str], organization_id: str) -> Optional[str]:
        """V0666 D3: why a line's change may not be announced in this room, or None (services/code_change_card)."""
        from . import code_change_card
        return await code_change_card.room_refusal(self.db, room_id, proposer_did, organization_id)

    async def _announce(self, cid: str) -> None:
        """V0666 D3: after a write that committed, the change's room card is refreshed (a change with no room: nothing)."""
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from sqlalchemy import select
        from .. import models
        try:
            room = (await self.db.execute(select(models.CodeChange.announce_conversation_id)
                                          .where(models.CodeChange.id == cid))).scalar()
            await self.db.commit()                  # end the read: the caller's session stays as it was
        except Exception:  # noqa: BLE001 — the card is a display of the change, which is recorded
            return
        if room:
            from . import code_change_card
            code_change_card.refresh_soon(cid)

    async def organization_names(self, ids: Sequence[str]) -> Dict[str, str]:
        """V0666 D2: {organization_id: name} for the ids that exist, in one statement."""
        from sqlalchemy import select
        from .. import models
        if not ids:
            return {}
        O = models.Organization
        rows = (await self.db.execute(select(O.id, O.name).where(O.id.in_(list(ids))))).all()
        return {str(i): n for i, n in rows}

    async def organization(self, org_id: str) -> bool:
        from .. import models
        org = await self.db.get(models.Organization, org_id)
        return org is not None and bool(getattr(org, "is_active", True))

    async def org_members(self, org_id: str) -> Dict[int, str]:
        """{developer_id: role} of the organization's ACTIVE memberships."""
        from sqlalchemy import select
        from .. import models
        rows = (await self.db.execute(select(models.OrganizationMember.developer_id, models.OrganizationMember.role)
                                      .where(models.OrganizationMember.organization_id == org_id,
                                             models.OrganizationMember.is_active.is_(True)))).all()
        return {int(d): str(r) for d, r in rows}

    async def team(self, team_id: str) -> Optional[Dict[str, Any]]:
        from .. import models
        t = await self.db.get(models.Team, team_id)
        return {"organization_id": t.organization_id, "is_active": bool(t.is_active)} if t is not None else None

    async def team_leads(self, team_id: str) -> Set[int]:
        from sqlalchemy import select
        from .. import models
        rows = (await self.db.execute(select(models.TeamMember.developer_id)
                                      .where(models.TeamMember.team_id == team_id, models.TeamMember.role == "lead",
                                             models.TeamMember.is_active.is_(True)))).scalars().all()
        return {int(d) for d in rows}

    async def developers_in_good_standing(self, ids: Sequence[int]) -> Set[int]:
        """Verified, not suspended, not pending deletion and not deleted (code_distributions.deciders)."""
        if not ids:
            return set()
        from sqlalchemy import select
        from .. import models
        D = models.Developer
        rows = (await self.db.execute(select(D.id).where(D.id.in_(list(ids)), D.is_verified.is_(True),
                                                          D.is_suspended.is_(False), D.deletion_status.is_(None),
                                                          D.deletion_requested_at.is_(None), D.deleted_at.is_(None)))).scalars().all()
        return {int(d) for d in rows}

    async def distribution_votes(self, cid: str) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        V = models.CodeDistributionVote
        rows = (await self.db.execute(select(V).where(V.code_change_id == cid).order_by(V.cast_at))).scalars().all()
        return [{"developer_id": r.developer_id, "vote": bool(r.vote), "agent_did": r.agent_did, "cast_at": r.cast_at}
                for r in rows]

    async def add_distribution_vote(self, row: Dict[str, Any]) -> None:
        await self.check_governing()     # V0666: the governing registry only (services/code_authority)
        from .. import models
        self.db.add(models.CodeDistributionVote(**{k: row[k] for k in ("code_change_id", "developer_id", "vote",
                                                                        "agent_did", "cast_at")}))
        await self.db.flush()
        await self._track([row["developer_id"]], f"code_change:{row['code_change_id']}")
        await self.db.commit()
        await self._announce(row["code_change_id"])

    async def open_distribution_ballots(self) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        C = models.CodeChange
        rows = (await self.db.execute(select(C.id).where(C.code_distribution_id.is_not(None), C.state == "balloting")
                                      .limit(100))).scalars().all()
        return [{"id": r} for r in rows]

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


def store_for(db: Any, agent: Any = None) -> DbStore:
    return DbStore(db, agent)
