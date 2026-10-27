"""D6-679 (2026-10-16): the evals.completed notification opens a page its recipients can open.

run_suite notified the owners of the agents a suite scored with click "/ui/#/evals", a route the console does not have
(it serves #/admin/evals, an administrator's page): the push, the in-app row and the mail button opened the not-found
page. The click now opens the public leaderboard on its Evals tab (#/leaderboard?mode=evals, which the leaderboard reads
on arrival and on a query change: Leaderboard.evalsMode.test.ts). The run is driven with a fake database and a fake
task runner; nothing is scored for real and nothing is sent.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentvault_registry.background_tasks import eval_runner, push_notify

ROUTER = (Path(eval_runner.__file__).resolve().parents[1] / "static" / "new_registry_frontend" / "src" / "router"
          / "index.ts")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self):
        self.added = []

    async def execute(self, *_a, **_k):
        return _Rows([SimpleNamespace(id=1, weight=1.0)])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def notify(type_key, dids, **kw):
        calls.append((type_key, list(dids), kw))

        async def nothing():
            return 0
        return nothing()
    monkeypatch.setattr(push_notify, "notify_agent_owners", notify)

    async def endpoint(self, db, did):
        return None

    async def run_one(self, suite, task, did, endpoint, db, pay_slot=None):
        return 1.0, True, 5, "ok", None
    monkeypatch.setattr(eval_runner.EvalRunner, "_agent_endpoint", endpoint)
    monkeypatch.setattr(eval_runner.EvalRunner, "_run_one", run_one)
    return calls


def _run_suite():
    suite = SimpleNamespace(id=3, key="code-v1", emit_reputation_signal=False, pay_per_task=0)
    db = _DB()

    async def go():
        return await eval_runner.EvalRunner().run_suite(db, suite, only_dids=["did:theprotocol:scored"])
    return asyncio.run(go()), db


def test_the_owners_are_sent_to_the_leaderboards_evals_tab(sent):
    run_id, db = _run_suite()
    assert run_id and len(db.added) == 1, "one task scored for one agent"
    assert [(t, d) for t, d, _ in sent] == [("evals.completed", ["did:theprotocol:scored"])]
    assert sent[0][2]["click"] == "/ui/#/leaderboard?mode=evals"


@pytest.mark.skipif(not ROUTER.is_file(), reason="the console source is not in this tree (a release image)")
def test_the_click_names_a_route_the_console_serves_without_an_admin_flag(sent):
    _run_suite()
    path = sent[0][2]["click"].split("#", 1)[1].split("?", 1)[0].lstrip("/")
    router = ROUTER.read_text()
    m = re.search(r"\{\s*path:\s*'" + re.escape(path) + r"',(.*?)\}\s*\n\s*\}", router, re.S)
    assert m, f"the console has no route '{path}'"
    assert "requiresRole: 'admin'" not in m.group(1) and "requiresAdmin" not in m.group(1)
