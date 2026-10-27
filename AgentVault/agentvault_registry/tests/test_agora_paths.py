"""§AGORAWORDS Phase 5 (2026-09-22): a peer dialer asks /api/v1/agora first and falls back to /api/v1/exchange ONLY when
the peer's router does not know the route. The two 404 bodies below are EU's real answers (measured 2026-09-22): an
unknown route, and an unknown listing under a known route."""
import asyncio

from agentvault_registry.core import agora_paths as ap

ROUTE_MISSING = {"error": {"detail": "Not Found", "type": "not_found"}, "type": "https://docs.theprotocol.cloud/errors/not_found",
                 "title": "Not Found", "status": 404, "detail": "Not Found", "instance": "/api/v1/agora/no-such-route"}
LISTING_MISSING = {"error": {"detail": "listing 'NOSUCH' not found", "type": "not_found"}, "type": "https://docs.theprotocol.cloud/errors/not_found",
                   "title": "Not Found", "status": 404, "detail": "listing 'NOSUCH' not found", "instance": "/api/v1/agora/listings/NOSUCH"}


class R:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Client:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def request(self, method, url, **kw):
        self.calls.append((method, url))
        return self.answers[url]


def test_route_missing_tells_the_two_404s_apart():
    assert ap.route_missing(R(404, ROUTE_MISSING)) is True
    assert ap.route_missing(R(404, LISTING_MISSING)) is False
    assert ap.route_missing(R(404, ValueError("html"))) is True
    assert ap.route_missing(R(200, {"listings": []})) is False
    assert ap.route_missing(R(502, {"detail": "Not Found"})) is False


def test_a_new_peer_is_asked_once_under_the_new_name():
    c = Client({"http://p/api/v1/agora/listings": R(200, {"listings": [1]})})
    r = asyncio.run(ap.peer_request(c, "GET", "http://p", "/listings"))
    assert r.status_code == 200 and c.calls == [("GET", "http://p/api/v1/agora/listings")]


def test_an_older_peer_falls_back_once_to_the_old_name():
    c = Client({"http://p/api/v1/agora/listings": R(404, ROUTE_MISSING), "http://p/api/v1/exchange/listings": R(200, {"listings": []})})
    r = asyncio.run(ap.peer_request(c, "GET", "http://p", "/listings"))
    assert r.status_code == 200
    assert c.calls == [("GET", "http://p/api/v1/agora/listings"), ("GET", "http://p/api/v1/exchange/listings")]


def test_a_business_404_is_an_answer_never_reasked():
    c = Client({"http://p/api/v1/agora/listings/NOSUCH": R(404, LISTING_MISSING)})
    r = asyncio.run(ap.peer_request(c, "GET", "http://p", "/listings/NOSUCH"))
    assert r.status_code == 404 and len(c.calls) == 1
