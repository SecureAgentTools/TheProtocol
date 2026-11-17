"""V0666 D1, code distributions (order gwo_f1c05b131b9208a94074beae): an organization's release line on top of our release,
`<base_release>_<slug>` (an organization's code distribution: never an AGORA payout, which is a different thing that
shares the word). Design: sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md and its D1 note.

A line names the paths it opens (a subset of the platform's CODE_CHANGE_OPEN_PATHS, never wider: the main line's own
check_paths), the team whose leads decide with the organization's owners and admins, and its quorum and pass rule within
bounds we fix. Its changes ride the main line's Code changes flow (services/code_changes) with three differences:

  - proposers are the organization's members (not guests), reviewers another developer of the organization;
  - the ballot is the line's OWN (code_distribution_votes), counted here (tally), never a governance proposal: the
    frame's governance tally (crud_governance.tally_votes) weighs member points against the whole network's, and is left
    exactly as it is;
  - beside the platform maintainer's go and veto, the organization's owner may veto, and record a go that never shortens
    the platform's veto window.

Through us, always: our checker's signed record before a review counts and before a merge (as on the main line), the
platform's pause (a paused line takes no proposal, no vote, no ballot and no merge), the platform maintainer's veto.
CODE_DISTRIBUTIONS_ENABLED (default off): off, every route of a line answers 404 and nothing changes for anyone.
No value moves here: no TEG call, no balance event; a bounty is a Guild order, as on the main line.
"""
from __future__ import annotations

import os
import re
import secrets
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .code_changes import REPOSITORY, CodeChangeRefusal, check_paths, path_inside

SWITCH = "CODE_DISTRIBUTIONS_ENABLED"
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
RELEASE = re.compile(r"^V[0-9]{4}$")
QUORUM_MIN, QUORUM_MAX, QUORUM_DEFAULT = 50, 100, 50
PASS_RULES = ("simple",)                 # two thirds later, with its own CHECK (session-lead, room seq 4629)
STATES = ("active", "paused")
ORG_DECIDING_ROLES = ("owner", "admin")
ORG_PROPOSING_ROLES = ("owner", "admin", "member")   # a guest neither proposes, reviews nor decides
TEAM_DECIDING_ROLE = "lead"
WHAT_IT_IS = "an organization's release line (a code distribution), not an AGORA payout"


def enabled() -> bool:
    return (os.getenv(SWITCH) or "").strip().lower() in ("1", "true", "yes", "on")


def require_enabled() -> None:
    if not enabled():
        raise CodeChangeRefusal(404, "not_found", "Not Found")


def release_name(dist: Dict[str, Any]) -> str:
    return f"{dist['base_release']}_{dist['slug']}"


def branch_name(dist: Dict[str, Any]) -> str:
    """The branch a line's changes merge into, named for its release (our pipeline builds it, D6)."""
    return f"distribution/{release_name(dist)}"


def check_open_paths(paths: Any) -> List[str]:
    """A line's open paths: well-formed, open on the platform and not forbidden (the main line's own rule, so never
    wider than CODE_CHANGE_OPEN_PATHS), at least one."""
    if not isinstance(paths, list) or not paths:
        raise CodeChangeRefusal(422, "open_paths", "name the paths this line opens (a list, at least one)")
    pc = check_paths(REPOSITORY, paths)
    if not pc.ok:
        raise CodeChangeRefusal(422, "open_paths", f"the line's paths: {pc.reason}")
    return pc.paths


def paths_inside_line(paths: Sequence[str], dist: Dict[str, Any]) -> Optional[str]:
    """None when every path of a change sits inside the line's open paths AND the platform's current ones (checked at
    propose and again at merge: either may have narrowed since); else why not."""
    pc = check_paths(REPOSITORY, list(paths))
    if not pc.ok:
        return pc.reason
    outside = [p for p in paths if not path_inside(p, dist.get("open_paths") or [])]
    if outside:
        return f"{outside[0]} is not open in this line (open: {', '.join(dist.get('open_paths') or [])})"
    return None


def rule_of(dist: Dict[str, Any]) -> Dict[str, Any]:
    """The line's ballot rule, snapshotted on a change at its ballot's open (a later PATCH changes later ballots only)."""
    return {"quorum_percent": int(dist["quorum_percent"]), "pass_rule": dist["pass_rule"],
            "decider_team_id": dist.get("decider_team_id")}


