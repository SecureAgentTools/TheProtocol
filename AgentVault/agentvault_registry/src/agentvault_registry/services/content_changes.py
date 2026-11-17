"""V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane. An organization changes its own CONTENT after its line's ballot and our check, without a release
(sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md section 2, item 1; the lines are services/code_distributions, decided as D1 decides them).

  the kinds      kit            a new version of one of the organization's own migration templates (its library, V0664): the whole kit's files
                 proxy_spec     a new version of the same, with proxy.yaml replaced and the rest of the latest version kept
                 policy_value   one key of the organization's settings catalog (services/org_policy.ORG_SETTING_CATALOG)
                 console_text   one text of the organization's console (organizations.settings.console_texts[key])
                 branding       its tagline, accent colour and logo (organizations.settings.branding)
                 compliance_pack  V0667 D7: a regulator's rules as policy within the allowed set (services/compliance_packs), organizations.settings.compliance_packs[name]
                 Never code, never another organization's space, never anything global: a template that is not the line's organization's, a settings key the
                 catalog does not name, a target a kind does not take: refused.
  the checker    OURS, in process: the schema of the kind, the destinations rule and the credential rule of a kit (the library's own check_kit), no secret shape
                 in any text (the shapes the audit trail screens), and the size. It runs at the proposal, so a refused change is never stored and never voted
                 on, and again at the apply, on the content as it then stands. Its verdict is kept on the record.
  the ballot     the line's: its deciders (code_distributions.deciders), its quorum and pass rule snapshotted at the open, one vote per developer through an
                 agent, closed at the end of the window or early once every current decider has voted
  the apply      on a pass, to the organization's OWN space on the governing registry, with the before and after on the record. A kit takes a new unpublished
                 version of its template (publishing stays the library's own step); a setting takes its key. Paused line: nothing closes and nothing applies.
  the undo       one step, by the line's deciders or a platform admin, restoring exactly what the apply replaced; refused (409) when the content has been
                 changed by anything else since, so it never overwrites a later change
  the authority  written on the governing registry only (services/code_authority): every write of the store and every step refuses elsewhere, as the code rail does

Reads are the organization's: its members (not only deciders) and platform admins read its changes; nobody else.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

from .code_changes import CodeChangeRefusal, ballot_days

KINDS = ("kit", "proxy_spec", "policy_value", "console_text", "branding", "compliance_pack")
STATES = ("balloting", "failed", "apply_failed", "applied", "undone", "withdrawn")
KIT_KINDS = ("kit", "proxy_spec")
MAX_BYTES = {"kit": 256 * 1024, "proxy_spec": 256 * 1024}        # every other kind: 64 KiB
DEFAULT_MAX_BYTES = 64 * 1024
TEXT_MAX = 600
TAGLINE_MAX = 200
LOGO_URL_MAX = 500
KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,59}$")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
BRANDING_FIELDS = ("tagline", "accent_color", "logo_url")
BRANDING_TARGET = "branding"
CONSOLE_TEXTS = "console_texts"            # organizations.settings.console_texts: {key: text}
BRANDING = "branding"                      # organizations.settings.branding: {tagline, accent_color, logo_url}
COMPLIANCE_PACKS = "compliance_packs"      # V0667 D7: organizations.settings.compliance_packs: {name: rules}


APPLY_CLAIM_STALE = dt.timedelta(seconds=120)    # a claim nobody finished (its reader died between the claim and the record) is taken over after this


class ContentRefused(CodeChangeRefusal):
    """Our checker's refusal: 422, the code checker_refused, one sentence naming the rule and the field (never a value) and the reasons it carries."""

    def __init__(self, sentence: str, reasons: Optional[List[str]] = None) -> None:
        super().__init__(422, "checker_refused", sentence)
        self.reasons = list(reasons or [sentence])


