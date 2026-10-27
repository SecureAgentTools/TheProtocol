"""§TESTBED (2026-09-19): the guild MCP tools carry a refusal's whole sentence.

RFC 7807 errors are application/problem+json; the tools tested startswith("application/json"), fell back to the raw
body cut at 300 characters, and with an issuer-bound DID the bond refusal lost "requires a bond of" (measured: the
federation suite in a kit sandbox read guild_bid's real refusal as none).
"""
import httpx

from agentvault_registry.mcp.tools_guild import _detail_of

_DID = "did:theprotocol:sandbox.larch.theprotocol.cloud:e3804d31-9866-4ef6-8124-4c99ba8558ee"
_SENTENCE = (f"{_DID} holds no reputation bond. Providing services here (bidding on a guild work order) requires a bond "
             f"of 250 locked for this agent; deposit it first.")


def _problem(status=403, detail=_SENTENCE):
    return httpx.Response(status, headers={"content-type": "application/problem+json"},
                          json={"error": {"detail": detail, "type": "forbidden"}, "type": "https://docs.theprotocol.cloud/errors/forbidden",
                                "title": "Forbidden", "status": status, "detail": detail})


def test_a_problem_json_refusal_keeps_its_whole_sentence():
    d = _detail_of(_problem())
    assert d == _SENTENCE and "requires a bond of" in d


def test_plain_json_and_text_still_work():
    assert _detail_of(httpx.Response(400, headers={"content-type": "application/json"}, json={"detail": "bad"})) == "bad"
    assert _detail_of(httpx.Response(502, headers={"content-type": "text/html"}, text="<h1>gateway</h1>")) == "<h1>gateway</h1>"
    assert _detail_of(httpx.Response(500, headers={"content-type": "application/json"}, text="not json")) == "not json"
