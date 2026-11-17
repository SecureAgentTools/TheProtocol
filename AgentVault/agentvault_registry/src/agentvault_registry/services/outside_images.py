"""V0663 (order gwo_e3187dbb237a06e8261c1dfc, following V0662 item 14): the remaining outside images through the registry.

V0662 served agent card icons from this registry's own origin (services/card_icons, routers/card_icons). Three kinds of
image still loaded from wherever their record said, in every reader's browser:
  - registry_logo     a registry's logo: an ACTIVE peer's signed card's visual.icon_url, made absolute on the peer's own
                      origin, and this registry's own (the frame manifest and core/federation_view.active_peer_entries,
                      the entries the console's federation views and registry-config carry);
  - developer_avatar  developers.avatar_url;
  - flare_logo        developers.flare_logo_url, and the flare a card carries (card_data.flare.logo_url), on a mirrored
                      card as on a native one.
GET /api/v1/public/images?src=<address> (routers/outside_images) serves them through card_icons' guarded, cached path.
It is not an open fetcher: address_kind answers which record names an address, and the route fetches nothing an
answer of None covers. Only absolute http(s) and data: addresses are looked up at all.
"""
from __future__ import annotations

from typing import Any, List, Optional

MAX_ADDRESS = 2048
KINDS = ("registry_logo", "developer_avatar", "flare_logo")


def _usable(url: Any) -> bool:
    if not isinstance(url, str) or not url or len(url) > MAX_ADDRESS:
        return False
    low = url.lower()
    return low.startswith(("https://", "http://", "data:image/"))


def developer_kinds_stmt(url: str):
    from sqlalchemy import or_, select
    from .. import models
    D = models.Developer
    return (select(D.avatar_url == url, D.flare_logo_url == url)
            .where(or_(D.avatar_url == url, D.flare_logo_url == url))
            .limit(1))


async def developer_kinds(db: Any, url: str) -> List[str]:
    """The kinds a developer's record names this address as (its avatar, its flare logo)."""
    row = (await db.execute(developer_kinds_stmt(url))).first()
    if row is None:
        return []
    return [k for k, hit in (("developer_avatar", row[0]), ("flare_logo", row[1])) if hit]


def card_flare_stmt(url: str):
    """A card whose flare names the address: a containment the GIN index on card_data serves."""
    from sqlalchemy import select
    from .. import models
    C = models.AgentCard
    return (select(C.id)
            .where(C.card_data.contains({"flare": {"logo_url": url}}), C.is_active.is_(True))
            .limit(1))


async def card_flare_named(db: Any, url: str) -> List[str]:
    return ["flare_logo"] if (await db.execute(card_flare_stmt(url))).first() is not None else []


async def peer_icon_named(db: Any, redis: Any, url: str) -> bool:
    """Whether a registry logo the console shows is this address: this registry's own and its peers' in the frame
    manifest (registry-config carries it), and every ACTIVE peer's entry as the federation views read it. This
    registry's own logo is absolute on its public host, which need not be the console's origin."""
    from ..core.federation_view import active_peer_entries, build_manifest
    manifest = await build_manifest(db, redis)
    named = [manifest.get("self") or {}, *(manifest.get("peers") or [])]
    if any(isinstance(e, dict) and e.get("icon_url") == url for e in named):
        return True
    return any(e.get("icon_url") == url for e in await active_peer_entries(db, redis))


async def address_kind(db: Any, redis: Any, url: Any) -> Optional[str]:
    """The kind of image a record of this registry names at `url`, or None (then nothing is fetched)."""
    if not _usable(url):
        return None
    kinds = await developer_kinds(db, url)
    if kinds:
        return kinds[0]
    if await card_flare_named(db, url):
        return "flare_logo"
    if await peer_icon_named(db, redis, url):
        return "registry_logo"
    return None
