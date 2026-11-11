"""V0657 (b), session-code 2026-11-06: orgs v2, local (order gwo_526ffa9f951232f15adbaeb8; the discovery: room seq 1475,
orgs_v2_discovery_2026-11-06.md; the Commander's answer: seq 1482).

What each test pins:
- item 2, privacy first: an organization's mark is stated only while it is listed (`public_listing`, off by default, a
  boolean) AND the agent shows it (`agents.show_org`); the agent itself or its creator sets that;
- item 1: the mark is a home extension (derived at the reads and the exports, never owner content, never an echo's
  change), and every change of the organization moves its agents' cards so every peer's pull re-reads them;
- item 3: the logo is a small PNG or JPEG this registry hosts and serves from its own origin (no sniffing, no script);
- item 8: an agent runs the organization by its live organization grant (admin to invite and to take agents out,
  owner for the settings and the roles), never the treasury, the ownership or deleting it;
- polish 9: an agent asks to join, or its creator proposes it, and an administrator (a person or an agent) decides;
- item 6: this registry's listed organizations, public, with the hosted logo and its home;
- polish 10: the two public listings ask one opt-in test and carry the logo and the website;
- items 5 and 11: the room names its organization (with its logo) and the open-room answer its live name.

Every case runs the real functions over a recording fake database. RED on e143dd798 ((a)'s head, the base of (b)).
"""
from __future__ import annotations

import asyncio
import io
import types

import pytest
from fastapi import HTTPException

ORG = "4f3c1b2a-0000-4000-8000-000000000001"
AGENT = "did:theprotocol:eu.test:0fc15206-ca13-4257-884f-656866dd1bb1"
OTHER = "did:theprotocol:eu.test:8db7b75e-6d87-4a1e-b530-42effe5787ab"
SHA = "a" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64


class _Result:
    def __init__(self, rows=(), rowcount=None, scalar=None, obj=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount
        self._scalar = scalar
        self._obj = obj

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def all(self):
        return list(self._rows)

    def scalar(self):
        if self._scalar is not None:
            return self._scalar
        r = self.first()
        return (r[0] if isinstance(r, (tuple, list)) else r) if r is not None else None

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def mappings(self):
        return self


class _Db:
    """Answers by the first handler whose needle is in the statement; records every statement and commit."""

    def __init__(self, *handlers):
        self.handlers = list(handlers)
        self.calls = []
        self.added = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, dict(params or {})) if callable(res) else res
        return _Result([], rowcount=0)

    def sql(self, needle):
        return [c for c in self.calls if needle in c[0]]

    async def commit(self):
        self.calls.append(("COMMIT", {}))

    async def rollback(self):
        self.calls.append(("ROLLBACK", {}))

    async def flush(self):
        return None

    def add(self, obj):
        self.added.append(obj)


def _run(coro):
    return asyncio.run(coro)


