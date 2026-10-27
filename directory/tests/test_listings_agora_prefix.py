"""§AGORAWORDS Phase 5 (2026-09-22): the Directory reads a registry's AGORA listings under /api/v1/agora, and under the
old /api/v1/exchange only when the new route answers 404 (a registry before V0419)."""
import asyncio

from directory.agora_listings import fetch_listings


def _run(answers):
    asked = []

    async def fake_fetch(client, url):
        asked.append(url)
        return answers[url]

    return asked, asyncio.run(fetch_listings(fake_fetch, None, "http://r"))


def test_a_new_registry_is_read_once_under_the_new_name():
    asked, (lst, err) = _run({"http://r/api/v1/agora/listings": ({"listings": []}, None)})
    assert asked == ["http://r/api/v1/agora/listings"] and lst == {"listings": []} and err is None


def test_an_older_registry_is_read_under_the_old_name_after_a_404():
    asked, (lst, err) = _run({"http://r/api/v1/agora/listings": (None, "http 404"),
                              "http://r/api/v1/exchange/listings": ({"listings": [1]}, None)})
    assert asked == ["http://r/api/v1/agora/listings", "http://r/api/v1/exchange/listings"] and lst == {"listings": [1]}


def test_a_server_error_is_not_retried_under_the_old_name():
    asked, (lst, err) = _run({"http://r/api/v1/agora/listings": (None, "http 500")})
    assert asked == ["http://r/api/v1/agora/listings"] and lst is None and err == "http 500"
