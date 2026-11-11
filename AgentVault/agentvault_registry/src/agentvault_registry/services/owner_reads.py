"""V0658 (q): reading follows ownership. Which parties of a Guild order or a contract are a developer's.

The maintainer's report (sessions' room seq 2105): he owns the agents on an order and the organization they work in,
and he saw nothing of it unless the right agent was selected in the acting-agent switcher. Writing is still the acting
agent's (every Guild and contract action takes an agent token); reading is the owner's, whichever agent is selected.

A party (an agent DID on the order or the contract) is the developer's when

  * he created the agent (`agents.creator_developer_id`), via "agent"; or
  * the agent is in an active organization he owns (`agents.organization_id`, `organizations.owner_id`) and its
    creator is an active member of that organization (`organization_members`), via "organization": the owner of the
    organization reads the orders and contracts of the agents its members bring.

The assignment alone is not the relationship. It outlives its creator's membership on purpose (§ORGLIFE L2: a removal
leaves the record, and list_organization_agents reports it as `creator_is_member`), so a removed member's agent, still
assigned, is not the owner's to read: the §ORGLEAK class, a link that outlives the relationship becoming a read
authority. The test here is that report's `creator_is_member` (its "or the owner" half is the "agent" road). An agent
that joined by its own request while its creator is no member does not count either.

There is no treasury road: an organization's treasury is keyless (services/org_treasury), so it never posts, bids or
signs a contract, and no party seat holds it.

ONE rule, written twice on purpose and tested as one: `MY_PARTY_DIDS` is the SQL (the developer's party DIDs), which
the list reads ask through `owned_by_sql`; `owned_parties` is the Python that names each party of a row (its role, its
name, and which road made it his). The real-Postgres test (tests/test_owner_reads_db.py) proves the two agree on the
same rows.

The Guild's deliverable is not this rule (routers/guild.py `_may_see_deliverable`): it is the parties' and their
creators' (`created_a_party`), and the owner's of the organization the work was done for (`owns_an_organization` over
the order's firm). The owner of an organization a member's agent works in reads that order and its parties, not the
work the agent did on its own account.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import text

GUILD_ROLES: Tuple[Tuple[str, str], ...] = (("poster", "poster_did"), ("worker", "worker_did"))
CONTRACT_ROLES: Tuple[Tuple[str, str], ...] = (("client", "client_did"), ("provider", "provider_did"))

# The developer's party DIDs (`:dev`): the agents he created, and the agents in an active organization he owns that an
# active member of it brought (uq_org_members makes the membership join one row per agent). Its aliases are its own,
# so it never reads the row of the statement it sits in.
MY_PARTY_DIDS = (
    "SELECT ag.did FROM agents ag WHERE ag.creator_developer_id = :dev"
    " UNION SELECT ag.did FROM agents ag"
    " JOIN organizations org ON org.id = ag.organization_id AND org.owner_id = :dev AND org.is_active"
    " JOIN organization_members mem ON mem.organization_id = org.id"
    " AND mem.developer_id = ag.creator_developer_id AND mem.is_active")


def owned_by_sql(*columns: str) -> str:
    """A WHERE condition for a list read: true when a party in these DID columns of the row is the developer's (`:dev`).

    Set first: his party DIDs are one array, computed once per column for the whole statement (an InitPlan each, never
    once per row), and each column meets it with `= ANY`, which the column's index answers. The first cut asked a
    correlated EXISTS per row, which read every order and contract on the registry however little he owns (measured on
    Postgres 18.6 with 200k orders: 4.2 s that way, 1.2 ms set first, the same rows)."""
    mine = "ARRAY(" + MY_PARTY_DIDS + ")"
    return "(" + " OR ".join(f"{c} = ANY({mine})" for c in columns) + ")"


async def created_a_party(db, developer_id: Optional[int], dids: Sequence[Optional[str]]) -> bool:
    """Did this developer create any of these agents? The "agent" road alone, one statement."""
    dids = [d for d in dids if d]
    if developer_id is None or not dids:
        return False
    return (await db.execute(text(
        "SELECT 1 FROM agents WHERE did = ANY(:d) AND creator_developer_id = :dev LIMIT 1"),
        {"d": dids, "dev": developer_id})).first() is not None


async def owns_an_organization(db, developer_id: Optional[int], org_ids: Iterable[Optional[str]]) -> bool:
    """Does this developer own any of these organizations, and is it active? One statement."""
    ids = sorted({str(x) for x in org_ids if x})
    if developer_id is None or not ids:
        return False
    return (await db.execute(text(
        "SELECT 1 FROM organizations WHERE id = ANY(:o) AND owner_id = :dev AND is_active LIMIT 1"),
        {"o": ids, "dev": developer_id})).first() is not None


async def owned_parties(db, developer_id: Optional[int], rows: Sequence[Mapping[str, Any]],
                        roles: Sequence[Tuple[str, str]]) -> List[List[Dict[str, Any]]]:
    """For each row, the parties that are the developer's, in the order of `roles`:
    `{"role", "agent_did", "name", "via", "organization_id", "organization_name"}` (the organization fields set when the
    road is "organization"). A row with none of his parties gets an empty list. Two statements for the whole page."""
    out: List[List[Dict[str, Any]]] = [[] for _ in rows]
    dids = sorted({str(r.get(col)) for r in rows for _role, col in roles if r.get(col)})
    if developer_id is None or not dids:
        return out
    orgs = (await db.execute(text(
        "SELECT id, name FROM organizations WHERE owner_id = :dev AND is_active"),
        {"dev": developer_id})).mappings().all()
    my_orgs = {str(o["id"]): o for o in orgs}
    agents = (await db.execute(text(
        "SELECT a.did, a.creator_developer_id, a.organization_id,"
        " EXISTS (SELECT 1 FROM organization_members m WHERE m.organization_id = a.organization_id"
        " AND m.developer_id = a.creator_developer_id AND m.is_active) AS creator_is_member,"
        " (SELECT ac.name FROM agent_cards ac WHERE ac.agent_did = a.did ORDER BY ac.updated_at DESC LIMIT 1) AS name"
        " FROM agents a WHERE a.did = ANY(:d)"), {"d": dids})).mappings().all()
    by_did = {str(a["did"]): a for a in agents}
    for i, row in enumerate(rows):
        for role, col in roles:
            did = row.get(col)
            if not did:
                continue
            did = str(did)
            a = by_did.get(did)
            if a is None:
                continue
            org = None
            if a.get("creator_developer_id") == developer_id:
                via = "agent"
            elif (a.get("organization_id") is not None and str(a["organization_id"]) in my_orgs
                  and a.get("creator_is_member")):
                via, org = "organization", my_orgs[str(a["organization_id"])]
            else:
                continue
            out[i].append({
                "role": role, "agent_did": did, "name": a.get("name") or None, "via": via,
                "organization_id": str(org["id"]) if org is not None else None,
                "organization_name": org.get("name") if org is not None else None,
            })
    return out