def _bytes(content: Any) -> int:
    return len(json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _strings(node: Any, at: str = "") -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    if isinstance(node, str):
        out.append((at or "content", node))
    elif isinstance(node, dict):
        for k, v in node.items():
            out.extend(_strings(v, f"{at}.{k}" if at else str(k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_strings(v, f"{at}[{i}]"))
    return out


def secret_shape_at(content: Any) -> Optional[str]:
    """The path of the first string in `content` that holds a credential SHAPE (a private key, a JWT, a prefixed key or token, an otpauth link), or None.
    The shapes are the audit trail's own (mcp/audit_sanitizer): one list of what a secret looks like."""
    from ..mcp.audit_sanitizer import _SECRET_SHAPES
    for path, text in _strings(content):
        if any(rx.search(text) for rx in _SECRET_SHAPES):
            return path
    return None


def _fields(content: Dict[str, Any], allowed: Sequence[str]) -> None:
    extra = sorted(k for k in content if k not in allowed)
    if extra:
        raise ContentRefused(f"unknown field {extra[0]!r}: this kind takes {', '.join(allowed)} (field)")


def _https_url(url: str) -> bool:
    if len(url) > LOGO_URL_MAX:
        return False
    p = urlparse(url)
    return p.scheme == "https" and bool(p.hostname) and not p.username and not p.password


def check_content(kind: str, target: Any, content: Any, *, org_id: str, template: Optional[Dict[str, Any]] = None,
                  latest_files: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """OUR checker. Returns the verdict {"ok": True, "kind", "target", "rules", "bytes", "after"[, "files"]} for a change that passes, ContentRefused for one that does
    not. `template` (a library row) and `latest_files` (its latest version's files) are what the caller read for a kit or a proxy spec."""
    if kind not in KINDS:
        raise ContentRefused(f"the kind is one of {', '.join(KINDS)} (kind)")
    if not isinstance(target, str) or not target.strip() or len(target) > 200:
        raise ContentRefused("name the target, 1 to 200 characters (target)")
    if not isinstance(content, dict):
        raise ContentRefused("the content is an object (content)")
    size = _bytes(content)
    cap = MAX_BYTES.get(kind, DEFAULT_MAX_BYTES)
    if size > cap:
        raise ContentRefused(f"the change is over {cap // 1024} KiB (size)")
    where = secret_shape_at(content)
    if where:
        raise ContentRefused(f"a secret is written out at {where}: a credential never travels in a content change (secret)")
    verdict: Dict[str, Any] = {"ok": True, "kind": kind, "target": target, "bytes": size}
    if kind in KIT_KINDS:
        from . import workflow_templates as wt
        if template is None:
            raise ContentRefused("no such template: name one of the organization's own library (template)")
        if template.get("source_org_id") != org_id:
            raise ContentRefused("the template is not one of the organization's own library: a change touches the organization's own space only (own)")
        if kind == "kit":
            _fields(content, ("files",))
            files = content.get("files")
        else:
            _fields(content, ("proxy_yaml",))
            proxy = content.get("proxy_yaml")
            if not isinstance(proxy, str) or not proxy.strip():
                raise ContentRefused("proxy_yaml is the text of the new proxy.yaml (proxy_yaml)")
            if not latest_files:
                raise ContentRefused("the template has no version to change (template)")
            files = {**latest_files, "proxy.yaml": proxy}
        try:
            wt.check_kit(files)
        except wt.KitRefused as e:
            raise ContentRefused(f"the kit is refused: {e.sentence} (schema)", [e.sentence])
        verdict.update(rules=["schema", "destinations", "secrets", "size"], files=files, after=None)
        return verdict
    if kind == "policy_value":
        from . import org_policy
        _fields(content, ("value",))
        if "value" not in content:
            raise ContentRefused("name the value (value)")
        keys = {str(e["key"]) for e in org_policy.ORG_SETTING_CATALOG}
        if target not in keys:
            raise ContentRefused(f"{target!r} is not an organization setting the fast lane changes: only the keys of the organization's settings catalog (target)")
        head, _, tail = target.partition(".")
        patch = {head: {tail: content["value"]}} if tail else {head: content["value"]}
        ok, why = org_policy.validate_org_settings_patch(patch)
        if not ok:
            raise ContentRefused(f"{target}: {why} (schema)", [why])
        verdict.update(rules=["schema", "secrets", "size"], after=content["value"])
        return verdict
    if kind == "console_text":
        _fields(content, ("text",))
        if not KEY_RE.match(target):
            raise ContentRefused("a console text's key is lowercase letters, digits, '.', '_' and '-', 2 to 60 characters, starting with a letter (key)")
        text = content.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > TEXT_MAX:
            raise ContentRefused(f"the text is 1 to {TEXT_MAX} characters (text)")
        verdict.update(rules=["schema", "secrets", "size"], after=text)
        return verdict
    if kind == "compliance_pack":
        from . import compliance_packs
        try:
            rules = compliance_packs.check_pack(target, content)
        except compliance_packs.PackRefused as e:
            raise ContentRefused(f"{e.sentence}", [e.sentence])
        verdict.update(rules=["allowed_set", "secrets", "size"], after=rules)
        return verdict
    # branding
    if target != BRANDING_TARGET:
        raise ContentRefused(f"the target of a branding change is {BRANDING_TARGET!r} (target)")
    _fields(content, BRANDING_FIELDS)
    if not content:
        raise ContentRefused("a branding change names a tagline, an accent_color or a logo_url (branding)")
    tag = content.get("tagline")
    if "tagline" in content and (not isinstance(tag, str) or not tag.strip() or len(tag) > TAGLINE_MAX):
        raise ContentRefused(f"the tagline is 1 to {TAGLINE_MAX} characters (tagline)")
    col = content.get("accent_color")
    if "accent_color" in content and not (isinstance(col, str) and HEX_COLOR.match(col)):
        raise ContentRefused("the accent_color is a #rrggbb colour (accent_color)")
    logo = content.get("logo_url")
    if "logo_url" in content and not (isinstance(logo, str) and _https_url(logo)):
        raise ContentRefused(f"the logo_url is an https address with no login in it, at most {LOGO_URL_MAX} characters (logo_url)")
    verdict.update(rules=["schema", "secrets", "size"], after=dict(content))
    return verdict


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.datetime) else v


def _line_active(dist: Dict[str, Any], step: str) -> None:
    if dist.get("state") != "active":
        raise CodeChangeRefusal(409, "line_paused", f"the platform paused this line ({dist.get('paused_reason')}): it takes no {step} until it is resumed")


class ContentChangeFlow:
    """The steps of a content change. Actors as in CodeChangeFlow: an agent's {did, developer_id}, a platform admin {developer_id, admin: True}."""

    def __init__(self, store: Any) -> None:
        self.s = store

    async def _governing(self) -> None:
        gate = getattr(self.s, "check_governing", None)
        if gate is not None:
            res = gate()
            if hasattr(res, "__await__"):
                await res

    async def _row(self, cid: str) -> Dict[str, Any]:
        row = await self.s.get(cid)
        if row is None:
            raise CodeChangeRefusal(404, "not_found", "no content change with that id")
        return row

    async def _line(self, row: Dict[str, Any]) -> Dict[str, Any]:
        dist = await self.s.distribution(row["code_distribution_id"])
        if dist is None:
            raise CodeChangeRefusal(404, "not_found", "the change's code distribution is gone")
        return dist

    async def _readable(self, actor: Dict[str, Any], row: Dict[str, Any]) -> None:
        """The organization's members (not only deciders) and platform admins read a change; for anyone else it does not exist."""
        if actor.get("admin"):
            return
        if actor.get("developer_id") in await self.s.org_members(row["organization_id"]):
            return
        raise CodeChangeRefusal(404, "not_found", "no content change with that id")

    async def _checked(self, kind: str, target: Any, content: Any, org_id: str) -> Dict[str, Any]:
        template = latest = None
        if kind in KIT_KINDS and isinstance(target, str):
            template = await self.s.template(target)
            if template is not None and kind == "proxy_spec":
                latest = await self.s.latest_files(target)
        return check_content(kind, target, content, org_id=org_id, template=template, latest_files=latest)

    # ── propose ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    async def propose(self, actor: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()      # V0667: only the governing registry (services/code_authority)
        from . import code_distributions as cd
        cd.require_enabled()
        dist = await self.s.distribution_by_slug(str(body.get("code_distribution") or ""))
        if not dist:
            raise CodeChangeRefusal(404, "not_found", "no code distribution with that name")
        _line_active(dist, "proposal")
        role = (await self.s.org_members(dist["organization_id"])).get(actor.get("developer_id"))
        if role not in cd.ORG_PROPOSING_ROLES:
            raise CodeChangeRefusal(403, "not_org_member", "a member of the line's organization proposes into it (not a guest)")
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 160:
            raise CodeChangeRefusal(422, "title", "a title of 1 to 160 characters")
        problem = str(body.get("problem") or "").strip()
        if not problem or len(problem) > 6000:
            raise CodeChangeRefusal(422, "problem", "the problem, in 1 to 6000 characters")
        room = str(body.get("room_id") or "").strip() or None
        if room is not None:
            why = await self.s.room_refusal(room, actor.get("did"), dist["organization_id"])         # V0667 D5b: the room rule of a code change's card
            if why:
                raise CodeChangeRefusal(422, "room", why)
        kind, target, content = body.get("kind"), body.get("target"), body.get("content")
        verdict = await self._checked(str(kind), target, content, dist["organization_id"])       # a refusal here writes nothing and opens no ballot
        verdict.pop("files", None)
        now = self.s.now()
        cid = "ct_" + secrets.token_hex(12)
        await self.s.insert({
            "id": cid, "code_distribution_id": dist["id"], "organization_id": dist["organization_id"], "kind": kind, "target": target, "title": title,
            "problem": problem, "content": content, "checker": {**verdict, "at": _iso(now)}, "state": "balloting",
            "proposer_did": actor.get("did"), "proposer_developer_id": actor.get("developer_id"), "announce_conversation_id": room,
            "ballot_rule": cd.rule_of(dist), "ballot_ends": now + dt.timedelta(days=ballot_days()), "ballot_result": None,
            "before": None, "after": None, "applied_at": None, "apply_error": None, "undone": None, "created_at": now, "updated_at": now})
        return await self.view(actor, cid)

    # ── the ballot ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    async def _synced(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """The ballot closes at its end, or early once EVERY current decider has voted; a pass applies. A paused line closes and applies nothing. A registry that
        does not govern only READS: the record is shown as it stands."""
        from . import code_distributions as cd
        if row["state"] != "balloting":
            return row
        dist = await self._line(row)
        if dist.get("state") != "active":
            return row
        now = self.s.now()
        ends = row.get("ballot_ends")
        if isinstance(ends, dt.datetime) and ends.tzinfo is None:
            ends = ends.replace(tzinfo=dt.timezone.utc)
        votes = await self.s.votes(row["id"])
        rule = row.get("ballot_rule") or cd.rule_of(dist)
        who, why = await cd.deciders(self.s, dist, rule)
        at_end = isinstance(ends, dt.datetime) and now >= ends
        if not (at_end or cd.everyone_voted(votes, who)):
            return row
        res = cd.tally(rule, votes, who, why)
        res.update(closed_at=_iso(now), early=not at_end)
        try:
            if res["status"] != "PASSED":
                await self.s.update(row["id"], state="failed", ballot_result=res, updated_at=now)
            else:
                # V0667 follow-up: a passed ballot is applied by ONE reader. Every write announces the change's room card and the card's refresh reads the change through this
                # same sync, so the request that cast the closing vote and that refresh both met a passed ballot that was still `balloting` and both applied: the second one read the
                # first one's value as its `before` and wrote it last, so the undo restored nothing. The claim is one compare-and-set; the loser shows the record as it stands.
                if not await self.s.claim_apply(row["id"], res, now, APPLY_CLAIM_STALE):
                    return await self._row(row["id"])
                await self._apply(row["id"])
        except CodeChangeRefusal as r:
            if r.code != "code_change_not_governed_here":
                raise
            return row
        return await self._row(row["id"])

    async def _apply(self, cid: str) -> None:
        """Write the passed change to the organization's own space, with its before and after; the checker runs again on the content as it now stands."""
        row = await self._row(cid)
        now = self.s.now()
        try:
            verdict = await self._checked(row["kind"], row["target"], row["content"], row["organization_id"])
            before, after = await self.s.apply(row["organization_id"], row["kind"], row["target"], row["content"], verdict, row["title"])
        except ContentRefused as e:
            await self.s.update(cid, state="apply_failed", apply_error=e.sentence[:500], applied_at=None, updated_at=now)
            return
        except CodeChangeRefusal as e:
            if e.code == "code_change_not_governed_here":
                raise
            await self.s.update(cid, state="apply_failed", apply_error=e.sentence[:500], applied_at=None, updated_at=now)
            return
        await self.s.update(cid, state="applied", before=before, after=after, applied_at=now, apply_error=None, updated_at=now)

    async def vote(self, actor: Dict[str, Any], cid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self._governing()
        from . import code_distributions as cd
        row = await self._synced(await self._row(cid))
        dist = await self._line(row)
        _line_active(dist, "vote")
        if row["state"] != "balloting":
            raise CodeChangeRefusal(409, "wrong_state", f"the ballot is not open (this change is {row['state']})")
        vote = body.get("vote")
        if not isinstance(vote, bool):
            raise CodeChangeRefusal(422, "vote", "the vote is true (for) or false (against)")
        dev = actor.get("developer_id")
        who, why = await cd.deciders(self.s, dist, row.get("ballot_rule"))
        if dev not in who:
            raise CodeChangeRefusal(403, "not_a_decider", why or "only the line's deciders vote (its organization's owners and admins and its deciding team's leads)")
        if any(v["developer_id"] == dev for v in await self.s.votes(cid)):
            raise CodeChangeRefusal(409, "already_voted", "this developer has voted on this change (a vote is not changed)")
        await self.s.add_vote({"content_change_id": cid, "developer_id": dev, "vote": vote, "agent_did": actor.get("did"), "cast_at": self.s.now()})
        return await self.view(actor, cid)

    async def withdraw(self, actor: Dict[str, Any], cid: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await self._governing()
        row = await self._row(cid)
        if not actor.get("admin") and actor.get("developer_id") != row["proposer_developer_id"]:
            raise CodeChangeRefusal(403, "not_the_proposer", "the proposer (or a platform admin) withdraws a change")
        if row["state"] != "balloting":
            raise CodeChangeRefusal(409, "wrong_state", f"only a change in its ballot is withdrawn (this one is {row['state']})")
        await self.s.update(cid, state="withdrawn", undone={"by": actor.get("developer_id"), "at": _iso(self.s.now()), "reason": str((body or {}).get("reason") or "")[:500]},
                            updated_at=self.s.now())
        return await self.view(actor, cid)

    async def undo(self, actor: Dict[str, Any], cid: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """One step: restore exactly what the apply replaced. By the line's deciders or a platform admin; refused when the content was changed since."""
        await self._governing()
        from . import code_distributions as cd
        row = await self._row(cid)
        dist = await self._line(row)
        if not actor.get("admin"):
            who, why = await cd.deciders(self.s, dist, row.get("ballot_rule"))
            if actor.get("developer_id") not in who:
                raise CodeChangeRefusal(403, "not_a_decider", why or "the line's deciders (or a platform admin) undo an applied change")
        if row["state"] != "applied":
            raise CodeChangeRefusal(409, "wrong_state", f"only an applied change is undone (this one is {row['state']})")
        await self.s.undo(row["organization_id"], row["kind"], row["target"], row.get("before"), row.get("after"))
        await self.s.update(cid, state="undone", undone={"by": actor.get("developer_id"), "at": _iso(self.s.now()), "reason": str((body or {}).get("reason") or "")[:500]},
                            updated_at=self.s.now())
        return await self.view(actor, cid)

    # ── reads ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    async def view(self, actor: Dict[str, Any], cid: str) -> Dict[str, Any]:
        from . import code_distributions as cd
        row = await self._row(cid)
        await self._readable(actor, row)
        row = await self._synced(row)
        dist = await self._line(row)
        votes = await self.s.votes(cid)
        who, why = await cd.deciders(self.s, dist, row.get("ballot_rule"))
        out = {k: _iso(v) for k, v in row.items()}
        mine = next((v for v in votes if v["developer_id"] == actor.get("developer_id")), None)
        out["code_distribution"] = {"id": dist["id"], "slug": dist["slug"], "title": dist["title"], "state": dist["state"],
                                    "release_name": f"{dist['base_release']}_{dist['slug']}"}
        out["ballot"] = {"rule": row.get("ballot_rule"), "ends": _iso(row.get("ballot_ends")), "result": row.get("ballot_result"), "deciders": len(who),
                         "cast": len(votes), "my_vote": None if mine is None else ("FOR" if mine["vote"] else "AGAINST"),
                         "can_vote": row["state"] == "balloting" and actor.get("developer_id") in who and mine is None}
        out["can_undo"] = row["state"] == "applied" and (bool(actor.get("admin")) or actor.get("developer_id") in who)
        return out

    async def list(self, actor: Dict[str, Any], *, slug: Optional[str] = None, state: Optional[str] = None, kind: Optional[str] = None,
                   organization_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """A member's changes: those of the organizations they are an active member of. A platform admin's inbox: every organization's (the filters narrow)."""
        if state is not None and state not in STATES:
            raise CodeChangeRefusal(422, "state", f"the state is one of {', '.join(STATES)}")
        if kind is not None and kind not in KINDS:
            raise CodeChangeRefusal(422, "kind", f"the kind is one of {', '.join(KINDS)}")
        orgs: Optional[Set[str]] = None
        if not actor.get("admin"):
            orgs = set(await self.s.orgs_of(actor.get("developer_id")))
            if organization_id is not None and organization_id not in orgs:
                return {"content_changes": []}
        dist_id = None
        if slug is not None:
            dist = await self.s.distribution_by_slug(slug)
            if not dist:
                raise CodeChangeRefusal(404, "not_found", "no code distribution with that name")
            if orgs is not None and dist["organization_id"] not in orgs:
                return {"content_changes": []}
            dist_id = dist["id"]
        rows = await self.s.list(orgs, organization_id, dist_id, state, kind, limit)
        return {"content_changes": [await self.view(actor, r["id"]) for r in rows]}


# ── the store on the registry database ───────────────────────────────────────────────────────────────────────────────────────────────────────────
class DbStore:
    """ContentChangeFlow's store on the registry database. Every write asks the governing registry first (check_governing); the organization helpers are the
    code-change store's own (one answer to who is a member, who decides, who is in good standing)."""

    def __init__(self, db: Any, agent: Any = None) -> None:
        from .code_changes import DbStore as CodeDbStore
        self.db, self.agent = db, agent
        self._base = CodeDbStore(db, agent)

    # delegated to the code-change store: one answer to who is a member, who decides, who is in good standing, and which registry governs
    async def check_governing(self) -> None:
        await self._base.check_governing()

    def now(self) -> dt.datetime:
        return self._base.now()

    async def distribution(self, did: str) -> Optional[Dict[str, Any]]:
        return await self._base.distribution(did)

    async def distribution_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return await self._base.distribution_by_slug(slug)

    async def org_members(self, org_id: str) -> Dict[int, str]:
        return await self._base.org_members(org_id)

    async def team(self, team_id: str) -> Optional[Dict[str, Any]]:
        return await self._base.team(team_id)

    async def team_leads(self, team_id: str) -> Set[int]:
        return await self._base.team_leads(team_id)

    async def developers_in_good_standing(self, ids: Sequence[int]) -> Set[int]:
        return await self._base.developers_in_good_standing(ids)

    async def organization_names(self, ids: Sequence[str]) -> Dict[str, str]:
        return await self._base.organization_names(ids)

    async def room_refusal(self, room_id: str, proposer_did: Optional[str], organization_id: str) -> Optional[str]:
        return await self._base.room_refusal(room_id, proposer_did, organization_id)

    async def _announce(self, cid: str) -> None:
        """V0667 D5b: after a write that committed, the change's room card is refreshed (a change with no room: nothing)."""
        from sqlalchemy import select
        from .. import models
        from . import content_change_card
        try:
            room = (await self.db.execute(select(models.ContentChange.announce_conversation_id).where(models.ContentChange.id == cid))).scalar()
            await self.db.commit()                  # end the read: the caller's session stays as it was
        except Exception:  # noqa: BLE001 — the card is a display of the change, which is recorded
            return
        if room:
            content_change_card.refresh_soon(cid)

    async def orgs_of(self, developer_id: Optional[int]) -> List[str]:
        if developer_id is None:
            return []
        from sqlalchemy import select
        from .. import models
        M = models.OrganizationMember
        return list((await self.db.execute(select(M.organization_id).where(M.developer_id == developer_id, M.is_active.is_(True)))).scalars().all())

    # the records
    @staticmethod
    def _dict(o: Any) -> Dict[str, Any]:
        return {c.name: getattr(o, c.name) for c in o.__table__.columns}

    async def get(self, cid: str) -> Optional[Dict[str, Any]]:
        from .. import models
        obj = await self.db.get(models.ContentChange, cid)
        if obj is not None:
            await self.db.refresh(obj)
        return self._dict(obj) if obj is not None else None

    async def insert(self, row: Dict[str, Any]) -> None:
        await self.check_governing()
        from .. import models
        self.db.add(models.ContentChange(**row))
        await self.db.commit()
        if row.get("announce_conversation_id"):
            await self._announce(str(row["id"]))

    async def claim_apply(self, cid: str, ballot_result: Dict[str, Any], now: dt.datetime, stale: dt.timedelta) -> bool:
        """Win the right to apply a passed ballot: ONE compare-and-set on the row (still `balloting`, and no claim, or one older than `stale`). The claim writes the ballot's result and
        stamps `applied_at` (the record's own time replaces it when the apply finishes, and a failed apply clears it). True for the one caller that won."""
        await self.check_governing()
        from sqlalchemy import or_, update
        from .. import models
        C = models.ContentChange
        res = await self.db.execute(update(C).where(C.id == cid, C.state == "balloting", or_(C.applied_at.is_(None), C.applied_at < now - stale))
                                    .values(ballot_result=ballot_result, applied_at=now, updated_at=now).returning(C.id))
        won = res.first() is not None
        await self.db.commit()
        if won:
            await self._announce(cid)
        return won

    async def update(self, cid: str, **fields: Any) -> None:
        await self.check_governing()
        from sqlalchemy import update
        from .. import models
        await self.db.execute(update(models.ContentChange).where(models.ContentChange.id == cid).values(**fields))
        await self.db.commit()
        await self._announce(cid)

    async def votes(self, cid: str) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        V = models.ContentChangeVote
        rows = (await self.db.execute(select(V).where(V.content_change_id == cid).order_by(V.cast_at))).scalars().all()
        return [{"developer_id": r.developer_id, "vote": bool(r.vote), "agent_did": r.agent_did, "cast_at": r.cast_at} for r in rows]

    async def add_vote(self, row: Dict[str, Any]) -> None:
        await self.check_governing()
        from .. import models
        self.db.add(models.ContentChangeVote(**row))
        await self.db.commit()
        await self._announce(row["content_change_id"])

    async def list(self, orgs: Optional[Set[str]], organization_id: Optional[str], dist_id: Optional[str], state: Optional[str], kind: Optional[str],
                   limit: int) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from .. import models
        C = models.ContentChange
        q = select(C)
        if orgs is not None:
            q = q.where(C.organization_id.in_(sorted(orgs)))
        if organization_id is not None:
            q = q.where(C.organization_id == organization_id)
        if dist_id is not None:
            q = q.where(C.code_distribution_id == dist_id)
        if state is not None:
            q = q.where(C.state == state)
        if kind is not None:
            q = q.where(C.kind == kind)
        rows = (await self.db.execute(q.order_by(C.created_at.desc(), C.id.desc()).limit(max(1, min(int(limit), 200))))).scalars().all()
        return [self._dict(r) for r in rows]

    # the organization's own space
    async def template(self, tid: str) -> Optional[Dict[str, Any]]:
        from . import workflow_templates as wt
        return await wt.DbStore(self.db).template(tid)

    async def latest_files(self, tid: str) -> Optional[Dict[str, str]]:
        from . import workflow_templates as wt
        versions = await wt.DbStore(self.db).template_versions(tid)
        return versions[-1]["files"] if versions else None

    async def _settings(self, org_id: str) -> Dict[str, Any]:
        from .. import models
        org = await self.db.get(models.Organization, org_id)
        if org is None:
            raise CodeChangeRefusal(404, "not_found", "the organization is gone")
        await self.db.refresh(org)
        return json.loads(json.dumps(org.settings or {}))

    async def _set_settings(self, org_id: str, settings: Dict[str, Any]) -> None:
        from sqlalchemy import update
        from .. import models
        await self.db.execute(update(models.Organization).where(models.Organization.id == org_id).values(settings=settings))
        await self.db.commit()

    @staticmethod
    def _path(kind: str, target: str) -> List[str]:
        if kind == "policy_value":
            return target.split(".")
        if kind == "console_text":
            return [CONSOLE_TEXTS, target]
        if kind == "compliance_pack":
            return [COMPLIANCE_PACKS, target]
        return [BRANDING]

    @staticmethod
    def _get(doc: Dict[str, Any], path: List[str]) -> Any:
        cur: Any = doc
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur

    @staticmethod
    def _put(doc: Dict[str, Any], path: List[str], value: Any) -> None:
        """Set the value at `path` (a missing parent is made); None takes the key away, and a parent the removal leaves empty goes with it, so an undo leaves the
        settings as they were before the apply made the parent."""
        chain = [doc]
        for p in path[:-1]:
            nxt = chain[-1].get(p)
            if not isinstance(nxt, dict):
                if value is None:
                    return
                nxt = chain[-1][p] = {}
            chain.append(nxt)
        if value is not None:
            chain[-1][path[-1]] = value
            return
        chain[-1].pop(path[-1], None)
        for depth in range(len(chain) - 1, 0, -1):
            if chain[depth]:
                break
            chain[depth - 1].pop(path[depth - 1], None)

    async def apply(self, org_id: str, kind: str, target: str, content: Dict[str, Any], verdict: Dict[str, Any], title: str) -> Tuple[Dict[str, Any], Any]:
        """Write the content to the organization's own space; returns (before, after) as the record keeps them."""
        await self.check_governing()
        if kind in KIT_KINDS:
            from . import workflow_templates as wt
            store = wt.DbStore(self.db)
            tpl = await store.template(target)
            if tpl is None or tpl.get("source_org_id") != org_id:
                raise CodeChangeRefusal(409, "not_own_template", "the template is not one of the organization's own library")
            versions = await store.template_versions(target)
            n = max((v["version"] for v in versions), default=0) + 1
            files = verdict["files"]
            manifest = wt.check_kit(files)
            row = {"id": "wtpv_" + secrets.token_hex(10), "template_id": target, "version": n, "manifest": manifest, "files": files,
                   "content_hash": wt.content_hash(manifest, files), "changelog": f"fast lane: {title}"[:500], "published_at": None, "created_at": self.now()}
            await store.insert_version(row)
            await store.update_template(target, updated_at=self.now())
            return ({"latest_version": n - 1}, {"version": n, "version_id": row["id"], "content_hash": row["content_hash"]})
        settings = await self._settings(org_id)
        path = self._path(kind, target)
        before = self._get(settings, path)
        new = ({**(before if isinstance(before, dict) else {}), **content} if kind == "branding" else content["text"] if kind == "console_text"
               else verdict["after"] if kind == "compliance_pack" else content["value"])
        self._put(settings, path, new)
        await self._set_settings(org_id, settings)
        return ({"value": before}, {"value": new})

    async def undo(self, org_id: str, kind: str, target: str, before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> None:
        await self.check_governing()
        if kind in KIT_KINDS:
            from sqlalchemy import text
            vid = (after or {}).get("version_id")
            rows = (await self.db.execute(text("SELECT version, published_at FROM workflow_template_versions WHERE id = :v AND template_id = :t"),
                                          {"v": vid, "t": target})).mappings().all()
            latest = (await self.db.execute(text("SELECT max(version) FROM workflow_template_versions WHERE template_id = :t"), {"t": target})).scalar()
            if not rows:
                raise CodeChangeRefusal(409, "changed_since", "the version this change made is gone: there is nothing to undo")
            if rows[0]["published_at"] is not None:
                raise CodeChangeRefusal(409, "changed_since", "the version this change made has been published since: it is not taken back")
            if latest != rows[0]["version"]:
                raise CodeChangeRefusal(409, "changed_since", "a newer version of the template exists: this change's version is not the latest, so it is not taken back")
            await self.db.execute(text("DELETE FROM workflow_template_versions WHERE id = :v"), {"v": vid})
            await self.db.commit()
            return
        settings = await self._settings(org_id)
        path = self._path(kind, target)
        if self._get(settings, path) != (after or {}).get("value"):
            raise CodeChangeRefusal(409, "changed_since", "the content has been changed by something else since this change: it is not overwritten")
        self._put(settings, path, (before or {}).get("value"))
        await self._set_settings(org_id, settings)


def store_for(db: Any, agent: Any = None) -> DbStore:
    return DbStore(db, agent)