async def deciders(store: Any, dist: Dict[str, Any], rule: Optional[Dict[str, Any]] = None) -> Tuple[Set[int], Optional[str]]:
    """THE rule (one place: an answer to "who decides" changes only this): the organization's owners and admins plus the
    leads of the deciding team, each also a current non-guest member of the organization whose account is verified, not
    suspended and not pending deletion. Read now, at every vote and again at the close. Returns (deciders, why none can
    decide): a deciding team that is gone or inactive is said, never a silent fall back to owners and admins."""
    team = (rule or {}).get("decider_team_id", dist.get("decider_team_id"))
    org = dist["organization_id"]
    members = await store.org_members(org)              # {developer_id: role}, active memberships only
    people = {d for d, role in members.items() if role in ORG_DECIDING_ROLES}
    if team:
        t = await store.team(team)
        if not t or not t.get("is_active") or t.get("organization_id") != org:
            return set(), "the line's deciding team is gone or inactive, so nobody can decide its changes"
        people |= {d for d in await store.team_leads(team) if members.get(d) in ORG_PROPOSING_ROLES}
    good = await store.developers_in_good_standing(sorted(people))
    return {d for d in people if d in good}, None


def tally(rule: Dict[str, Any], votes: Iterable[Dict[str, Any]], deciders_now: Set[int],
          why_none: Optional[str] = None) -> Dict[str, Any]:
    """The line's ballot, counted: only the votes of developers who are deciders NOW (a role taken away takes its vote
    with it); quorum = counted / deciders >= the rule's percent; pass ('simple') = more FOR than AGAINST among the
    counted. No deciders is FAILED with a sentence, never a division by zero."""
    votes = list(votes)
    counted = [v for v in votes if v["developer_id"] in deciders_now]
    yes = sum(1 for v in counted if v["vote"])
    no = len(counted) - yes
    n = len(deciders_now)
    out = {"deciders": n, "for": yes, "against": no, "counted": len(counted), "cast": len(votes),
           "quorum_percent": int(rule["quorum_percent"]), "pass_rule": rule["pass_rule"]}
    if n == 0:
        return {**out, "status": "FAILED", "quorum_met": False,
                "sentence": why_none or "the line has no deciders at the close, so nobody decided: the change fails"}
    quorum_met = len(counted) * 100 >= int(rule["quorum_percent"]) * n
    passed = quorum_met and yes > no
    if not quorum_met:
        sentence = f"{len(counted)} of {n} deciders voted, below the quorum of {rule['quorum_percent']} percent"
    elif passed:
        sentence = f"{yes} for, {no} against, of {n} deciders: passed"
    else:
        sentence = f"{yes} for, {no} against, of {n} deciders: not passed (a simple majority of the votes is needed)"
    return {**out, "status": "PASSED" if passed else "FAILED", "quorum_met": quorum_met, "sentence": sentence}


def everyone_voted(votes: Iterable[Dict[str, Any]], deciders_now: Set[int]) -> bool:
    """The early close (session-lead, room seq 4629 and 4637): EVERY current decider has voted, so nobody is outvoted
    unseen. A line with no deciders never closes early (it waits for its end, and then fails with its sentence)."""
    voted = {v["developer_id"] for v in votes}
    return bool(deciders_now) and deciders_now <= voted


def public(dist: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dist.items()}
    out["release_name"] = release_name(dist)
    out["branch"] = branch_name(dist)
    out["what"] = WHAT_IT_IS
    return out


