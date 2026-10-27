"""GraphQL over the Directory — QUERIES ONLY. There is no mutation type: nothing writes through GraphQL."""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional

import strawberry
from strawberry.types import Info

from .board import row_figures


@strawberry.type
class Bond:
    status: str
    is_bonded: bool
    amount: Optional[str]
    currency: Optional[str]


@strawberry.type
class Enforcement:
    is_enforced: bool
    status: Optional[str]


@strawberry.type(description="A registry's members, counts only (its GET /api/v1/membership/stats, read by this Directory).")
class MembershipFigures:
    state: str = strawberry.field(description="The LAST read: ok | absent (the registry does not serve the figure) | "
                                              "unreadable (the read failed; the figures below are from the last good read).")
    mode: Optional[str] = strawberry.field(description="What weighs a vote there: lock | member.", default=None)
    members: Optional[int] = None
    joined_30d: Optional[int] = None
    left_30d: Optional[int] = None
    presence_mode: Optional[str] = strawberry.field(description="Whether a binding vote needs its human's confirmation: off | conditional | required.", default=None)
    min_bond_age_days: Optional[int] = None
    tenure_full_days: Optional[int] = None
    as_of: Optional[str] = strawberry.field(description="The registry's own time for these figures.", default=None)
    read_at: Optional[float] = strawberry.field(description="When this Directory last read them successfully.", default=None)
    checked_at: Optional[float] = strawberry.field(description="When this Directory last tried.", default=None)
    error: Optional[str] = strawberry.field(description="The last failure, verbatim; null after a good read.", default=None)


@strawberry.type(description="One commons season as its registry publishes it: budget and counts, never a ballot.")
class CommonsSeasonFigures:
    id: int
    title: Optional[str] = None
    status: Optional[str] = strawberry.field(description="open | closed | paid | cancelled", default=None)
    currency: Optional[str] = None
    budget: Optional[str] = None
    paid_total: Optional[str] = None
    submissions: Optional[int] = None
    ballots: Optional[int] = None
    opens_at: Optional[str] = None
    ends_at: Optional[str] = None
    closed_at: Optional[str] = None
    paid_at: Optional[str] = None
    cancelled_at: Optional[str] = None


@strawberry.type(description="A registry's commons (its GET /api/v1/commons/seasons: the newest three seasons that were "
                             "not cancelled, and how many of its last twenty were).")
class CommonsFigures:
    state: str = strawberry.field(description="The LAST read: ok | switched_off (the registry answered commons_disabled) | "
                                              "absent | unreadable (the figures below are from the last good read).")
    currency: Optional[str] = None
    seasons: List[CommonsSeasonFigures] = strawberry.field(default_factory=list)
    cancelled_recent: Optional[int] = strawberry.field(
        default=None, description="Cancelled seasons among the registry's last twenty (a cancelled season paid nothing).")
    read_at: Optional[float] = None
    checked_at: Optional[float] = None
    error: Optional[str] = None


def _membership_figures(r) -> Optional[MembershipFigures]:
    got = row_figures(r, "membership")
    if got is None:
        return None
    f = got["figures"] or {}
    return MembershipFigures(state=got["state"], mode=f.get("mode"), members=f.get("members"),
                             joined_30d=f.get("joined_30d"), left_30d=f.get("left_30d"),
                             presence_mode=f.get("presence_mode"), min_bond_age_days=f.get("min_bond_age_days"),
                             tenure_full_days=f.get("tenure_full_days"), as_of=f.get("as_of"), read_at=got["read_at"],
                             checked_at=got["checked_at"], error=got["error"])


def _commons_figures(r) -> Optional[CommonsFigures]:
    got = row_figures(r, "commons")
    if got is None:
        return None
    f = got["figures"] or {}
    seasons = [CommonsSeasonFigures(**{k: v for k, v in x.items() if k in CommonsSeasonFigures.__annotations__})
               for x in (f.get("seasons") or []) if isinstance(x, dict) and x.get("id") is not None]
    return CommonsFigures(state=got["state"], currency=f.get("currency"), seasons=seasons,
                          cancelled_recent=f.get("cancelled_recent"), read_at=got["read_at"],
                          checked_at=got["checked_at"], error=got["error"])


