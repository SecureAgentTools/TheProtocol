"""§MCPTEST30 (V0548) — an MCP tool whose request fails says so; it never answers a failed read as a real one.

The census (tests/mcp_failure_census.py, a fresh process riding the request survey) answers every request a tool sends
to this registry with 503 and reads what the tool returns. On V0546 ten tools answered an empty list: three peer feeds
(fixed in V0547) and getMyAgentLogs, getMyDeveloperActivity, getProposalVotes, getPublicEventStoreRecent,
listDeveloperApikeysMe, listDeveloperWebhooks and listFederationRegistries, whose wrappers dropped the `error` key or
replaced the envelope with {"<list>": [], "total": 0}. A caller (and the tester's own contracts, which pinned the list
keys) read an outage as "nothing there". None may do it again.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def census():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "failures.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(HERE.parent / "src") + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run([sys.executable, str(HERE / "mcp_failure_census.py"), "--json", str(out)],
                           env=env, cwd=str(HERE), capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, f"the census did not run:\n{r.stderr[-3000:]}"
        return json.loads(out.read_text())


def test_the_census_reached_the_tools(census):
    assert census["tools"] >= 700 and census["said"] >= 650, {k: v for k, v in census.items() if k != "swallowed"}


def test_no_tool_answers_a_failed_request_as_a_real_answer(census):
    assert census["swallowed"] == {}, ("these tools answered a 503 without a trace of it (return the failure):\n"
                                       + json.dumps(census["swallowed"], indent=1, sort_keys=True))


def test_the_instrument_tells_a_stated_failure_from_a_swallowed_one():
    # the function alone: importing the census would patch httpx in this process, so its source is compiled instead
    src = (HERE / "mcp_failure_census.py").read_text()
    ns: dict = {}
    start = src.index("def says_failure(")
    exec(compile("from typing import Any\n" + src[start:src.index("\n\n\nasync def census()")], "says_failure", "exec"), ns)
    says = ns["says_failure"]
    assert says({"error": "HTTP 503: down"}) and says({"status_code": 503, "upstream_error": "x returned HTTP 503"})
    assert says({"_text": "Error: HTTP 503: down"}) and says({"success": False}) and says({"outer": {"error": "x"}})
    # the shapes the ten wrappers answered: what a caller cannot tell from "nothing there"
    assert not says({"logs": [], "total": 0}) and not says({"registries": [], "total": 0})
    assert not says({"agent_cards": [], "total": 0, "limit": 100})
