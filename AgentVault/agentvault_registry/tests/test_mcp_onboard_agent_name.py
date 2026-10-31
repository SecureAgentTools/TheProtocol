"""§MCPTEST30 (V0650, tester batch 1 item 3, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): the onboarding
rail the manuals teach names the placeholder card after agent_name.

The external test's run 1 created its agents with POST /api/v1/onboard/create_agent (agent_host and agent_name) and the
card came out named after the host: the schema dropped agent_name silently (fixed in V0649, 3cc665f53). The MCP bridges
cannot drive that rail (it takes a Bootstrap-Token header), so earn_onboard_agent_name drives it through the target's
in-target transport. RED on V0649's code: the lifecycle does not exist (and on V0648's registry the row would read the
host's name).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_devtools as D
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


class _Throwaways:
    adopted: List[Tuple[str, str]] = []
    closed = 0

    def __init__(self, rpc, parse, bag, tag):
        pass

    async def developer(self, role: str, verify: bool = True) -> Dict[str, Any]:
        return {"developer_id": 9, "access_token": "dev-jwt", "email": "x@example.com"}

    def adopt(self, did: str, owner_jwt: str) -> None:
        type(self).adopted.append((did, owner_jwt))

    async def close(self) -> None:
        type(self).closed += 1


class _Registry:
    """The bootstrap and create routes as the target answers them, and the card it builds."""

    def __init__(self, *, keeps_name: bool = True, create_code: str = "201", home: Optional[str] = None,
                 manual_url: Optional[str] = None, manual_code: str = "200"):
        self.keeps_name, self.create_code = keeps_name, create_code
        # V0650 (tester batch 2 item 5): the credential's registry_url and the address the served manual names
        self.home, self.manual_url, self.manual_code = home, manual_url, manual_code
        self.card: Dict[str, Any] = {}
        self.calls: List[Tuple[str, str, Dict[str, str]]] = []

    async def http(self, method: str, path: str, *, body: Optional[bytes] = None, bearer: str = "",
                   headers: Optional[Dict[str, str]] = None, **_k) -> Tuple[str, str]:
        self.calls.append((method, path, dict(headers or {})))
        if (method, path) == ("GET", "/api/v1/downloads/CLAUDE.md"):
            line = f"> | `REGISTRY_URL` | `{self.manual_url}` |\n" if self.manual_url else ""
            return self.manual_code, f"# Operator manual\n\n> **This registry, as it answered**\n{line}> | Name | pair-a |\n"
        b = json.loads(body or b"{}")
        if path == "/api/v1/onboard/bootstrap/request-token":
            assert bearer == "dev-jwt"
            return "201", json.dumps({"bootstrap_token": "bt_scripted"})
        if path == "/api/v1/onboard/create_agent":
            # V0650 (e) refuses a special-use host on this rail: the row names one under theprotocol.cloud that no
            # DNS record answers
            assert headers == {"Bootstrap-Token": "bt_scripted"} and b["agent_host"].endswith(".tester.theprotocol.cloud")
            if not self.create_code.startswith("2"):
                return self.create_code, json.dumps({"detail": "refused"})
            slug = b["agent_host"].split("//", 1)[1].split(".", 1)[0]
            self.card = {"id": "card-1", "card_data": {"name": b.get("agent_name") if self.keeps_name else slug}}
            made = {"agent_did": "did:theprotocol:sandbox-a:named", "agent_card_id": "card-1", "client_id": "c",
                    "client_secret": "never-in-a-row"}
            return "201", json.dumps({**made, **({"registry_url": self.home} if self.home else {})})
        raise AssertionError(path)

    async def rpc(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        assert tool == "theprotocol_getAgentCardById" and args == {"card_id": "card-1"}
        return True, {"result": self.card}, "200"


def _run(reg: Optional[_Registry], monkeypatch) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    monkeypatch.setattr(D, "Throwaways", _Throwaways)
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    if reg is not None:
        bag.http_in_target = reg.http   # type: ignore[attr-defined]
    out: Dict[str, dict] = {}

    async def no_rpc(*_a, **_k):
        raise AssertionError("no call expected")
    asyncio.run(D.lifecycle_earn_onboard_agent_name(reg.rpc if reg else no_rpc,
                                                   lambda b: b.get("result") if isinstance(b, dict) else {}, bag, out))
    return out


def test_it_is_registered_and_its_rows_are_read():
    assert "earn_onboard_agent_name" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]
    assert D.ONBOARD_NAMED.startswith(F._SYNTHETIC_ROW_PREFIXES), "a prefix missing there drops the row unread"


def test_the_card_named_after_agent_name_passes_and_keeps_no_secret(monkeypatch):
    _Throwaways.adopted, _Throwaways.closed = [], 0
    out = _run(_Registry(), monkeypatch)
    row = out[D.ONBOARD_NAMED]
    assert row["healthy"] and not row.get("fail_reason"), row
    assert row["result_excerpt"]["card_name"].startswith("MCP tester named card ")
    assert "never-in-a-row" not in repr(out)
    assert _Throwaways.adopted == [("did:theprotocol:sandbox-a:named", "dev-jwt")] and _Throwaways.closed == 1


def test_a_card_named_after_the_host_is_red(monkeypatch):
    out = _run(_Registry(keeps_name=False), monkeypatch)
    row = out[D.ONBOARD_NAMED]
    assert not row["healthy"] and "named after the host" in row["fail_reason"], row


def test_a_refused_creation_is_red_and_no_transport_is_said(monkeypatch):
    out = _run(_Registry(create_code="422"), monkeypatch)
    assert not out[D.ONBOARD_NAMED]["healthy"]
    out = _run(None, monkeypatch)
    assert "in-target transport" in str(out[D.ONBOARD_NAMED].get("skip_reason"))


# ── V0650 (tester batch 2 item 5): the manual names the address the credential names ──────────────────────────────────
HOME = "https://nt261031x4a.theprotocol.cloud"


def test_the_manual_naming_the_credentials_address_passes(monkeypatch):
    out = _run(_Registry(home=HOME, manual_url=HOME), monkeypatch)
    row = out[D.ONBOARD_MANUAL]
    assert row["healthy"] and not row.get("fail_reason"), row
    assert row["result_excerpt"] == {"manual_registry_url": HOME, "credential_registry_url": HOME}
    assert D.ONBOARD_MANUAL.startswith(F._SYNTHETIC_ROW_PREFIXES)
    assert "never-in-a-row" not in repr(out)


def test_a_manual_naming_another_address_is_red(monkeypatch):
    # what the outside view read on EU before V0650: the credential https://theprotocol.cloud, the manual eu.
    out = _run(_Registry(home="https://theprotocol.cloud", manual_url="https://eu.theprotocol.cloud"), monkeypatch)
    row = out[D.ONBOARD_MANUAL]
    assert not row["healthy"] and "two addresses for one registry" in row["fail_reason"], row


@pytest.mark.parametrize("reg,said", [
    (dict(), "names no registry_url"),
    (dict(home=HOME, manual_url=None), "no REGISTRY_URL line"),
    (dict(create_code="422"), "names no registry_url"),
])
def test_what_cannot_be_compared_is_said(monkeypatch, reg, said):
    out = _run(_Registry(**reg), monkeypatch)
    assert said in str(out[D.ONBOARD_MANUAL].get("skip_reason")), out[D.ONBOARD_MANUAL]


def test_a_manual_that_does_not_answer_is_red(monkeypatch):
    out = _run(_Registry(home=HOME, manual_url=HOME, manual_code="503"), monkeypatch)
    assert not out[D.ONBOARD_MANUAL]["healthy"] and "HTTP 503" in out[D.ONBOARD_MANUAL]["fail_reason"]


def test_the_manual_line_is_read_both_ways():
    assert D.manual_registry_url(f"> | `REGISTRY_URL` | `{HOME}/` |") == HOME
    assert D.manual_registry_url(f"> `REGISTRY_URL` = `{HOME}`") == HOME
    assert D.manual_registry_url("Every `{REGISTRY_URL}` below has already been replaced") is None


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