def _org(**kw):
    base = dict(id=ORG, slug="theprotocol-sessions", name="TheProtocol Sessions", owner_id=6, is_active=True,
                settings={"public_listing": True}, limits={}, description="d", website="https://example.org",
                logo_url=None, created_at=None, updated_at=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _agent_actor(did=AGENT):
    return {"kind": "agent", "agent_did": did, "agent": types.SimpleNamespace(did=did)}


def _dev_actor(dev_id=6):
    return {"kind": "developer", "developer": types.SimpleNamespace(id=dev_id, name="ruler", email="r@x.invalid")}


@pytest.fixture
def touches(monkeypatch):
    """The card touches, recorded: (kind, ref)."""
    from agentvault_registry.services import org_mark
    seen = []

    async def agents(db, dids):
        seen.append(("agents", tuple(dids)))
        return len(dids)

    async def org(db, org_id):
        seen.append(("org", str(org_id)))
        return 1
    monkeypatch.setattr(org_mark, "touch_agent_cards_no_commit", agents)
    monkeypatch.setattr(org_mark, "touch_org_cards_no_commit", org)
    return seen


@pytest.fixture
def audits(monkeypatch):
    from agentvault_registry.services import org_actor
    seen = []

    async def audit(db, who, action, org_id, **kw):
        seen.append((who.kind, who.ref, action))
    monkeypatch.setattr(org_actor, "audit", audit)
    return seen


def _as(monkeypatch, org, who):
    """The route's caller resolves to `who` in `org` (org_actor.org_authority is tested on its own below)."""
    from agentvault_registry.routers import organizations as r

    async def authority(db, org_id, actor, people, agents=None, *, people_only=False):
        return org, who
    monkeypatch.setattr(r, "_authority", authority)


# ── item 2: privacy first ───────────────────────────────────────────────────────────────────────────────────────────
def test_listing_is_a_catalog_setting_off_by_default_and_only_a_boolean_lists():
    from agentvault_registry.services import org_policy as op
    entry = next(e for e in op.ORG_SETTING_CATALOG if e["key"] == "public_listing")
    assert entry["type"] == "bool"
    assert op.validate_org_settings_patch({"public_listing": True}) == (True, "")
    ok, err = op.validate_org_settings_patch({"public_listing": "true"})
    assert not ok and "public_listing" in err
    assert [op.listed_public(s) for s in ({}, None, {"public_listing": "true"}, {"public_listing": True})] == \
        [False, False, False, True]
    assert op.sql_listed_public("o") == "((o.settings->'public_listing')::text = 'true')"


def test_the_mark_is_stated_only_for_a_listed_org_and_an_agent_that_shows_it(monkeypatch):
    from agentvault_registry.services import org_mark
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_origin", lambda: "https://eu.example")
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_url_static", lambda: "https://eu.example/ui")
    db = _Db(("FROM agents a JOIN organizations o", _Result([(AGENT, ORG, "sessions", "Sessions", SHA)])))
    states = _run(org_mark.card_states(db, [AGENT, OTHER]))
    sql, params = db.calls[0]
    for clause in ("o.is_active = TRUE", "a.show_org = TRUE", "((o.settings->'public_listing')::text = 'true')"):
        assert clause in sql, clause
    assert params["dids"] == [AGENT, OTHER] and list(states) == [AGENT]
    st = states[AGENT]
    assert st["logo"] == f"https://eu.example/api/v1/organizations/{ORG}/logo?v={SHA[:12]}"
    assert st["page"] == "https://eu.example/ui/#/firms?org=sessions"
    assert st["home"]["origin"] == "https://eu.example" and (st["id"], st["name"]) == (ORG, "Sessions")
    assert _run(org_mark.card_states(_Db(), [])) == {}


# ── item 1: the mark rides the card the way the home extensions do ──────────────────────────────────────────────────
def test_the_block_is_added_only_with_a_mark_and_never_stale():
    from agentvault_registry.services import org_mark
    stale = {"extensions": [{"uri": org_mark.ORG_EXTENSION_URI, "params": {"name": "Old"}}, {"uri": "x:keep"}]}
    out = org_mark.inject_extension(dict(stale), None)
    assert out["extensions"] == [{"uri": "x:keep"}]
    st = {"id": ORG, "slug": "s", "name": "New", "logo": None, "home": {"name": "EU"}, "page": None}
    out = org_mark.inject_extension(dict(stale), st)
    assert [e["uri"] for e in out["extensions"]] == ["x:keep", org_mark.ORG_EXTENSION_URI]
    assert org_mark.extension_from_card(out)["name"] == "New"


def test_an_owner_cannot_write_the_org_block_and_a_native_read_states_it(monkeypatch):
    from agentvault_registry.services import home_extensions as he
    from agentvault_registry.services import org_mark
    forged = {"name": "a", "extensions": [{"uri": org_mark.ORG_EXTENSION_URI, "params": {"name": "Acme Labs"}}]}
    assert org_mark.ORG_EXTENSION_URI in he.HOME_EXTENSION_URIS
    assert he.strip_home_extensions(forged)["extensions"] == []

    async def none(db, did):
        return None

    async def mark(db, did):
        return {"id": ORG, "slug": "s", "name": "Sessions", "logo": None, "home": {"name": "EU"}, "page": None}
    for mod in ("reputation_bond", "enforcement_propagation", "listing_propagation"):
        monkeypatch.setattr(f"agentvault_registry.services.{mod}.card_state", none)
    monkeypatch.setattr(org_mark, "card_state", mark)
    out = _run(he.derive_for_read(_Db(), forged, AGENT))
    assert org_mark.extension_from_card(out)["name"] == "Sessions", "the home's statement replaces the owner's"


def test_an_echo_of_our_own_card_with_its_org_block_is_no_change():
    from agentvault_registry.crud.crud_peer_registry import drop_export_derived
    from agentvault_registry.services import org_mark
    cd = {"name": "a", "extensions": [{"uri": org_mark.ORG_EXTENSION_URI, "params": {"name": "Sessions"}}]}
    drop_export_derived(cd)
    assert "extensions" not in cd


# ── item 1: every change of the organization moves its agents' cards ───────────────────────────────────────────────
def test_the_settings_move_the_cards_only_when_the_listing_flips(monkeypatch, touches, audits):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services.organization_service import OrganizationService
    org = _org(settings={})
    _as(monkeypatch, org, types.SimpleNamespace(kind="agent", ref=AGENT, level="owner"))

    async def update(db, org_id, **kw):
        org.settings = kw.get("settings", org.settings)
        return org
    monkeypatch.setattr(OrganizationService, "update_organization", staticmethod(update))
    _run(r.update_organization_settings(actor=_agent_actor(), org_id=ORG, patch={"contract_offer_ttl_days": 7},
                                        db=_Db()))
    assert touches == []
    _run(r.update_organization_settings(actor=_agent_actor(), org_id=ORG, patch={"public_listing": True}, db=_Db()))
    assert touches == [("org", ORG)]
    assert ("agent", AGENT, "settings") in audits


def test_a_rename_moves_the_cards_and_an_unchanged_name_does_not(monkeypatch, touches, audits):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services.organization_service import OrganizationService
    org = _org(created_at=types.SimpleNamespace(isoformat=lambda: "t"),
               updated_at=types.SimpleNamespace(isoformat=lambda: "t"))
    _as(monkeypatch, org, types.SimpleNamespace(kind="developer", ref="6", level="admin", developer_id=6))

    async def update(db, org_id, **kw):
        for k, v in kw.items():
            setattr(org, k, v)
        return org
    monkeypatch.setattr(OrganizationService, "update_organization", staticmethod(update))
    body = r.OrganizationUpdate(description="new words")
    _run(r.update_organization(actor=_dev_actor(), org_id=ORG, org_update=body, db=_Db()))
    assert touches == []
    _run(r.update_organization(actor=_dev_actor(), org_id=ORG, org_update=r.OrganizationUpdate(name="Sessions Two"),
                               db=_Db()))
    assert touches == [("org", ORG)]


def test_an_agent_taken_out_by_an_admin_agent_moves_its_card(monkeypatch, touches, audits):
    from agentvault_registry.routers import organizations as r
    org = _org()
    _as(monkeypatch, org, types.SimpleNamespace(kind="agent", ref=OTHER, level="admin"))
    agent = types.SimpleNamespace(did=AGENT, organization_id=ORG, team_id=None)
    db = _Db(("FROM agents", _Result(obj=agent)))
    _run(r.unassign_agent_from_org(actor=_agent_actor(OTHER), org_id=ORG, agent_did=AGENT, db=db))
    assert agent.organization_id is None and touches == [("agents", (AGENT,))]
    assert ("agent", OTHER, "agent_unassign") in audits


def test_an_assign_moves_the_card_and_the_owner_still_assigns_only_its_own(monkeypatch, touches):
    from agentvault_registry.routers import organizations as r
    org = _org()

    async def perm(org_id, developer, db, required_role=None):
        return org
    monkeypatch.setattr(r, "get_organization_with_permission", perm)
    agent = types.SimpleNamespace(did=AGENT, organization_id=None, team_id=None, creator_developer_id=6)
    db = _Db(("FROM agents", _Result(obj=agent)), ("count(", _Result(scalar=0)))
    dev = types.SimpleNamespace(id=6)
    _run(r.assign_agent_to_org(org_id=ORG, agent_did=AGENT, team_id=None, developer=dev, db=db))
    assert agent.organization_id == ORG and touches == [("agents", (AGENT,))]
    agent2 = types.SimpleNamespace(did=OTHER, organization_id=None, team_id=None, creator_developer_id=7)
    with pytest.raises(HTTPException) as e:
        _run(r.assign_agent_to_org(org_id=ORG, agent_did=OTHER, team_id=None, developer=dev,
                                   db=_Db(("FROM agents", _Result(obj=agent2)))))
    assert e.value.status_code == 403 and "agent-requests" in e.value.detail


def test_deleting_the_organization_moves_its_agents_cards_before_they_leave(monkeypatch, touches):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import org_treasury
    from agentvault_registry.services.organization_service import OrganizationService
    org = _org()

    async def perm(org_id, developer, db, required_role=None):
        return org

    async def none(db, org_id):
        return []

    async def deleted(db, org_id):
        return True
    monkeypatch.setattr(r, "get_organization_with_permission", perm)
    monkeypatch.setattr(org_treasury, "org_treasury_blockers", none)
    monkeypatch.setattr(OrganizationService, "delete_organization", staticmethod(deleted))
    db = _Db()
    _run(r.delete_organization(org_id=ORG, current_developer=types.SimpleNamespace(id=6), db=db))
    assert touches == [("org", ORG)]
    assert db.sql("UPDATE agents SET organization_id = NULL"), "the agents still leave"


# ── item 8: an agent runs the organization by its live grant ───────────────────────────────────────────────────────
def test_an_agents_level_is_the_highest_slice_its_grant_covers():
    from agentvault_registry.services import org_actor, org_authz
    slices = org_authz.ORG_ROLE_PERMISSION_DEFAULTS
    assert org_actor.level_of_permissions(sorted(slices["member"])) == "member"
    assert org_actor.level_of_permissions(sorted(slices["owner"] | {"authz.delegate"})) == "owner"
    short = sorted(slices["admin"] - {"gov.vote"})
    assert org_actor.level_of_permissions(short) == "member", "a slice is covered whole or not at all"
    assert org_actor.level_of_permissions([]) is None


def _authority_db(*, status="active", org_of_agent=ORG, grants=()):
    return _Db(("SELECT status, organization_id FROM agents", _Result([(status, org_of_agent)])),
               ("FROM agent_delegation_grants", _Result([(list(g),) for g in grants])))


def test_an_agent_acts_by_its_live_grant_and_never_where_only_people_may(monkeypatch):
    from agentvault_registry.services import org_actor, org_authz
    from agentvault_registry.services.organization_service import OrganizationService
    org = _org()

    async def get(db, org_id, **kw):
        return org
    monkeypatch.setattr(OrganizationService, "get_organization", staticmethod(get))
    admin = sorted(org_authz.ORG_ROLE_PERMISSION_DEFAULTS["admin"])
    _org_, who = _run(org_actor.org_authority(_authority_db(grants=[admin]), ORG, _agent_actor(), "admin"))
    assert (who.kind, who.level, who.ref) == ("agent", "admin", AGENT)
    with pytest.raises(HTTPException) as e:
        _run(org_actor.org_authority(_authority_db(grants=[admin]), ORG, _agent_actor(), "owner"))
    assert e.value.status_code == 403 and "holds admin authority" in e.value.detail and "needs owner" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _run(org_actor.org_authority(_authority_db(grants=[admin]), ORG, _agent_actor(), "guest", people_only=True))
    assert e.value.status_code == 403
    for db in (_authority_db(status="suspended", grants=[admin]), _authority_db(org_of_agent="other", grants=[admin]),
               _authority_db(grants=[])):
        with pytest.raises(HTTPException) as e:
            _run(org_actor.org_authority(db, ORG, _agent_actor(), "member"))
        assert e.value.status_code == 403 and "holds no authority" in e.value.detail


def test_a_person_still_acts_by_the_membership_role(monkeypatch):
    from agentvault_registry.services import org_actor
    from agentvault_registry.services.organization_service import OrganizationService
    org = _org()
    asked = []

    async def get(db, org_id, **kw):
        return org

    async def check(db, org_id, developer_id, required_role=None):
        asked.append(required_role)
        return required_role != "owner"
    monkeypatch.setattr(OrganizationService, "get_organization", staticmethod(get))
    monkeypatch.setattr(OrganizationService, "check_member_permission", staticmethod(check))
    db = _Db(("FROM organization_members", _Result([("admin",)])))
    _o, who = _run(org_actor.org_authority(db, ORG, _dev_actor(7), "admin"))
    assert (who.kind, who.level) == ("developer", "admin") and asked == ["admin"]
    with pytest.raises(HTTPException) as e:
        _run(org_actor.org_authority(db, ORG, _dev_actor(7), "owner"))
    assert e.value.status_code == 403


def _route(path, method):
    from agentvault_registry.routers import organizations as r
    return next(rt for rt in r.router.routes if rt.path == path and method in rt.methods)


def _takes_agents(path, method):
    from agentvault_registry.security import get_current_actor_for_read_or_key
    deps = [d.call for d in _route(path, method).dependant.dependencies]
    return get_current_actor_for_read_or_key in deps


def test_the_management_routes_take_an_agent_and_the_money_and_ownership_stay_with_people():
    base = "/api/v1/organizations"
    for path, method in (("/{org_id}", "GET"), ("/{org_id}", "PUT"), ("/{org_id}/settings", "GET"),
                         ("/{org_id}/settings", "PUT"), ("/{org_id}/members", "GET"), ("/{org_id}/invite", "POST"),
                         ("/{org_id}/invitations", "GET"), ("/{org_id}/invitations/{invitation_id}", "DELETE"),
                         ("/{org_id}/members/{developer_id}", "DELETE"),
                         ("/{org_id}/members/{developer_id}/role", "PUT"),
                         ("/{org_id}/agents/{agent_did}/unassign", "POST"), ("/{org_id}/agents", "GET"),
                         ("/{org_id}/logo", "PUT"), ("/{org_id}/agent-requests", "POST"),
                         ("/{org_id}/agent-requests/{request_id}/accept", "POST")):
        assert _takes_agents(base + path, method), (path, method)
    for path, method in (("/{org_id}", "DELETE"), ("/{org_id}/treasury/fund", "POST"),
                         ("/{org_id}/treasury/sweep", "POST"), ("/{org_id}/ownership/transfer", "POST"),
                         ("/{org_id}/agents/grant-bulk", "POST"), ("/{org_id}/members/{developer_id}/approver", "PUT"),
                         ("/{org_id}/agents/{agent_did}/assign", "POST")):
        assert not _takes_agents(base + path, method), (path, method)


def test_an_agent_invites_as_itself_and_its_owner_is_recorded(monkeypatch, audits):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services.organization_service import InvitationService
    org = _org()
    _as(monkeypatch, org, types.SimpleNamespace(kind="agent", ref=OTHER, level="admin", agent_did=OTHER))
    seen = {}

    async def create(db, **kw):
        seen.update(kw)
        return types.SimpleNamespace(id="inv_1", token="t",
                                     expires_at=types.SimpleNamespace(isoformat=lambda: "t")), True
    monkeypatch.setattr(InvitationService, "create_invitation", staticmethod(create))
    db = _Db(("SELECT a.creator_developer_id, c.name FROM agents", _Result([(9, "session-lead")])))
    _run(r.invite_member(actor=_agent_actor(OTHER), org_id=ORG, invite=r.MemberInvite(email="a@b.example"), db=db))
    assert seen["invited_by_id"] == 9 and seen["inviter_name"] == "session-lead, an agent of TheProtocol Sessions"
    assert ("agent", OTHER, "invite") in audits


# ── item 3: the hosted logo ─────────────────────────────────────────────────────────────────────────────────────────
def _upload(data, name="logo.png"):
    from starlette.datastructures import UploadFile
    return UploadFile(file=io.BytesIO(data), filename=name)


def test_a_logo_is_a_small_png_or_jpeg_hosted_here(monkeypatch, touches, audits):
    from agentvault_registry.routers import organizations as r
    _as(monkeypatch, _org(), types.SimpleNamespace(kind="developer", ref="6", level="admin"))
    db = _Db(("FROM organization_logos", _Result(obj=None)))
    out = _run(r.upload_organization_logo(actor=_dev_actor(), org_id=ORG, file=_upload(PNG), db=db))
    row = db.added[0]
    assert (row.content_type, row.size, row.data) == ("image/png", len(PNG), PNG)
    assert out["logo"] == f"/api/v1/organizations/{ORG}/logo?v={row.sha256[:12]}" and touches == [("org", ORG)]
    assert _run(r.upload_organization_logo(actor=_dev_actor(), org_id=ORG, file=_upload(JPEG),
                                           db=_Db(("FROM organization_logos", _Result(obj=None)))))["content_type"] \
        == "image/jpeg"
    for data, code in ((b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", 415), (b"GIF89a" + b"0" * 20, 415),
                       (PNG + b"0" * (256 * 1024), 413)):
        with pytest.raises(HTTPException) as e:
            _run(r.upload_organization_logo(actor=_dev_actor(), org_id=ORG, file=_upload(data), db=_Db()))
        assert e.value.status_code == code


def test_the_logo_is_served_from_this_origin_with_no_sniffing_and_no_script():
    from agentvault_registry.routers import organizations as r
    resp = _run(r.get_organization_logo(org_id=ORG, db=_Db(("FROM organization_logos", _Result([("image/png", PNG,
                                                                                                    SHA)])))))
    assert resp.body == PNG and resp.media_type == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff" and "default-src 'none'" in \
        resp.headers["content-security-policy"]
    with pytest.raises(HTTPException) as e:
        _run(r.get_organization_logo(org_id=ORG, db=_Db()))
    assert e.value.status_code == 404


def test_an_organizations_answer_names_its_hosted_logo_never_another_hosts():
    from agentvault_registry.routers import organizations as r
    assert "logo" in r.OrganizationResponse.model_fields and "listed" in r.OrganizationResponse.model_fields
    paths = _run(r._logo_paths(_Db(("FROM organization_logos", _Result([(ORG, SHA)]))), [ORG]))
    assert paths == {ORG: f"/api/v1/organizations/{ORG}/logo?v={SHA[:12]}"}


# ── item 2: "show my org" ──────────────────────────────────────────────────────────────────────────────────────────
def test_show_my_org_is_set_by_the_agent_itself_or_its_creator(monkeypatch, touches, audits):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services.organization_service import OrganizationService

    async def get(db, org_id, **kw):
        return _org()
    monkeypatch.setattr(OrganizationService, "get_organization", staticmethod(get))
    db = _Db(("SELECT creator_developer_id, organization_id FROM agents", _Result([(6, ORG)])))
    out = _run(r.set_agent_org_mark(actor=_agent_actor(), org_id=ORG, agent_did=AGENT, body=r.OrgMarkUpdate(show=False),
                                    db=db))
    assert out == {"agent_did": AGENT, "show_org": False, "org_mark_public": False}
    assert db.sql("UPDATE agents SET show_org")[0][1] == {"s": False, "d": AGENT} and touches == [("agents", (AGENT,))]
    out = _run(r.set_agent_org_mark(actor=_dev_actor(6), org_id=ORG, agent_did=AGENT, body=r.OrgMarkUpdate(show=True),
                                    db=db))
    assert out["org_mark_public"] is True
    for actor, code in ((_agent_actor(OTHER), 403), (_dev_actor(7), 403)):
        with pytest.raises(HTTPException) as e:
            _run(r.set_agent_org_mark(actor=actor, org_id=ORG, agent_did=AGENT, body=r.OrgMarkUpdate(show=True), db=db))
        assert e.value.status_code == code
    with pytest.raises(HTTPException) as e:
        _run(r.set_agent_org_mark(actor=_agent_actor(), org_id=ORG, agent_did=AGENT, body=r.OrgMarkUpdate(show=True),
                                  db=_Db(("SELECT creator_developer_id", _Result([(6, "another-org")])))))
    assert e.value.status_code == 404


# ── polish 9: join requests ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def org_service(monkeypatch):
    from agentvault_registry.services.organization_service import OrganizationService
    state = {"member": True}

    async def get(db, org_id, **kw):
        return _org()

    async def check(db, org_id, developer_id, required_role=None):
        return state["member"]
    monkeypatch.setattr(OrganizationService, "get_organization", staticmethod(get))
    monkeypatch.setattr(OrganizationService, "check_member_permission", staticmethod(check))
    return state


def _agents_row(creator=6, org=None, status="active"):
    return ("SELECT creator_developer_id, organization_id, status FROM agents", _Result([(creator, org, status)]))


def test_an_agent_asks_to_join_for_itself_and_the_admins_hear_it(monkeypatch, org_service, audits):
    from agentvault_registry.routers import organizations as r
    told = []

    async def tell(db, org, did, kind):
        told.append((did, kind))
    monkeypatch.setattr(r, "_tell_admins", tell)
    db = _Db(_agents_row(), ("status = 'pending'", _Result([])))
    out = _run(r.create_agent_request(actor=_agent_actor(), org_id=ORG, body=r.AgentRequestIn(note="I do the docs"),
                                      db=db))
    assert out["status"] == "pending" and out["requested_by_kind"] == "agent" and out["id"].startswith("oar_")
    ins = db.sql("INSERT INTO organization_agent_requests")[0][1]
    assert (ins["d"], ins["k"], ins["r"], ins["n"]) == (AGENT, "agent", AGENT, "I do the docs")
    assert told == [(AGENT, "agent")]
    with pytest.raises(HTTPException) as e:
        _run(r.create_agent_request(actor=_agent_actor(), org_id=ORG, body=r.AgentRequestIn(agent_did=OTHER), db=db))
    assert e.value.status_code == 403


def test_a_member_proposes_only_an_agent_it_created_and_only_once(monkeypatch, org_service):
    from agentvault_registry.routers import organizations as r

    async def tell(db, org, did, kind):
        return None
    monkeypatch.setattr(r, "_tell_admins", tell)
    body = r.AgentRequestIn(agent_did=AGENT)
    for db, code in ((_Db(_agents_row(creator=7)), 403),                          # not the creator
                     (_Db(_agents_row(org=ORG)), 409),                            # already in
                     (_Db(_agents_row(status="suspended")), 409),
                     (_Db(_agents_row(), ("status = 'pending'", _Result([("oar_x",)]))), 409)):  # one open request
        with pytest.raises(HTTPException) as e:
            _run(r.create_agent_request(actor=_dev_actor(6), org_id=ORG, body=body, db=db))
        assert e.value.status_code == code
    org_service["member"] = False
    with pytest.raises(HTTPException) as e:
        _run(r.create_agent_request(actor=_dev_actor(6), org_id=ORG, body=body, db=_Db(_agents_row())))
    assert e.value.status_code == 403
    org_service["member"] = True
    out = _run(r.create_agent_request(actor=_dev_actor(6), org_id=ORG, body=body, db=_Db(_agents_row())))
    assert out["requested_by_kind"] == "developer" and out["requested_by_ref"] == "6"


def test_an_admin_agent_accepts_a_request_once_and_the_agent_joins_as_by_assign(monkeypatch, audits):
    from agentvault_registry.routers import organizations as r
    org = _org()
    _as(monkeypatch, org, types.SimpleNamespace(kind="agent", ref=OTHER, level="admin", agent_did=OTHER,
                                                developer_id=None))
    attached = []

    async def attach(db, org, agent, *, team_id, granted_by, **kw):
        # V0658 (s): an accept may name the organization it leaves, and says who decides (what it may be told)
        attached.append((agent.did, team_id, granted_by))

    async def inviter(db, org, who):
        return 9, "x"
    monkeypatch.setattr(r, "_attach_agent", attach)
    monkeypatch.setattr(r, "_inviter", inviter)
    monkeypatch.setattr(r, "_tell_requester", lambda *a, **k: None)
    agent = types.SimpleNamespace(did=AGENT, status="active")
    claims = iter([1, 0])
    db = _Db(("SELECT agent_did, status FROM organization_agent_requests", _Result([(AGENT, "pending")])),
             ("UPDATE organization_agent_requests SET status", lambda sql, p: _Result(rowcount=next(claims))),
             ("FROM agents", _Result(obj=agent)))
    out = _run(r.accept_agent_request(actor=_agent_actor(OTHER), org_id=ORG, request_id="oar_1",
                                      body=r.AgentRequestDecision(), db=db))
    assert out["status"] == "accepted" and attached == [(AGENT, None, 9)]
    assert db.sql("UPDATE organization_agent_requests SET status")[0][1]["k"] == "agent"
    with pytest.raises(HTTPException) as e:
        _run(r.accept_agent_request(actor=_agent_actor(OTHER), org_id=ORG, request_id="oar_1",
                                    body=r.AgentRequestDecision(), db=db))
    assert e.value.status_code == 409 and len(attached) == 1
    assert ("agent", OTHER, "agent_request_accepted") in audits


def test_only_the_one_who_asked_or_the_creator_withdraws(monkeypatch):
    from agentvault_registry.routers import organizations as r
    row = ("FROM organization_agent_requests r LEFT JOIN agents a", _Result([(AGENT, "agent", AGENT, "pending", 6)]))
    with pytest.raises(HTTPException) as e:
        _run(r.withdraw_agent_request(actor=_dev_actor(7), org_id=ORG, request_id="oar_1", db=_Db(row)))
    assert e.value.status_code == 403
    db = _Db(row, ("SET status = 'withdrawn'", _Result(rowcount=1)))
    assert _run(r.withdraw_agent_request(actor=_dev_actor(6), org_id=ORG, request_id="oar_1", db=db))["status"] \
        == "withdrawn"


# ── item 6 and polish 10: the public lists ─────────────────────────────────────────────────────────────────────────
def test_the_listed_feed_names_only_listed_organizations_with_hosted_logos_and_its_home(monkeypatch):
    from agentvault_registry.routers import organizations as r
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_origin", lambda: "https://eu.example")
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_url_static", lambda: "https://eu.example/ui")
    row = (ORG, "sessions", "Sessions", "We ship", "javascript:alert(1)", SHA, None, 3, 7, 2)
    db = _Db(("SELECT count(*) FROM organizations o", _Result(scalar=1)), ("ORDER BY lower(o.name)", _Result([row])))
    out = _run(r.list_listed_organizations(limit=200, offset=0, db=db))
    assert all("((o.settings->'public_listing')::text = 'true')" in sql for sql, _ in db.calls)
    org = out["organizations"][0]
    assert org["logo"] == f"https://eu.example/api/v1/organizations/{ORG}/logo?v={SHA[:12]}"
    assert org["website"] is None, "only an http(s) address is shown"
    assert (org["member_count"], org["agent_count"], org["settled_work"]) == (3, 7, 2)
    assert out["home"]["console"] == "https://eu.example/ui" and out["total"] == 1


def test_both_public_listings_ask_one_opt_in_test_and_carry_the_logo_and_the_website():
    from agentvault_registry.routers import organizations as r
    pred = "((o.settings->'public_transparency_opt_in')::text = 'true')"
    db = _Db(("WITH worker AS", _Result([])))
    _run(r.discover_firms(limit=12, db=db))
    sql = db.calls[0][0]
    assert pred in sql and "->>'public_transparency_opt_in'" not in sql
    row = (ORG, "Sessions", "sessions", "d", "topic", None, "https://example.org")
    db = _Db(("FROM organizations o LEFT JOIN conversations", _Result([row])), ("FROM organization_logos",
                                                                                 _Result([(ORG, SHA)])))
    out = _run(r.list_transparent_organizations(limit=25, db=db))
    assert pred in db.calls[0][0]
    assert out["organizations"][0]["website"] == "https://example.org"
    assert out["organizations"][0]["logo"] == f"/api/v1/organizations/{ORG}/logo?v={SHA[:12]}"


# ── items 5 and 11: the room names its organization, by its live name ─────────────────────────────────────────────
def test_the_room_shows_its_organization_and_its_hosted_logo():
    from agentvault_registry.services import org_mark
    out = _run(org_mark.room_org(_Db(("FROM organizations o LEFT JOIN organization_logos",
                                      _Result([(ORG, "sessions", "Sessions", SHA, {"public_listing": "true"})]))), ORG))
    assert out == {"id": ORG, "slug": "sessions", "name": "Sessions",
                   "logo": f"/api/v1/organizations/{ORG}/logo?v={SHA[:12]}", "listed": False}


def test_a_counterpartys_mark_is_its_homes_statement(monkeypatch):
    from agentvault_registry.services import org_mark
    mirror = {"extensions": [{"uri": org_mark.ORG_EXTENSION_URI, "params": {"name": "Asia Org", "slug": "asia"}}]}
    db = _Db(("SELECT 1 FROM agents", _Result([])), ("FROM agent_cards", _Result([(mirror,)])))
    assert _run(org_mark.mark_for_did(db, OTHER))["name"] == "Asia Org"

    async def state(db, did):
        return {"name": "Sessions"}
    monkeypatch.setattr(org_mark, "card_state", state)
    assert _run(org_mark.mark_for_did(_Db(("SELECT 1 FROM agents", _Result([(1,)]))), AGENT)) == {"name": "Sessions"}


def test_the_open_room_answer_carries_the_live_name(monkeypatch):
    from agentvault_registry.routers import chat
    from agentvault_registry.services import chat_service as cs
    from agentvault_registry.services import org_mark
    conv = types.SimpleNamespace(id="c1", kind="org", title="Old Name", mode="open", topic=None, genesis=None)

    async def open_room(db, actor, org_id):
        return conv, False, types.SimpleNamespace(state="active", can_post=True)

    async def role(db, org_id, actor):
        return "owner"

    async def room_org(db, org_id):
        return {"id": ORG, "slug": "s", "name": "New Name", "logo": None, "listed": False}
    monkeypatch.setattr(cs, "open_org_room", open_room)
    monkeypatch.setattr(cs, "actor_org_role", role)
    monkeypatch.setattr(cs, "actor_from_auth", lambda a: types.SimpleNamespace(key="d:6"))
    monkeypatch.setattr(org_mark, "room_org", room_org)
    fn = getattr(chat.open_org_room, "__wrapped__", chat.open_org_room)
    out = _run(fn(org_id=ORG, actor_dict=_dev_actor(), db=_Db()))
    assert out["title"] == "New Name" and out["room"]["title"] == "New Name" and out["room"]["org"]["name"] == "New Name"
