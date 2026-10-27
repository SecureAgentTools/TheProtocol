"""§MCPTEST30 (V0547) — the peers' feeds are read the way a peer reads them (federation_suite/peer_feed_probe.py).

federation_registry_cards_endpoint_reachable_per_frame and federation_agent_cards_endpoint_reachable called MCP
wrappers that turned the route's 401 into an empty list, and passed on any dict. Measured live 2026-10-02 from
sbx-beta-registry with its own SVID: sandbox-A's registry-card feed answered 200 with 4 cards, its agent-card feed 200
with 10, and both answered 400 to a caller with no client certificate.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agentvault_registry.api_tests.federation_suite import peer_feed_probe as P
from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet

SUITE = Path(P.__file__).resolve().parent / "tests"
MEASURED = '{"name": "peer", "status": 200, "items": 4, "detail": null}\n{"name": "stranger", "status": 400, "items": null, "detail": null}\n'


def test_the_measured_answers_pass_and_say_what_was_read():
    ok, sentence, ev = P.verdict(P.read_answers(MEASURED), "registry-card feed")
    assert ok is True and "with its own SVID (4 item(s))" in sentence and "no certificate was refused" in sentence
    assert ev["peer"]["status"] == 200 and ev["stranger"]["status"] == 400


def test_a_feed_that_serves_a_stranger_is_the_finding():
    rows = P.read_answers(MEASURED.replace('"stranger", "status": 400', '"stranger", "status": 200'))
    ok, sentence, _ = P.verdict(rows, "agent-card feed")
    assert ok is False and sentence.startswith("BUG-FIND: sandbox-A's agent-card feed answered 200 to a caller with no")


@pytest.mark.parametrize("peer", ['{"name": "peer", "status": 401, "items": null, "detail": "Federation authentication required"}',
                                  '{"name": "peer", "error": "SSLError", "msg": "certificate verify failed"}'])
def test_a_peer_that_cannot_read_the_feed_fails(peer):
    rows = P.read_answers(peer + "\n" + MEASURED.splitlines()[1])
    ok, sentence, _ = P.verdict(rows, "agent-card feed")
    assert ok is False and "the path the sync worker takes is closed" in sentence


def test_a_200_without_a_list_is_not_a_readable_feed():
    rows = P.read_answers(MEASURED.replace('"items": 4', '"items": null'))
    ok, sentence, _ = P.verdict(rows, "registry-card feed")
    assert ok is False and "without a list" in sentence


@pytest.mark.parametrize("rows", [
    '{"name": "peer", "status": 200, "items": 4}\n{"name": "stranger", "status": 500}',          # neither refused nor served
    '{"name": "peer", "error": "ValueError", "msg": "x"}\n{"name": "stranger", "status": 400}',  # the probe itself broke
])
def test_an_answer_the_probe_cannot_read_is_a_precondition_never_a_verdict(rows):
    with pytest.raises(PreconditionUnmet):
        P.verdict(P.read_answers(rows), "agent-card feed")


@pytest.mark.parametrize("file,fn", [("test_federation_discovery.py", "test_federation_registry_cards"),
                                     ("test_pull_sync.py", "test_federation_agent_cards_listed")])
def test_the_two_rows_read_the_feed_as_a_peer_and_no_longer_call_the_wrapper(file, fn):
    tree = ast.parse((SUITE / file).read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == fn)
    calls = {getattr(c.func, "id", getattr(c.func, "attr", "")) for c in ast.walk(node) if isinstance(c, ast.Call)}
    assert "peer_feed_row" in calls
    strings = {c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert not {"listFederationAgentCards", "listFederationRegistryCards"} & strings
