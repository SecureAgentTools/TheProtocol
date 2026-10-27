"""§MCPTEST30 (2026-10-01) — the hostile-input probe (api_tests/contracts/input_hygiene.py) and the refusals it
found reasonless.

Every read-only MCP tool with a text argument is asked with a NUL, LIKE's wildcards ending in its escape character and
4,000 characters; a server error is the finding. Measured by hand first, with no login: a NUL answered 500 on
/api/v1/discover and /api/v1/fiat/flare/agent/{did} (sbx-alpha, V0515), and the discover tool said so as
"discover endpoint returned 500", a refusal no judge and no census could read (they matched `HTTP nnn` only).
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re

from agentvault_registry.api_tests.contracts import input_hygiene as IH
from agentvault_registry.api_tests.contracts import pagination_partition as PP
from agentvault_registry.api_tests.contracts import result_shape


def _ro(name):
    return {"readOnlyHint": name.split("_")[-1].startswith(("get", "list", "search"))}


def _schema(name, props, required=()):
    return {"name": name, "inputSchema": {"type": "object", "properties": props, "required": list(required)}}


S = {"type": "string"}


def test_the_targets_are_the_read_tools_with_text_arguments_each_asked_once():
    public = [
        _schema("theprotocol_getThing", {"thing_id": S, "agent_jwt": S, "limit": {"type": "integer"}}, ["thing_id"]),
        _schema("theprotocol_listThings", {"page": {"type": "integer"}, "q": {"type": ["string", "null"]}},
                ["page"]),
        _schema("theprotocol_createThing", {"name": S}),                       # a write: never asked
        _schema("theprotocol_getOnlyAuthed", {"agent_jwt": S}),                # no text argument but a credential
        _schema("theprotocol_getAgentToken", {"client_id": S}),                # left out: a credential exchange
        _schema("theprotocol_searchTools", {"query": S}),
    ]
    admin = [_schema("theprotocol_searchTools", {"query": S}),                 # on both surfaces: public only
             _schema("theprotocol_getAdminThing", {"x": S, "flag": {"type": "boolean"}}, ["flag"])]
    got = IH.targets(public, admin, {"theprotocol_getThing"}, {"theprotocol_listThings"}, _ro)
    assert got == [
        ("theprotocol_getThing", "2", ["thing_id"], {}),
        ("theprotocol_listThings", "3", ["q"], {"page": 1}),
        ("theprotocol_searchTools", "1", ["query"], {}),
        ("theprotocol_getAdminThing", "admin", ["x"], {"flag": False}),
    ]


def test_a_tool_whose_annotation_cannot_be_read_is_never_taken_for_a_read():
    def boom(name):
        raise RuntimeError("no metadata")
    assert IH.targets([_schema("theprotocol_getX", {"a": S})], [], set(), set(), boom) == []


def test_the_running_servers_targets():
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    got = IH.default_targets()
    names = {t[0] for t in got}
    assert len(got) >= 100
    assert "theprotocol_discoverAgents" in names and "theprotocol_getAgentToken" not in names
    assert not names & set(IH.LEFT_OUT)
    for tool, tier, text, _fill in got:
        assert derive_annotations(tool)["readOnlyHint"], tool
        assert text and not set(text) & IH.NEVER_HOSTILE, tool
        assert tier in ("1", "2", "3", "admin")


def _err(text, code="200"):
    return False, {"_text": text}, code


def test_the_answer_kinds():
    answered = lambda ok, inner, code: bool(ok)  # noqa: E731
    assert IH.answer_kind(*_err("Error: InvalidURL: Invalid non-printable ASCII character in URL, '\\x00' at position 52."),
                          answered) == ("unsent", None, None)
    assert IH.answer_kind(*_err("Error: discover endpoint returned 500"), answered)[:2] == ("server_error", 500)
    assert IH.answer_kind(*_err("Error: discover endpoint returned HTTP 400: A NUL character is not valid"),
                          answered)[:2] == ("refused", 400)
    assert IH.answer_kind(True, {"agents": [], "total": 0}, "200", answered)[0] == "rows"


def test_the_verdict_fails_only_on_a_server_error():
    ok, sentence, ev = IH.verdict({"nul": ("server_error", 500, None), "escape": ("rows", None, 3),
                                   "long": ("refused", 404, None)})
    assert ok is False and sentence.startswith("BUG-FIND: hygiene:") and "(nul)" in sentence
    assert ev == {"nul": "server_error HTTP 500", "escape": "3 rows", "long": "refused HTTP 404"}
    assert IH.verdict({"nul": ("no_answer", None, None), "escape": ("no_answer", None, None),
                       "long": ("no_answer", None, None)})[0] is None
    assert IH.verdict({"nul": ("refused", 400, None), "escape": ("refused", 404, None),
                       "long": ("rows", None, 0)})[0] is True
    # a value that never left the tool: the tool interpolates its argument unencoded (V0515 measured 108)
    ok, sentence, _ev = IH.verdict({"nul": ("unsent", None, None), "escape": ("refused", 404, None),
                                    "long": ("rows", None, 0)})
    assert ok is False and "into its URL (nul)" in sentence


def _outcome(name, tier, ok, code, ms, fail, inner, expect_status="success", skip_reason=None):
    return {"tool": name, "healthy": ok and not skip_reason, "error": fail, "skip_reason": skip_reason}


class _Bag:
    developer_jwt = "dev"
    sentinel_jwt = "agent"


def test_the_run_asks_each_value_once_and_records_no_value():
    calls = []

    async def rpc(tool, args, jwt="", timeout=30):
        calls.append((tool, dict(args), jwt))
        v = next(iter(a for k, a in args.items() if k == "thing_id"), None)
        if v and "\x00" in v:
            return False, {"_text": "Error: things returned 500"}, "500"
        return True, {"items": []}, "200"

    out = {}
    todo = [("theprotocol_getThing", "2", ["thing_id"], {"limit": 1}),
            ("theprotocol_getAdminThing", "admin", ["x"], {})]
    asyncio.run(IH.run_hygiene(lambda tier: None if tier == "admin" else rpc, lambda b: b, _Bag(), out, _outcome,
                               lambda ok, inner, code: bool(ok), todo=todo))
    assert [c[0] for c in calls] == ["theprotocol_getThing"] * 3
    assert [c[1]["thing_id"] for c in calls] == [v for _l, v in IH.HOSTILE]
    assert all(c[1]["agent_jwt"] == "agent" and c[1]["limit"] == 1 and c[2] == "dev" for c in calls)
    row = out["hygiene: getThing"]
    assert row["healthy"] is False and row["error"].startswith("BUG-FIND: hygiene:")
    assert row["result_excerpt"]["arguments"] == ["thing_id"]
    blob = json.dumps(out)
    assert "\\u0000" not in blob and "p" * 100 not in blob and "mcp-probe" not in blob
    assert out["hygiene: getAdminThing"]["skip_reason"].startswith("NOT MEASURED")


def test_the_lifecycle_is_registered_and_its_rows_are_synthetic():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    assert any(e["name"] == "input_hygiene" and e["runner"] is L.lifecycle_input_hygiene for e in L.LIFECYCLES)
    assert IH.PREFIX in F._SYNTHETIC_ROW_PREFIXES


def test_a_returned_status_without_the_http_word_is_read_as_a_status():
    # the census, the bounds judge and the list/detail judge all read "<route> returned 500" now
    err = {"jsonrpc": "2.0", "id": 1,
           "result": {"isError": True, "content": [{"type": "text", "text": "Error: discover endpoint returned 500"}]}}
    assert result_shape.reasonless(err) == "500"
    from agentvault_registry.api_tests.contracts import list_detail as LD
    assert LD._HTTP.search("Error: discover endpoint returned 500").group(1) == "500"
    assert PP._HTTP.search("Error: x returned HTTP 404: gone").group(1) == "404"
    assert PP._HTTP.search("Error: returned 5000 rows") is None


_RETURNED_SITE = re.compile(r'f"[^"\n]*?returned \{\w+\.status_code\}[^"\n]*"')


def test_no_mcp_module_ends_a_refusal_at_a_returned_status():
    from agentvault_registry.mcp import refusal
    root = pathlib.Path(refusal.__file__).parent
    sites = sorted((p.name, m.group(0)) for p in root.glob("*.py") for m in _RETURNED_SITE.finditer(p.read_text()))
    assert sites == [], sites


def test_the_discover_tool_carries_the_routes_reason(monkeypatch):
    from agentvault_registry.mcp import tools_discovery as TD

    class _R:
        status_code = 400
        text = json.dumps({"detail": "A NUL character is not valid in a request path or query string."})

        def json(self):
            return json.loads(self.text)

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _R()

    monkeypatch.setattr(TD.httpx, "AsyncClient", _C)
    out = asyncio.run(TD.discover_agents(query="mcp-probe\x00nul"))
    assert out["error"] == ("discover endpoint returned HTTP 400: "
                            "A NUL character is not valid in a request path or query string.")
