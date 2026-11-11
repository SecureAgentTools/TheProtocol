"""V0657 (b), item 6 (session-code, 2026-11-06): how the Directory reads a registry's listed organizations and the
organization mark on its cards (directory/orgs_reader.py), without the registry package (it runs in the plain CI job).

- the addresses a console loads or opens are rebuilt from the registry's public URL, never taken from the feed: a feed
  naming another host's logo or page sends no viewer anywhere else;
- only an http(s) website is kept; an item that names no organization is dropped;
- the list is read page by page; a registry before V0657 (404) or a failed page is "unread", never "none".
RED on origin/master (ca7020bf): the module does not exist.
"""
import asyncio

from directory import orgs_reader as orr

BASE = "https://eu.theprotocol.cloud"


def test_the_logo_and_the_page_are_rebuilt_on_the_registrys_own_address():
    assert orr.logo_at(BASE, "org-1", "https://eu.theprotocol.cloud/api/v1/organizations/org-1/logo?v=abc123") == \
        f"{BASE}/api/v1/organizations/org-1/logo?v=abc123"
    # a feed naming a third party's address keeps only the version; the address is the registry's
    assert orr.logo_at(BASE, "org-1", "https://tracker.example/pixel.png?v=abc") == \
        f"{BASE}/api/v1/organizations/org-1/logo?v=abc"
    assert orr.logo_at(BASE, "org-1", "https://x.example/l.png?v=<script>") == f"{BASE}/api/v1/organizations/org-1/logo"
    assert orr.logo_at(BASE, "org-1", None) is None, "no logo said, no logo"
    assert orr.logo_at("not an address", "org-1", "x") is None
    assert orr.page_at(BASE + "/", "my org") == f"{BASE}/ui/#/firms?org=my%20org"
    assert orr.home("EU", BASE) == {"name": "EU", "origin": BASE, "console": f"{BASE}/ui"}


def test_an_item_keeps_only_what_a_list_may_show():
    row = orr.org_row({"id": "org-1", "slug": "s", "name": " Sessions ", "description": "d",
                       "website": "javascript:alert(1)", "logo": "/api/v1/organizations/org-1/logo?v=1",
                       "member_count": 3, "agent_count": -1, "settled_work": True}, "EU", BASE)
    assert row["id"] == "EU:org-1" and row["name"] == "Sessions" and row["website"] is None
    assert row["logo"] == f"{BASE}/api/v1/organizations/org-1/logo?v=1" and row["page"] == f"{BASE}/ui/#/firms?org=s"
    assert (row["member_count"], row["agent_count"], row["settled_work"]) == (3, None, None)
    assert orr.org_row({"id": "org-1"}, "EU", BASE) is None
    assert orr.web("https://example.org/x") == "https://example.org/x"


def test_the_mark_on_a_card_is_its_homes_with_the_addresses_rebuilt():
    cd = {"extensions": [{"uri": orr.ORG_EXTENSION_URI, "params": {
        "id": "org-1", "slug": "s", "name": "Sessions", "logo": "https://evil.example/x.png?v=9",
        "home": {"origin": "https://evil.example"}, "page": "https://evil.example/phish"}}]}
    m = orr.org_mark_from_card(cd, "EU", BASE)
    assert m == {"id": "org-1", "slug": "s", "name": "Sessions", "logo": f"{BASE}/api/v1/organizations/org-1/logo?v=9",
                 "page": f"{BASE}/ui/#/firms?org=s", "home": {"name": "EU", "origin": BASE, "console": f"{BASE}/ui"}}
    assert orr.org_mark_from_card({"provider": {"name": "Acme Labs"}}, "EU", BASE) is None


def _fetcher(pages):
    asked = []

    async def fetch(client, url):
        asked.append(url)
        return pages.pop(0)
    return fetch, asked


def test_the_list_is_read_page_by_page_and_a_missing_list_is_unread():
    fetch, asked = _fetcher([({"organizations": [{"id": str(i)} for i in range(500)], "total": 501}, None),
                             ({"organizations": [{"id": "500"}], "total": 501}, None)])
    items, err = asyncio.run(orr.fetch_organizations(fetch, None, BASE))
    assert err is None and len(items) == 501
    assert asked == [f"{BASE}{orr.LISTED}?limit=500&offset=0", f"{BASE}{orr.LISTED}?limit=500&offset=500"]
    fetch, _ = _fetcher([(None, "http 404")])
    assert asyncio.run(orr.fetch_organizations(fetch, None, BASE)) == (None, "http 404")
    fetch, _ = _fetcher([({"nope": 1}, None)])
    assert asyncio.run(orr.fetch_organizations(fetch, None, BASE))[0] is None