@strawberry.type
class Listing:
    """A share listing on a registry's own AGORA venue. The Directory INDEXES venues; it never routes an order —
    a trade is placed at the home registry, in that venue's own currency."""
    id: str
    listing_id: str
    symbol: str
    display_name: Optional[str]
    currency: Optional[str]
    status: Optional[str]
    approved: bool
    ipo_price: Optional[str]
    last_price: Optional[str]
    best_bid: Optional[str]
    best_ask: Optional[str]
    volume_24h: Optional[str]
    trades_24h: int
    organization_id: Optional[str]
    treasury_agent_did: Optional[str]
    source: str
    reachable: bool

    @strawberry.field(description="The registry whose venue carries this listing — where an order actually goes.")
    def venue(self, info: Info) -> Optional["Registry"]:
        r = info.context["store"].get_registry(self.source)
        return _registry(r) if r else None


@strawberry.type
class ListingConnection:
    edges: List[Listing]
    end_cursor: Optional[str]
    has_next_page: bool
    total: Optional[int]


@strawberry.type
class Registry:
    name: str
    trust_domain: Optional[str]
    tier: Optional[str]
    public_url: Optional[str]
    did_namespace: Optional[str]
    verified: bool
    reason: Optional[str]
    reachable: bool
    location: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    card_epoch: Optional[str]
    federation_status: Optional[str]
    hop: Optional[int]
    last_sync_at: Optional[float]
    agents_indexed: int
    listings_indexed: int
    feed_supported: bool = strawberry.field(description="Whether this registry serves the index feed (updated_since / natives_only echoed in applied_filters); false = the Directory reads it whole every cycle.", default=False)
    cards_cursor: Optional[str] = strawberry.field(description="The epoch the Directory has walked this registry's card feed to.", default=None)
    hop_depth: Optional[int] = strawberry.field(description="How deep this Directory walks FROM this registry (per-source budget).", default=None)
    currency: Optional[str] = strawberry.field(description="The settlement currency this registry's own signed card declares.", default=None)
    last_full_at: Optional[float] = strawberry.field(description="When this registry was last read in FULL — the only pass that can notice a card went away.", default=None)
    membership: Optional[MembershipFigures] = strawberry.field(description="Its members, counts only; null until this Directory has checked it.", default=None)
    commons: Optional[CommonsFigures] = strawberry.field(description="Its commons seasons; null until this Directory has checked it.", default=None)

    @strawberry.field
    def listings(self, info: Info) -> List[Listing]:
        return [_listing(l) for l in info.context["store"].list_listings(first=500, source=self.name)["rows"]]

    @strawberry.field
    def operators(self, info: Info) -> List["Registry"]:
        store = info.context["store"]
        return [_registry(r) for r in store.list_registries()
                if r.get("trust_domain") == self.trust_domain and r["name"] != self.name and (r.get("tier") or "") == "cloud-operator"]


@strawberry.type
class Agent:
    card_id: str
    did: Optional[str]
    name: Optional[str]
    human_readable_id: Optional[str]
    description: Optional[str]
    is_active: bool
    issuer: Optional[str]
    shape: Optional[str]
    epoch: Optional[str]
    source: str
    verified: bool
    reachable: bool
    bond: Bond
    enforcement: Enforcement

    @strawberry.field(description="The settlement currency of this agent's HOME — an index row costs an FX hop when it differs from the viewer's.")
    def home_currency(self, info: Info) -> Optional[str]:
        r = info.context["store"].get_registry(self.source)
        return (r or {}).get("currency")

    @strawberry.field(description="The registry this agent lives on (its origin); interactions go there, never through the Directory.")
    def home(self, info: Info) -> Optional[Registry]:
        r = info.context["store"].get_registry(self.source)
        return _registry(r) if r else None

    @strawberry.field(description="The frame whose trust domain the DID's issuer names (a namespaced DID); None for the older shapes.")
    def issuer_frame(self, info: Info) -> Optional[Registry]:
        if not self.issuer:
            return None
        r = info.context["store"].registry_by_trust_domain(self.issuer, tier_prefix="sovereign") or info.context["store"].registry_by_trust_domain(self.issuer)
        return _registry(r) if r else None


@strawberry.type
class AgentConnection:
    edges: List[Agent]
    end_cursor: Optional[str]
    has_next_page: bool
    total: Optional[int]


@strawberry.type
class SourceStatus:
    name: str
    verified: bool
    reason: Optional[str]
    reachable: bool
    federation_status: Optional[str]
    agents_indexed: int
    listings_indexed: int
    feed_supported: bool
    hop: Optional[int] = strawberry.field(description="How many federation hops out this source sits from an anchor (0 = an anchor).", default=None)
    hops: Optional[int] = strawberry.field(description="How deep this Directory walks FROM this source — per-source, so a node with room can index further out than one without (DIRECTORY_HOPS_BY_REGISTRY).", default=None)
    currency: Optional[str] = strawberry.field(description="That registry's settlement currency, off its own signed card.", default=None)
    cards_cursor: Optional[str] = None
    last_sync_at: Optional[float]
    last_full_at: Optional[float]
    last_error: Optional[str]


