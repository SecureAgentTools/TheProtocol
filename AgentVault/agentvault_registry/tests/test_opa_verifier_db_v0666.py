"""V0666 layer C: the verifier's readers on a REAL Postgres (gwo_bec4b18190831482a6463d46). SQLite would not run the readers' SQL
(ANY(:ids), EXTRACT(EPOCH ...), JSONB, a read-only server setting).

The verifier's own readers (verifier/facts.py::NodeSources) read the registry's tables and an event store's `events`; this file builds
those tables from the registry's models (and a minimal `events` table), seeds rows a clean node and a broken node would hold, and asks:
  1. each reader returns the facts the rule needs, from the rows alone (nothing is told to it);
  2. the connection is read-only: a write through the verifier's own engine settings is refused by the server;
  3. end to end through the real Rego (when OPA_VERIFIER_BIN and OPA_VERIFIER_POLICY_DIR are set): the clean node raises nothing, and
     breaking ONE row (an overdue deletion, a merged change with no review) raises exactly that alert.
Skipped unless OPA_VERIFIER_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
RED on 7e05df63d: there are no readers.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import pathlib
import uuid

import pytest

DB = os.environ.get("OPA_VERIFIER_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set OPA_VERIFIER_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from agentvault_registry.verifier import evaluator, facts, runner  # noqa: E402

NOW = dt.datetime(2026, 11, 16, 0, 0, tzinfo=dt.timezone.utc)
OWN = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "verifier" / "policies"
BIN, POLICIES = os.environ.get("OPA_VERIFIER_BIN"), os.environ.get("OPA_VERIFIER_POLICY_DIR")
SHA = "a" * 40
ENV_JSON = '["AGENT_RBAC_MODE=enforce","AGENT_DELEGATION_MODE=enforce","GUILD_ENABLED=true","EXCHANGE_ENABLED=false","DATABASE_URL=postgresql://u:SECRET@h/d"]'


@pytest.fixture
async def maker():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_type varchar(100) NOT NULL, "
                                "aggregate_id varchar(255) NOT NULL, idempotency_key varchar(255))"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(maker, *, merged_review=True, overdue=False, issued=False, profile_denies=("exchange",)):
    from agentvault_registry import models as m
    async with maker() as s:
        devs = {}
        for key in ("proposer", "reviewer", "pending", "overdue"):
            d = m.Developer(name=f"{key}-{uuid.uuid4().hex[:6]}", email=f"{key}{uuid.uuid4().hex[:6]}@test.local", hashed_password="x",
                            is_verified=True)
            s.add(d)
            devs[key] = d
        await s.flush()
        devs["pending"].deletion_status = "pending_deletion"
        devs["pending"].deletion_requested_at = NOW - dt.timedelta(days=3)
        if overdue:
            devs["overdue"].deletion_status = "pending_deletion"
            devs["overdue"].deletion_requested_at = NOW - dt.timedelta(days=40)
        p = m.GovernanceProposal(proposer_did="did:test:p", title="t", description="d", status="PASSED", proposal_type="standard",
                                 quorum_percent=10.0, pass_percent=50.0, end_timestamp=NOW - dt.timedelta(days=3))
        s.add(p)
        await s.flush()
        s.add(m.CodeChange(
            id="cc-clean", repository="theprotocol/AgentVault", paths=["agentvault_registry/x.py"], title="t", problem="p", mode="branch",
            commit=SHA, proposer_did="did:test:a", proposer_developer_id=devs["proposer"].id, sensitive=False, state="merged",
            proposal_id=p.id, passed_at=NOW - dt.timedelta(days=3),
            acceptance={"ok": True, "record": {"commit": SHA, "read_from": "checker", "checker_kid": "k1",
                                                "touched": ["agentvault_registry/x.py"]}},
            merged={"commit": SHA, "into": "main", "at": (NOW - dt.timedelta(days=1)).isoformat()}))
        s.add(m.CodeChangeReview(code_change_id="cc-clean", reviewer_developer_id=devs["reviewer"].id, verdict="approve", commit=SHA, findings=""))
        if not merged_review:
            s.add(m.CodeChange(
                id="cc-bad", repository="theprotocol/AgentVault", paths=["agentvault_registry/y.py"], title="t", problem="p", mode="branch",
                commit=SHA, proposer_did="did:test:a", proposer_developer_id=devs["proposer"].id, sensitive=False, state="merged",
                proposal_id=p.id, passed_at=NOW - dt.timedelta(days=3),
                acceptance={"ok": True, "record": {"commit": SHA, "read_from": "checker", "checker_kid": "k1",
                                                    "touched": ["agentvault_registry/y.py"]}},
                merged={"commit": SHA, "into": "main", "at": (NOW - dt.timedelta(days=1)).isoformat()}))
        import json
        s.add(m.ExchangeFlag(key="jurisdiction_profile", value=json.dumps(
            {"name": "p", "version": 1, "features": {f: False for f in profile_denies}, "limits": {}})))
        s.add(m.FiatPurchase(id="fp-1", stripe_session_id="cs_1", amount_eur=10, amount_avt=20000, avt_per_eur_rate=2000,
                             tier_label="t", status="completed"))
        await s.commit()
        if issued:
            await s.execute(text("INSERT INTO events (event_type, aggregate_id, idempotency_key) VALUES ('TokensIssued', 'fp-1', NULL)"))
            await s.commit()


def _sources():
    return facts.NodeSources(
        [{"name": "n1", "container": "n1-registry", "db_env": "DB", "es_env": "DB", "base_url": "http://n1"}],
        environ={"DB": DB}, runner=lambda cmd: ENV_JSON,
        fetch=lambda url: {"paths": {"/api/v1/fiat/quote": {}, "/api/v1/fiat/tiers": {}}})


def run(coro):
    return asyncio.run(coro)


async def test_each_reader_returns_the_facts_from_the_rows_alone(maker):
    await _seed(maker, merged_review=False, overdue=True, issued=True)
    src = _sources()
    (_, f), = await src.subjects("iron_pairing", "n1")
    assert f["env"] == {"AGENT_RBAC_MODE": "enforce", "AGENT_DELEGATION_MODE": "enforce", "GUILD_ENABLED": "true",
                        "EXCHANGE_ENABLED": "false"}                      # the DSN never left the reader
    (_, f), = await src.subjects("jurisdiction_coherent", "n1")
    assert f["profile"]["features"] == {"exchange": False}
    (_, f), = await src.subjects("fiat_buy_only", "n1")
    assert f["purchases_not_in"] == 0 and f["purchases_issued"] == 1 and f["paths"] == ["/api/v1/fiat/quote", "/api/v1/fiat/tiers"]
    subs = dict(await src.subjects("merge_needs_the_record", "n1"))
    assert set(subs) == {"cc-clean", "cc-bad"}
    assert [r["verdict"] for r in subs["cc-clean"]["reviews"]] == ["approve"] and subs["cc-bad"]["reviews"] == []
    assert subs["cc-clean"]["change"]["proposal_status"] == "PASSED" and subs["cc-clean"]["change"]["passed_at"] is not None
    subs = dict(await src.subjects("deletion_on_schedule", "n1"))
    assert len(subs) == 2 and all(k.startswith("developer:") for k in subs)
    assert {v["account"]["deletion_status"] for v in subs.values()} == {"pending_deletion"}


async def test_a_node_with_nothing_to_judge_judges_nothing_and_says_so(maker):
    src = _sources()
    assert await src.subjects("merge_needs_the_record", "n1") == []
    assert await src.subjects("deletion_on_schedule", "n1") == []


async def test_the_verifiers_own_connection_is_read_only_the_server_refuses_a_write_through_it(maker):
    src = _sources()
    assert await src.rows("n1", "db", "SHOW default_transaction_read_only") == [{"default_transaction_read_only": "on"}]
    with pytest.raises(facts.Unmeasured) as e:                     # the reader's own engine, handed a write: the server refuses
        await src.rows("n1", "db", "INSERT INTO exchange_flags (key, value) VALUES ('x', 'y')")
    assert "could not be read" in str(e.value)
    async with maker() as s:
        assert (await s.execute(text("SELECT count(*) FROM exchange_flags WHERE key = 'x'"))).scalar_one() == 0
    assert facts.READ_ONLY["server_settings"]["default_transaction_read_only"] == "on"


async def test_a_database_that_does_not_answer_is_unmeasured_without_its_dsn_in_the_reason(maker):
    src = facts.NodeSources([{"name": "n1", "container": "c", "db_env": "DB", "es_env": "DB", "base_url": "http://n1"}],
                            environ={"DB": "postgresql+asyncpg://u:SECRETPW@127.0.0.1:1/none"}, runner=lambda cmd: ENV_JSON)
    with pytest.raises(facts.Unmeasured) as e:
        await src.subjects("deletion_on_schedule", "n1")
    assert "SECRETPW" not in str(e.value) and "database could not be read" in str(e.value)
    src = facts.NodeSources([{"name": "n1", "container": "c", "base_url": "http://n1"}], environ={}, runner=lambda cmd: ENV_JSON)
    with pytest.raises(facts.Unmeasured) as e:
        await src.subjects("merge_needs_the_record", "n1")
    assert "no db database is configured" in str(e.value)


@pytest.mark.skipif(not (BIN and POLICIES), reason="needs OPA_VERIFIER_BIN and OPA_VERIFIER_POLICY_DIR. Skipped, never silently passed.")
async def test_end_to_end_the_clean_node_raises_nothing_and_each_broken_row_raises_its_alert(maker, tmp_path):
    opa = evaluator.OpaEvaluator(BIN, [POLICIES, str(OWN)])
    src = _sources()
    src.now = lambda: NOW
    await _seed(maker)
    clean = await runner.run_once(src, opa)
    assert sum(clean.violations.values()) == 0 and sum(clean.errors.values()) == 0 and sum(clean.unmeasured.values()) == 0, clean.metrics_text()
    assert clean.subjects == {"iron_pairing": 1, "jurisdiction_coherent": 1, "fiat_buy_only": 1, "merge_needs_the_record": 1,
                              "deletion_on_schedule": 1}
    # break ONE row each: an overdue deletion, a merged change with no review, a denied feature that is live
    await _seed_more(maker)
    rec = runner.Recorder(tmp_path / "f.jsonl")
    broken = await runner.run_once(src, opa, recorder=rec)
    assert broken.violations == {"iron_pairing": 0, "jurisdiction_coherent": 1, "fiat_buy_only": 0, "merge_needs_the_record": 1,
                                 "deletion_on_schedule": 1}
    assert 'opa_verifier_violations{rule="deletion_on_schedule"} 1' in broken.metrics_text()
    subjects = sorted((f["rule"], f["subject"]) for f in broken.findings)
    assert ("merge_needs_the_record", "cc-bad") in subjects and any(r == "deletion_on_schedule" for r, _ in subjects)
    assert len((tmp_path / "f.jsonl").read_text().splitlines()) == 3


async def _seed_more(maker):
    from agentvault_registry import models as m
    async with maker() as s:
        proposer = (await s.execute(text("SELECT id FROM developers ORDER BY id LIMIT 1"))).scalar_one()
        pid = (await s.execute(text("SELECT id FROM governance_proposals LIMIT 1"))).scalar_one()
        d = m.Developer(name=f"late-{uuid.uuid4().hex[:6]}", email=f"late{uuid.uuid4().hex[:6]}@test.local", hashed_password="x",
                        is_verified=True, deletion_status="pending_deletion", deletion_requested_at=NOW - dt.timedelta(days=60))
        s.add(d)
        s.add(m.CodeChange(
            id="cc-bad", repository="theprotocol/AgentVault", paths=["agentvault_registry/y.py"], title="t", problem="p", mode="branch",
            commit=SHA, proposer_did="did:test:a", proposer_developer_id=proposer, sensitive=False, state="merged", proposal_id=pid,
            passed_at=NOW - dt.timedelta(days=3),
            acceptance={"ok": True, "record": {"commit": SHA, "read_from": "checker", "checker_kid": "k1", "touched": ["agentvault_registry/y.py"]}},
            merged={"commit": SHA, "into": "main", "at": (NOW - dt.timedelta(days=1)).isoformat()}))
        await s.execute(text("UPDATE exchange_flags SET value = :v WHERE key = 'jurisdiction_profile'"),
                        {"v": '{"name": "p", "version": 1, "features": {"exchange": false, "guild": false}, "limits": {}}'})
        await s.commit()