async def named(store: Any, dists: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """V0666 D2 (session-lead, room seq 4803): public(dist) with its organization's name, read in one statement for a whole
    list; a name the store cannot read is None, so a screen never falls back to the bare id."""
    ids = sorted({str(d["organization_id"]) for d in dists})
    names = await store.organization_names(ids) if ids and hasattr(store, "organization_names") else {}
    out = []
    for d in dists:
        p = public(d)
        p["organization_name"] = names.get(str(d["organization_id"]))
        out.append(p)
    return out


class CodeDistributionFlow:
    """A line's own steps (create, read, list, update, pause, resume). Actors as in CodeChangeFlow: a developer
    {developer_id}, a platform admin {developer_id, admin: True}."""

    def __init__(self, store: Any) -> None:
        self.s = store

    async def _governing(self) -> None:
        """V0666: an organization's release line is written on the governing registry only (services/code_authority): the production store refuses elsewhere."""
        gate = getattr(self.s, "check_governing", None)
        if gate is not None:
            res = gate()
            if hasattr(res, "__await__"):
                await res

    async def _dist(self, slug: str) -> Dict[str, Any]:
        d = await self.s.distribution_by_slug(str(slug or ""))
        if not d:
            raise CodeChangeRefusal(404, "not_found", "no code distribution with that name")
        return d

    async def _role(self, org_id: str, developer_id: Optional[int]) -> Optional[str]:
        if developer_id is None:
            return None
        return (await self.s.org_members(org_id)).get(developer_id)

    async def _team_of(self, org_id: str, team_id: Optional[str]) -> Optional[str]:
        if team_id in (None, ""):
            return None
        t = await self.s.team(str(team_id))
        if not t or not t.get("is_active") or t.get("organization_id") != org_id:
            raise CodeChangeRefusal(422, "decider_team", "the deciding team must be an active team of this organization")
        return str(team_id)

    @staticmethod
    def _quorum(v: Any) -> int:
        try:
            q = int(v)
        except (TypeError, ValueError):
            raise CodeChangeRefusal(422, "quorum_percent", f"the quorum is a whole percent from {QUORUM_MIN} to {QUORUM_MAX}")
        if isinstance(v, bool) or not QUORUM_MIN <= q <= QUORUM_MAX:
            raise CodeChangeRefusal(422, "quorum_percent", f"the quorum is a whole percent from {QUORUM_MIN} to {QUORUM_MAX}")
        return q

    @staticmethod
    def _pass_rule(v: Any) -> str:
        v = v or "simple"
        if v not in PASS_RULES:
            raise CodeChangeRefusal(422, "pass_rule", f"the pass rule is one of {', '.join(PASS_RULES)}")
        return v

    async def create(self, actor: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        require_enabled()
        org = str(body.get("organization_id") or "")
        if not org or not await self.s.organization(org):
            raise CodeChangeRefusal(404, "no_organization", "no organization with that id")
        if await self._role(org, actor.get("developer_id")) not in ORG_DECIDING_ROLES:
            raise CodeChangeRefusal(403, "not_owner_or_admin", "an owner or an admin of the organization creates its lines")
        slug = str(body.get("slug") or "")
        if not SLUG.match(slug):
            raise CodeChangeRefusal(422, "slug", "a name of 2 to 40 lowercase letters, digits and '-', starting with a letter")
        if await self.s.distribution_by_slug(slug):
            raise CodeChangeRefusal(409, "slug_taken", "a code distribution of that name exists on this frame")
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 200:
            raise CodeChangeRefusal(422, "title", "a title of 1 to 200 characters")
        base = str(body.get("base_release") or "")
        if not RELEASE.match(base):
            raise CodeChangeRefusal(422, "base_release", "the base release is a release name such as V0666")
        now = self.s.now()
        row = {"id": "cdst_" + secrets.token_hex(12), "organization_id": org, "slug": slug, "title": title,
               "base_release": base, "open_paths": check_open_paths(body.get("open_paths")),
               "decider_team_id": await self._team_of(org, body.get("decider_team_id")),
               "quorum_percent": self._quorum(body.get("quorum_percent", QUORUM_DEFAULT)),
               "pass_rule": self._pass_rule(body.get("pass_rule")), "state": "active", "paused_reason": None,
               "paused_by_developer_id": None, "paused_at": None, "created_by_developer_id": actor["developer_id"],
               "created_at": now, "updated_at": now}
        await self.s.insert_distribution(row)
        return (await named(self.s, [await self._dist(slug)]))[0]

    async def read(self, actor: Dict[str, Any], slug: str) -> Dict[str, Any]:
        require_enabled()
        d = await self._dist(slug)
        if not actor.get("admin") and await self._role(d["organization_id"], actor.get("developer_id")) is None:
            raise CodeChangeRefusal(404, "not_found", "no code distribution with that name")
        out = (await named(self.s, [d]))[0]
        who, why = await deciders(self.s, d)
        out["deciders"] = len(who)
        out["deciders_note"] = why
        return out

    async def list_for_org(self, actor: Dict[str, Any], org_id: str) -> Dict[str, Any]:
        require_enabled()
        # the subject first, for everyone: the platform admin's bypass skips the membership check, never the question whether the
        # organization exists (V0667's pair proof saw an admin get 200 [] for a missing one)
        if not org_id or not await self.s.organization(str(org_id)):
            raise CodeChangeRefusal(404, "no_organization", "no organization with that id")
        if not actor.get("admin") and await self._role(org_id, actor.get("developer_id")) is None:
            raise CodeChangeRefusal(404, "no_organization", "no organization with that id")
        return {"items": await named(self.s, await self.s.distributions(org_id))}

    async def list_all(self, actor: Dict[str, Any]) -> Dict[str, Any]:
        require_enabled()
        if not actor.get("admin"):
            raise CodeChangeRefusal(403, "admin_only", "this step is a platform admin's")
        return {"items": await named(self.s, await self.s.distributions(None))}

    async def update(self, actor: Dict[str, Any], slug: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Title, open paths, deciding team, quorum and pass rule, within the bounds; never the organization, the name or
        the base release. A ballot already open keeps the rule it opened with."""
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        require_enabled()
        d = await self._dist(slug)
        if await self._role(d["organization_id"], actor.get("developer_id")) not in ORG_DECIDING_ROLES:
            raise CodeChangeRefusal(403, "not_owner_or_admin", "an owner or an admin of the organization changes its lines")
        fixed = sorted(k for k in body if k in ("organization_id", "slug", "base_release", "state"))
        if fixed:
            raise CodeChangeRefusal(422, "fixed", f"a line's {', '.join(fixed)} does not change here")
        fields: Dict[str, Any] = {}
        if "title" in body:
            title = str(body.get("title") or "").strip()
            if not title or len(title) > 200:
                raise CodeChangeRefusal(422, "title", "a title of 1 to 200 characters")
            fields["title"] = title
        if "open_paths" in body:
            fields["open_paths"] = check_open_paths(body.get("open_paths"))
        if "decider_team_id" in body:
            fields["decider_team_id"] = await self._team_of(d["organization_id"], body.get("decider_team_id"))
        if "quorum_percent" in body:
            fields["quorum_percent"] = self._quorum(body.get("quorum_percent"))
        if "pass_rule" in body:
            fields["pass_rule"] = self._pass_rule(body.get("pass_rule"))
        if fields:
            await self.s.update_distribution(d["id"], updated_at=self.s.now(), **fields)
        return await self.read(actor, slug)

    async def pause(self, actor: Dict[str, Any], slug: str, reason: str) -> Dict[str, Any]:
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        require_enabled()
        if not actor.get("admin"):
            raise CodeChangeRefusal(403, "admin_only", "the platform pauses a line (admin_platform)")
        reason = " ".join(str(reason or "").split())[:500]
        if not reason:
            raise CodeChangeRefusal(422, "reason", "a pause says why")
        d = await self._dist(slug)
        await self.s.update_distribution(d["id"], state="paused", paused_reason=reason,
                                         paused_by_developer_id=actor.get("developer_id"), paused_at=self.s.now(),
                                         updated_at=self.s.now())
        return (await named(self.s, [await self._dist(slug)]))[0]

    async def resume(self, actor: Dict[str, Any], slug: str) -> Dict[str, Any]:
        await self._governing()      # V0666: only the governing registry (services/code_authority)
        require_enabled()
        if not actor.get("admin"):
            raise CodeChangeRefusal(403, "admin_only", "the platform resumes a line (admin_platform)")
        d = await self._dist(slug)
        await self.s.update_distribution(d["id"], state="active", paused_reason=None, paused_by_developer_id=None,
                                         paused_at=None, updated_at=self.s.now())
        return (await named(self.s, [await self._dist(slug)]))[0]


async def team_in_use(db: Any, team_id: str) -> Optional[str]:
    """A team a line names as its deciders is not deleted (no silent fall back to owners and admins): the line's name,
    or None. Asked by the team-delete route (a soft delete the foreign key's RESTRICT cannot see)."""
    from sqlalchemy import select
    from .. import models
    row = (await db.execute(select(models.CodeDistribution.slug)
                            .where(models.CodeDistribution.decider_team_id == team_id).limit(1))).scalar_one_or_none()
    return row
