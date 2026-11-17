"""V0664 (order gwo_f56d1ec465259a4454ad20df, found by session-tester on v0664/cut d77905a7a, room seq 3945): a workflow made
from a template says which template.

POST /api/v1/workflow-templates/{tid}/instantiate (services/workflow_templates.Library over its DbStore) writes template_id,
template_version and template_content_hash onto agent_workflows (migration 0228); GET /api/v1/workflows/{wid} (services/
workflows.view, which the route returns as it is) and the list (workflows.list_for) now carry them as a "template" block,
{id, version, content_hash, title}, or null for a workflow made by hand. The workflow rail reads agent_workflows with plain SQL
(SELECT *) and has no ORM model, so the row it loads already holds the three columns.

Driven through the real instantiate on SQLite: the template's tables hold the columns DbStore reads.
Red on d77905a7a: the view and the list carry no template.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from decimal import Decimal

import pytest
import yaml
from sqlalchemy import text

from agentvault_registry import models
from agentvault_registry.services import workflow_templates as wt
from agentvault_registry.services import workflows as W
from tests._sqlite_db import sqlite_db
from tests.test_workflow_templates_kit_v0664 import MANIFEST, kit

sqlite3.register_adapter(Decimal, str)

OWNER = "did:theprotocol:eu.test:wf-owner"
AUTHOR = "did:theprotocol:eu.test:tpl-author"
TID, VID = "wtpl_" + "a" * 20, "wtpv_" + "a" * 20


def _env():
    db = sqlite_db(models.Developer, models.Agent)
    s = db.sync
    s.connection().connection.dbapi_connection.create_function(
        "now", 0, lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(" "))
    s.execute(text("""CREATE TABLE agent_workflows (id TEXT PRIMARY KEY, owner_did TEXT, title TEXT, ruleset TEXT, ruleset_hash TEXT,
        total_budget NUMERIC, currency TEXT, status TEXT DEFAULT 'draft', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP, template_id TEXT, template_version INTEGER, template_content_hash TEXT)"""))
    s.execute(text("""CREATE TABLE agent_workflow_steps (id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT, position INTEGER,
        step_key TEXT, role TEXT, spec TEXT, acceptance TEXT, budget NUMERIC, deadline_seconds INTEGER, ruleset TEXT, input_from TEXT,
        order_id TEXT, output_hash TEXT, receipt TEXT)"""))
    s.execute(text("""CREATE TABLE workflow_templates (id TEXT PRIMARY KEY, slug TEXT, title TEXT, summary TEXT, kind TEXT,
        from_kind TEXT, to_kind TEXT, owner_agent_did TEXT, source_org_id TEXT, visibility TEXT, pricing_model TEXT, price NUMERIC,
        price_currency TEXT, fork_share_bps INTEGER, forked_from_template_id TEXT, forked_from_version INTEGER,
        current_version_id TEXT, created_at TEXT, updated_at TEXT)"""))
    s.execute(text("""CREATE TABLE workflow_template_versions (id TEXT PRIMARY KEY, template_id TEXT, version INTEGER, manifest TEXT,
        files TEXT, content_hash TEXT, changelog TEXT, published_at TEXT, created_at TEXT)"""))
    s.execute(text("""CREATE TABLE workflow_template_uses (id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT, version INTEGER,
        agent_did TEXT, kind TEXT, reference TEXT, at TEXT)"""))
    files = kit()
    manifest = yaml.safe_load(MANIFEST)
    s.execute(text("""INSERT INTO workflow_templates (id, slug, title, kind, owner_agent_did, visibility, pricing_model,
        fork_share_bps, current_version_id) VALUES (:i, 'crm-to-pg', 'CRM to Postgres', 'migration', :o, 'public', 'free', 2000, :v)"""),
              {"i": TID, "o": AUTHOR, "v": VID})
    s.execute(text("""INSERT INTO workflow_template_versions (id, template_id, version, manifest, files, content_hash, published_at)
        VALUES (:v, :t, 1, :m, :f, :h, '2026-11-14T17:00:00+00:00')"""),
              {"v": VID, "t": TID, "m": json.dumps(manifest), "f": json.dumps(files), "h": wt.content_hash(manifest, files)})
    s.commit()
    return db, wt.content_hash(manifest, files)


def _by_hand():
    return {"title": "By hand", "total_budget": 30, "steps": [{"key": "build", "role": "builder", "budget": 10}]}


@pytest.mark.asyncio
async def test_a_workflow_made_from_a_template_reads_back_which_template():
    db, content = _env()
    actor = {"kind": "agent", "did": OWNER, "developer_id": None, "org": None}
    out = await wt.Library(wt.DbStore(db)).instantiate(actor, TID, {"total_budget": "100"})
    view = await W.view(db, out["workflow_id"])
    assert view["template"] == {"id": TID, "version": 1, "content_hash": content, "title": "CRM to Postgres"}
    listed = {w["id"]: w for w in await W.list_for(db, OWNER)}
    assert listed[out["workflow_id"]]["template"] == view["template"]


@pytest.mark.asyncio
async def test_a_workflow_made_by_hand_carries_no_template():
    db, _ = _env()
    made = await W.create(db, OWNER, _by_hand())
    assert made["template"] is None
    assert (await W.view(db, made["id"]))["template"] is None
    assert [w["template"] for w in await W.list_for(db, OWNER)] == [None]


@pytest.mark.asyncio
async def test_a_template_removed_since_keeps_the_provenance_without_its_title():
    db, content = _env()
    actor = {"kind": "agent", "did": OWNER, "developer_id": None, "org": None}
    out = await wt.Library(wt.DbStore(db)).instantiate(actor, TID, {"total_budget": "100"})
    db.sync.execute(text("DELETE FROM workflow_templates WHERE id = :i"), {"i": TID})
    db.sync.commit()
    assert (await W.view(db, out["workflow_id"]))["template"] == {"id": TID, "version": 1, "content_hash": content,
                                                                 "title": None}
