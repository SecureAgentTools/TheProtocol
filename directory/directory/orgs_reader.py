"""V0657 (b), item 6 (session-code, 2026-11-06): the organizations a registry LISTS, and the organization mark its cards
carry, as the Directory keeps them.

A registry from V0657 serves its listed organizations at GET /api/v1/organizations/public/listed (only those that chose
to be listed, `public_listing`), and states each agent's organization on the agent's card as the extension
`https://theprotocol.cloud/extensions/v1/org` (only while the organization is listed and the agent shows it). A registry
before V0657 answers the list with a 404: it is read as "this registry does not list organizations", never as "it has
none", and nothing it was holding is swept.

What a registry SAYS about addresses is not taken: the logo and the page a console loads or opens are rebuilt here from
the address this Directory reads the registry at (the public URL its signed card was fetched from), so a feed can never
send a viewer's browser to a third party. A logo is kept only when the registry says it hosts one (and its version
token travels, so a new upload is a new address); a website only when it is an http(s) address.

Kept free of any registry import, so the Directory's CI job (a plain Python container) can test it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlsplit

LISTED = "/api/v1/organizations/public/listed"
ORG_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/org"
PAGE = 500          # the registry's own cap per page
MAX_PAGES = 20      # 10,000 organizations from one registry is far beyond any today; the rest waits for the next cycle
_WEB = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def _str(v: Any, limit: int = 500) -> Optional[str]:
    return v.strip()[:limit] if isinstance(v, str) and v.strip() else None


def origin_of(public_url: Optional[str]) -> Optional[str]:
    """scheme://host[:port] of an http(s) address, else None."""
    if not public_url:
        return None
    try:
        p = urlsplit(public_url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


def web(v: Any) -> Optional[str]:
    """A website a list may link: an http(s) address, else nothing."""
    s = _str(v)
    return s if s and _WEB.match(s) else None


def logo_at(public_url: Optional[str], org_id: str, stated: Any) -> Optional[str]:
    """The organization's logo on its own registry, when the registry says it hosts one: the address is built from the
    registry's public URL and the organization's id (the registry's word only names the version)."""
    origin = origin_of(public_url)
    s = _str(stated, 1000)
    if not origin or not s or not org_id:
        return None
    version = None
    try:
        version = (parse_qs(urlsplit(s).query).get("v") or [None])[0]
    except ValueError:
        version = None
    path = f"{origin}/api/v1/organizations/{quote(str(org_id), safe='')}/logo"
    return f"{path}?v={quote(version, safe='')}" if version and re.fullmatch(r"[A-Za-z0-9]{1,64}", version) else path


def page_at(public_url: Optional[str], slug: Optional[str]) -> Optional[str]:
    """The organization's page on its registry's own console (a registry serves its console at /ui)."""
    origin = origin_of(public_url)
    if not origin or not slug:
        return None
    return f"{origin}/ui/#/firms?org={quote(slug, safe='')}"


def home(name: str, public_url: Optional[str]) -> Dict[str, Optional[str]]:
    origin = origin_of(public_url)
    return {"name": name, "origin": origin, "console": f"{origin}/ui" if origin else None}


def org_row(item: Dict[str, Any], source: str, public_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """One listed organization as the store keeps it, or None when the item names no organization."""
    oid = _str(item.get("id"), 255)
    name = _str(item.get("name"), 255)
    if not oid or not name:
        return None
    slug = _str(item.get("slug"), 255)

    def _n(k: str) -> Optional[int]:
        v = item.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None
    return {"id": f"{source}:{oid}", "org_id": oid, "source": source, "slug": slug, "name": name,
            "description": _str(item.get("description"), 1000), "website": web(item.get("website")),
            "logo": logo_at(public_url, oid, item.get("logo")), "page": page_at(public_url, slug),
            "member_count": _n("member_count"), "agent_count": _n("agent_count"), "settled_work": _n("settled_work")}


def org_mark_from_card(cd: Any, source: str, public_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """The organization mark a NATIVE card carries (its home stated it), with the addresses rebuilt here."""
    if not isinstance(cd, dict):
        return None
    for ext in cd.get("extensions") or []:
        if isinstance(ext, dict) and ext.get("uri") == ORG_EXTENSION_URI and isinstance(ext.get("params"), dict):
            p = ext["params"]
            oid, name = _str(p.get("id"), 255), _str(p.get("name"), 255)
            if not oid or not name:
                return None
            slug = _str(p.get("slug"), 255)
            return {"id": oid, "slug": slug, "name": name, "logo": logo_at(public_url, oid, p.get("logo")),
                    "page": page_at(public_url, slug), "home": home(source, public_url)}
    return None


async def fetch_organizations(fetch_json, client, base: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """(every listed organization, None) from `fetch_json(client, url)`; (None, "http 404") from a registry that does
    not list organizations (before V0657); (None, error) when a page failed; (what was read, "incomplete") past
    MAX_PAGES. The caller sweeps only after a complete read."""
    out: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(MAX_PAGES):
        doc, err = await fetch_json(client, f"{base}{LISTED}?limit={PAGE}&offset={offset}")
        if doc is None:
            return None, err
        items = doc.get("organizations") if isinstance(doc, dict) else None
        if not isinstance(items, list):
            return None, "not an organizations list"
        out.extend(i for i in items if isinstance(i, dict))
        total = doc.get("total") if isinstance(doc, dict) else None
        offset += len(items)
        if not items or not isinstance(total, int) or offset >= total:
            return out, None
    return out, "incomplete"
