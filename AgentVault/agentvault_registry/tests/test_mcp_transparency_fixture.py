"""§SUITES1018 (2026-10-18): the MCP lifecycle keeps one organization opted into transparency, so the pair
listTransparentOrganizations -> getOrgPublicFeed has a row to ask.

Measured in the 2026-10-18 lifecycle run on sbx-alpha (58e748f7f76f419b): the pair read NOT MEASURED ("the list is empty
(0 rows), so no detail can be asked"), as it did every night: no organization on the frame had opted in. The run now
finds its fixture by name and opts it in, or makes it once; it never deletes it.

RED on 9ac0925c: there is no fixture step (mcp_lifecycles._ensure_transparent_org does not exist).
"""
from __future__ import annotations

import asyncio

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L


class _Bag:
    developer_jwt = "dev.jwt"


def _rpc(answers):
    calls = []

    async def rpc(tool, args, jwt="", timeout=30):
        calls.append((tool, dict(args), jwt))
        return True, answers.get(tool, {}), "200"
    return rpc, calls


def _parse(body):
    return body


def test_red_an_empty_frame_gets_its_fixture_made_once_opted_in():
    rpc, calls = _rpc({"theprotocol_listTransparentOrganizations": {"organizations": []},
                       "theprotocol_getMyOrganizations": {"organizations": [{"id": "o1", "name": "someone else's"}]}})
    asyncio.run(L._ensure_transparent_org(rpc, _parse, _Bag()))
    made = [c for c in calls if c[0] == "theprotocol_createOrganization"]
    assert len(made) == 1, calls
    assert made[0][1]["name"] == L._TRANSPARENCY_FIXTURE and made[0][1]["settings"] == {"public_transparency_opt_in": True}
    assert made[0][2] == "dev.jwt"


def test_red_an_existing_fixture_is_opted_in_not_made_again():
    rpc, calls = _rpc({"theprotocol_listTransparentOrganizations": {"organizations": []},
                       "theprotocol_getMyOrganizations": {"organizations": [{"id": "fx", "name": L._TRANSPARENCY_FIXTURE}]}})
    asyncio.run(L._ensure_transparent_org(rpc, _parse, _Bag()))
    assert [c[0] for c in calls][-1] == "theprotocol_updateOrganization", calls
    assert calls[-1][1] == {"org_id": "fx", "settings": {"public_transparency_opt_in": True}}
    assert not any(c[0] == "theprotocol_createOrganization" for c in calls)


def test_control_a_frame_that_already_lists_one_is_left_alone():
    rpc, calls = _rpc({"theprotocol_listTransparentOrganizations": {"organizations": [{"org_id": "x"}]}})
    asyncio.run(L._ensure_transparent_org(rpc, _parse, _Bag()))
    assert [c[0] for c in calls] == ["theprotocol_listTransparentOrganizations"], calls


def test_control_a_failing_transport_never_breaks_the_lifecycle():
    async def boom(*a, **k):
        raise RuntimeError("transport down")
    asyncio.run(L._ensure_transparent_org(boom, _parse, _Bag()))   # no exception