@strawberry.type
class DirectoryStatus:
    anchors: List[str]
    sources: List[SourceStatus]
    agents_total: int
    agents_gone: int
    listings_total: int
    registries_total: int
    registries_verified: int
    last_cycle_at: Optional[float]
    last_cycle_seconds: Optional[float]
    last_cycle_number: Optional[int]
    last_cycle_was_full: bool
    last_cycle_detail_reads: Optional[int]
    extract_version: Optional[int]
    # §FDLEAK-2 — the FAILURE clock, beside the success one. Without these, an index that has stopped
    # reads exactly like an index with nothing new: `lastCycleAt` simply stops moving, and every other
    # field keeps answering from the last good pass. `indexing` is the verdict a caller should read.
    last_error_at: Optional[float]
    last_error: Optional[str]
    consecutive_failures: int
    seconds_since_last_success: Optional[float]
    indexing: bool


def _registry(r) -> Registry:
    return Registry(name=r["name"], trust_domain=r.get("trust_domain"), tier=r.get("tier"), public_url=r.get("public_url"),
                    did_namespace=r.get("did_namespace"), verified=bool(r.get("verified")), reason=r.get("reason"),
                    reachable=bool(r.get("reachable")), location=r.get("location"), latitude=r.get("latitude"), longitude=r.get("longitude"),
                    card_epoch=r.get("card_epoch"), federation_status=r.get("federation_status"), hop=r.get("hop"),
                    last_sync_at=r.get("last_sync_at"), agents_indexed=int(r.get("agents_indexed") or 0),
                    listings_indexed=int(r.get("listings_indexed") or 0), feed_supported=bool(r.get("feed_supported")),
                    cards_cursor=r.get("cards_cursor"), last_full_at=r.get("last_full_at"),
                    hop_depth=(int(r["hop_depth"]) if r.get("hop_depth") is not None else None), currency=r.get("currency"),
                    membership=_membership_figures(r), commons=_commons_figures(r))


def _listing(l) -> Listing:
    return Listing(id=l["id"], listing_id=l.get("listing_id") or "", symbol=l.get("symbol") or "", display_name=l.get("display_name"),
                   currency=l.get("currency"), status=l.get("status"), approved=bool(l.get("approved")), ipo_price=l.get("ipo_price"),
                   last_price=l.get("last_price"), best_bid=l.get("best_bid"), best_ask=l.get("best_ask"),
                   volume_24h=l.get("volume_24h"), trades_24h=int(l.get("trades_24h") or 0), organization_id=l.get("organization_id"),
                   treasury_agent_did=l.get("treasury_agent_did"), source=l["source"], reachable=bool(l.get("reachable")))


def _agent(a) -> Agent:
    b = json.loads(a.get("bond_json") or "{}"); e = json.loads(a.get("enforcement_json") or "{}")
    return Agent(card_id=a["id"], did=a.get("did"), name=a.get("name"), human_readable_id=a.get("hri"), description=a.get("description"),
                 is_active=bool(a.get("is_active")), issuer=a.get("issuer"), shape=a.get("shape"), epoch=a.get("updated_at"),
                 source=a["source"], verified=bool(a.get("verified")), reachable=bool(a.get("reachable")),
                 bond=Bond(status=b.get("status") or "none", is_bonded=bool(b.get("is_bonded")), amount=b.get("amount"), currency=b.get("currency")),
                 enforcement=Enforcement(is_enforced=bool(e.get("is_enforced")), status=e.get("status")))


