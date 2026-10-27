"""§AGORAWORDS Phase 5 (2026-09-22): where the Directory reads a registry's AGORA listings.

The documented name first: every registry since V0419 serves /api/v1/agora. A registry before that answers the listings
COLLECTION with a bare 404 and is read under the old name, which stays live until a later release drops it. The
collection has no business 404 (an unknown id) to be confused with it, so the status alone decides. Kept free of any
registry import, so the Directory's CI job (a plain Python container) can test it.
"""
AGORA_LISTINGS = "/api/v1/agora/listings"
LEGACY_LISTINGS = "/api/v1/exchange/listings"


async def fetch_listings(fetch_json, client, base):
    """(listings document, error) from `fetch_json(client, url)`, asking the old name only after a 404."""
    lst, err = await fetch_json(client, f"{base}{AGORA_LISTINGS}")
    if lst is None and err == "http 404":
        lst, err = await fetch_json(client, f"{base}{LEGACY_LISTINGS}")
    return lst, err