@strawberry.type
class Query:
    @strawberry.field
    def registries(self, info: Info) -> List[Registry]:
        return [_registry(r) for r in info.context["store"].list_registries()]

    @strawberry.field
    def registry(self, info: Info, name: str) -> Optional[Registry]:
        r = info.context["store"].get_registry(name)
        return _registry(r) if r else None

    @strawberry.field
    def agents(self, info: Info, first: int = 50, after: Optional[str] = None, issuer: Optional[str] = None,
               name_contains: Optional[str] = None, bonded_only: bool = False, source: Optional[str] = None) -> AgentConnection:
        """The live set: the agents whose source still publishes them.

        §DARKSYNC (2026-09-22): there is deliberately NO `includeGone` argument here, and adding one back is a
        disclosure decision, not a convenience. A row goes unreachable when its source stopped publishing the card,
        and from outside this index that is indistinguishable from the card having gone DARK — an unlisted service
        agent, which every registry's own discovery hides on purpose (V0424: the canaries, svc-sim's clerks,
        svc-market's funders). While the argument existed, one public query handed a caller exactly the set of agents
        their homes had just decided not to show: measured before this change, 43 rows on the EU/ASIA index and 8 on
        the sandbox one, cards and all. A caller that already knows a DID can still resolve it through `agent(did:)`,
        which is the rule the registries keep too — a direct lookup is not enumeration. Nothing is deleted: the rows
        stay marked, and `sweep_source` restores one the moment its source publishes it again."""
        first = max(1, min(first, 500))
        page = info.context["store"].list_agents(first=first, after=after, issuer=issuer, name_contains=name_contains,
                                                 bonded_only=bonded_only, source=source)
        return AgentConnection(edges=[_agent(a) for a in page["rows"]], end_cursor=page["end_cursor"], has_next_page=page["has_next_page"], total=page["total"])

    @strawberry.field
    def listings(self, info: Info, first: int = 50, after: Optional[str] = None, source: Optional[str] = None,
                 symbol: Optional[str] = None, trading_only: bool = False) -> ListingConnection:
        """Every venue in the federated component, in one query: the cross-frame market index the mesh could not
        answer before (a registry only knows its OWN venue plus whatever its ticker env names)."""
        first = max(1, min(first, 500))
        page = info.context["store"].list_listings(first=first, after=after, source=source, symbol=symbol, trading_only=trading_only)
        return ListingConnection(edges=[_listing(l) for l in page["rows"]], end_cursor=page["end_cursor"], has_next_page=page["has_next_page"], total=page["total"])

    @strawberry.field
    def agent(self, info: Info, did: str) -> Optional[Agent]:
        a = info.context["store"].get_agent(did)
        return _agent(a) if a else None

    @strawberry.field
    def status(self, info: Info) -> DirectoryStatus:
        store = info.context["store"]; c = store.counts(); last = store.get_meta("last_cycle", {}) or {}
        err = store.get_meta("last_cycle_error", None) or {}
        _since = (time.time() - float(last["at"])) if last.get("at") else None
        # honest verdict: no failure recorded since the last success, AND that success is recent enough
        # that another cycle should have happened by now (two intervals of slack, never a bare boolean
        # from the error alone — a process killed before it could record anything must not read healthy).
        _budget = float(os.environ.get("DIRECTORY_SYNC_SECONDS", "60")) * 3
        _indexing = (not err) and (_since is not None) and (_since <= _budget)
        return DirectoryStatus(anchors=list(last.get("anchors") or []),
                               sources=[SourceStatus(name=r["name"], verified=bool(r.get("verified")), reason=r.get("reason"), reachable=bool(r.get("reachable")),
                                                     federation_status=r.get("federation_status"), agents_indexed=int(r.get("agents_indexed") or 0),
                                                     listings_indexed=int(r.get("listings_indexed") or 0), feed_supported=bool(r.get("feed_supported")),
                                                     hop=(int(r["hop"]) if r.get("hop") is not None else None),
                                                     hops=(int(r["hop_depth"]) if r.get("hop_depth") is not None else None),
                                                     currency=r.get("currency"),
                                                     cards_cursor=r.get("cards_cursor"), last_sync_at=r.get("last_sync_at"),
                                                     last_full_at=r.get("last_full_at"), last_error=r.get("last_error")) for r in store.list_registries()],
                               agents_total=c["agents"], agents_gone=int(c["agents_including_gone"]) - int(c["agents"]),
                               listings_total=c["listings"], registries_total=c["registries"], registries_verified=c["registries_verified"],
                               last_cycle_at=last.get("at"), last_cycle_seconds=last.get("duration_s"),
                               last_cycle_number=last.get("cycle"), last_cycle_was_full=bool(last.get("full")),
                               last_cycle_detail_reads=last.get("detail_reads"), extract_version=last.get("extract_version"),
                               last_error_at=err.get("at"), last_error=err.get("error"),
                               consecutive_failures=int(err.get("consecutive") or 0),
                               seconds_since_last_success=(round(_since, 1) if _since is not None else None),
                               indexing=_indexing)


schema = strawberry.Schema(query=Query)  # no mutation=…: read-only by construction
