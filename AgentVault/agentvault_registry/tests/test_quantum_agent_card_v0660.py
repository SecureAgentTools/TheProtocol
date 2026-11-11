"""V0660 (a) (session-code, 2026-11-08): the quantum workload agent card extension, our proposed standard.

The extension is one entry of a card's top-level extensions[] (URI https://theprotocol.cloud/extensions/v1/quantum/workload,
version 1.0; spec PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md in the stack). Under the frame switch
QUANTUM_WORKLOADS_MODE (core/quantum_mode.py):

- off (the source default) is byte-inert: a card write reads nothing of the extension and stores what it stored before,
  discovery runs the statement it ran before and adds no key to its answer (a quantum parameter, even a malformed one,
  is not read), the validate route answers what it answered, the two read routes refuse with the switch's sentence and
  are left out of the OpenAPI schema, and the three MCP reads are not listed;
- shadow checks every write, logs and counts what on would refuse, and writes the card; discovery filters and states
  the facets; the reads answer;
- on refuses a card write whose extension fails the schema or the spec's semantic rules (422 with the sentences), on
  create, on update and on a pulled card; the validate route says invalid.

RED on origin/v0658/cut (4b79322d7): services/quantum_agent_card.py, core/quantum_mode.py, the routes and the tools do not
exist (the module import fails).
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import json
import logging
import os
import subprocess
import sys
import textwrap
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from agentvault_registry import schemas  # noqa: E402
from agentvault_registry.core import quantum_mode  # noqa: E402
from agentvault_registry.services import quantum_agent_card as Q  # noqa: E402

URI = "https://theprotocol.cloud/extensions/v1/quantum/workload"
PAY = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"
# the bytes the spec publishes (the stack's PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0_schema.json) and the
# SDK carries (theprotocol/quantum/quantum_workload_v1.0.schema.json): the SDK's own test pins the same digest
SCHEMA_SHA256 = "99af03a3ac40a0977c85a7c4aebdd94c9e06020b55e63a95f31184b2732abfab"


def _ext():
    return copy.deepcopy(Q.schema()["examples"][0])


def _card(ext=None, pay=True, **over):
    exts = [ext if ext is not None else _ext()]
    if pay:
        exts.append({"uri": PAY, "params": {"base_rate": "1.5", "currency": "SBXA"}})
    card = {
        "protocolVersion": "1.0", "humanReadableId": "lab/qsim", "agentVersion": "1.0.0", "name": "Quantum Sim",
        "description": "A statevector simulator and a noisy emulator.", "url": "https://lab.example.org/a2a",
        "provider": {"name": "Example Lab"}, "capabilities": {"streaming": False},
        "authSchemes": [{"scheme": "bearer"}], "extensions": exts,
    }
    card.update(over)
    return card


@pytest.fixture
def mode(monkeypatch):
    def set_(m):
        if m is None:
            monkeypatch.delenv("QUANTUM_WORKLOADS_MODE", raising=False)
        else:
            monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", m)
    set_(None)
    return set_


# ── the switch and the schema ────────────────────────────────────────────────

def test_the_switch_is_off_by_default_and_reads_an_unknown_value_as_off(mode):
    assert quantum_mode.quantum_workloads_mode() == "off"
    for raw, want in (("shadow", "shadow"), (" ON ", "on"), ("enforce", "off"), ("", "off"), ("true", "off")):
        mode(raw)
        assert quantum_mode.quantum_workloads_mode() == want, raw


def test_the_registry_carries_the_published_schema_bytes_and_its_example_passes():
    raw = Q.schema_path().read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256 == Q.SCHEMA_SHA256
    s = json.loads(raw)
    assert s["properties"]["uri"]["const"] == URI == Q.EXTENSION_URI
    assert s["$defs"]["pricing"]["properties"]["payment_extension"]["const"] == PAY
    assert Q.check(_card()) == [], "the schema's own example, on a card that carries the payment extension"
    assert Q.check({"name": "plain"}) == [] and Q.check(None) == [], "no extension: nothing to say"


# ── the check ────────────────────────────────────────────────────────────────

def _problems(mutate, *, pay=True):
    ext = _ext()
    mutate(ext["params"])
    return Q.check(_card(ext, pay=pay))


def test_the_schema_half_names_the_path_and_the_rule():
    def sim_superconducting(p):
        p["backends"][0]["modality"] = "superconducting"
    assert any(x.startswith("params.backends.0.modality") for x in _problems(sim_superconducting))

    def ledger_circuits(p):
        p["data"]["ledger_keeps"] = ["hashes", "circuits"]
    assert any("ledger_keeps" in x and "circuits" in x for x in _problems(ledger_circuits)), "never circuits"

    def amount_in_pricing(p):
        p["pricing"]["base_rate"] = "5"
    assert any("base_rate" in x for x in _problems(amount_in_pricing)), "the amount lives in the payment extension"

    def rung3_unbased(p):
        p["evidence"].pop("rung_3_basis")
    assert any("rung_3_basis" in x for x in _problems(rung3_unbased))

    def qpu_without_calibration(p):
        b = p["backends"][1]
        b["kind"] = "qpu"
        b.pop("calibration")
    assert any("calibration" in x for x in _problems(qpu_without_calibration)), "a QPU states its calibration"

    def network_decoder(p):
        p["backends"][1]["qubits"]["logical"] = {"count": 1, "code": "surface-d3",
                                                  "decoder": {"name": "d", "version": "1", "placement": "network"}}
    assert any("placement" in x for x in _problems(network_decoder)), "a real-time decoder is never a network service"


def test_the_semantic_rules_the_schema_cannot_state():
    assert any(x.startswith("params.pricing") for x in _problems(lambda p: None, pay=False))

    def future(p):
        p["backends"][0]["queue"]["as_of"] = "2099-01-01T00:00:00Z"
    assert any("params.backends.0.queue.as_of" in x and "later than" in x for x in _problems(future))

    def logical_over(p):
        p["backends"][1]["qubits"]["logical"] = {"count": 40, "code": "surface-d3"}
    assert any("logical.count" in x for x in _problems(logical_over))

    def wide(p):
        p["backends"][1]["limits"]["max_width"] = 99
    assert any("max_width" in x for x in _problems(wide))

    def dup_ids(p):
        p["backends"][1]["id"] = p["backends"][0]["id"]
    assert any("more than once" in x for x in _problems(dup_ids))

    def unlisted_rung(p):
        p["evidence"]["verification_rungs"] = [1, 3]
    assert any("acceptance_tests.1" in x and "rung 2" in x for x in _problems(unlisted_rung))

    def rung_without_test(p):
        p["evidence"]["acceptance_tests"] = p["evidence"]["acceptance_tests"][:1]
    assert any("lists rung 2 and no acceptance test" in x for x in _problems(rung_without_test))

    def meter_without_circuit(p):
        p["evidence"].pop("metering_circuit")
    assert any("metering_circuit" in x for x in _problems(meter_without_circuit))

    def verifier_without_tests(p):
        p["roles"] = ["verifier"]
        p["evidence"]["acceptance_tests"] = []
        p["evidence"]["verification_rungs"] = [3]
    assert any("a verifier names the acceptance tests" in x for x in _problems(verifier_without_tests))


def test_the_item_facets_are_the_directorys_derivation():
    """Spec section 8.1: discovery and the Directory derive the same facets (directory/quantum_reader.py in the stack):
    a bool is not a count, and a format or jurisdiction name longer than 64 characters is left out."""
    p = _ext()["params"]
    p["backends"][1]["qubits"]["logical"] = {"count": True, "code": "surface-d3"}
    p["backends"][0]["formats"] = ["openqasm3", "x-" + "a" * 63]
    p["backends"][0]["location"]["jurisdiction"] = "X" * 65
    got = Q.facets(p)
    assert got["max_logical_qubits"] is None, "True is not a count of logical qubits"
    assert got["formats"] == ["openqasm3", "qir"] and got["jurisdictions"] == ["DE"]
    p["backends"][1]["qubits"]["logical"] = {"count": 2, "code": "surface-d3"}
    p["backends"][0]["formats"] = ["openqasm3", "x-" + "a" * 62]
    got = Q.facets(p)
    assert got["max_logical_qubits"] == 2 and "x-" + "a" * 62 in got["formats"], "64 characters are kept"


def test_placement_one_entry_at_the_top_level():
    misplaced = _card()
    misplaced["capabilities"]["extensions"] = [misplaced["extensions"].pop(0)]
    assert any(x.startswith("capabilities.extensions") for x in Q.check(misplaced))
    doubled = _card()
    doubled["extensions"].insert(0, _ext())
    assert any("carries 2" in x for x in Q.check(doubled))


# ── the gate on a card write ─────────────────────────────────────────────────

def _bad_card():
    ext = _ext()
    ext["params"]["data"]["ledger_keeps"] = ["circuits"]
    return _card(ext)


def test_off_reads_nothing(mode, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("off must not run the check")
    monkeypatch.setattr(Q, "check", boom)
    assert Q.gate(_bad_card(), where="create") is None


def test_shadow_reports_and_writes(mode, caplog):
    mode("shadow")
    with caplog.at_level(logging.WARNING, logger=Q.__name__):
        said = Q.gate(_bad_card(), where="create")
    assert said and "ledger_keeps" in said
    assert any("QUANTUM-SHADOW" in r.getMessage() and "would be refused" in r.getMessage() for r in caplog.records)
    assert Q.gate(_card(), where="create") is None, "a valid extension: nothing to report"


def test_on_refuses_with_the_sentences(mode):
    mode("on")
    with pytest.raises(ValueError) as e:
        Q.gate(_bad_card(), where="create")
    assert str(e.value).startswith("Invalid quantum workload extension") and "ledger_keeps" in str(e.value)
    assert Q.gate(_card(), where="create") is None and Q.gate({"name": "plain"}, where="update") is None


class _Db:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj, *a, **k):
        return None

    async def rollback(self):
        return None

    async def get(self, *a, **k):
        return None

    async def execute(self, *a, **k):
        raise RuntimeError("no database here")


def _create(card):
    from agentvault_registry.crud import agent_card as crud
    db = _Db()
    out = asyncio.run(crud.create_agent_card(db=db, developer_id=7, card_create=schemas.AgentCardCreate(card_data=card)))
    return db, out


def test_create_under_off_stores_the_extension_as_given(mode):
    db, out = _create(_bad_card())
    stored = [e for e in out.card_data["extensions"] if e.get("uri") == URI]
    assert json.dumps(stored[0], sort_keys=True) == json.dumps(_bad_card()["extensions"][0], sort_keys=True)
    assert db.added == [out]


def test_create_under_on_refuses_before_anything_is_added(mode):
    mode("on")
    with pytest.raises(ValueError) as e:
        _create(_bad_card())
    assert "Invalid quantum workload extension" in str(e.value)
    mode("shadow")
    db, out = _create(_bad_card())
    assert db.added == [out], "shadow writes the card"


def test_update_under_on_leaves_the_stored_card_untouched(mode):
    from agentvault_registry.crud import agent_card as crud
    mode("on")
    before = _card()
    row = SimpleNamespace(id=uuid.uuid4(), card_data=copy.deepcopy(before), name=before["name"],
                          description=before["description"], is_active=True)
    with pytest.raises(ValueError):
        asyncio.run(crud.update_agent_card(db=_Db(), db_card=row,
                                           card_update=schemas.AgentCardUpdate(card_data={"extensions": _bad_card()["extensions"]})))
    assert row.card_data == before


def test_the_validate_route_says_what_a_write_would_meet(mode):
    from agentvault_registry.routers import utils as U

    def validate(card):
        return asyncio.run(U.validate_agent_card(schemas.AgentCardValidationRequest(card_data=card)))
    off = validate(_bad_card())
    assert off.is_valid is True and off.detail is None, "off: the answer it gave before V0660"
    mode("shadow")
    sh = validate(_bad_card())
    assert sh.is_valid is True and "ledger_keeps" in (sh.detail or "") and "shadow" in sh.detail
    mode("on")
    on = validate(_bad_card())
    assert on.is_valid is False and "ledger_keeps" in (on.detail or "")
    legacy = _card(pay=False, pricing={"payment_required": True, "base_rate": "2"})
    assert validate(legacy).is_valid is True, "a legacy pricing block derives the payment extension, as a write does"


# ── a pulled card ────────────────────────────────────────────────────────────

def _pull(card_served, row_card):
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    row = SimpleNamespace(agent_did="did:theprotocol:q-1", card_data=row_card, last_pulled_at=None, last_pulled_etag=None,
                          last_pull_attempt_at=None, last_pull_status=None, pull_failures=0, name="Quantum Sim",
                          listed_name=None, listed_description=None, developer_id=None)
    stats = {"candidates": 0, "fetched_200": 0, "fetched_304": 0, "fetched_4xx": 0, "fetched_5xx": 0, "fetched_timeout": 0,
             "skipped_internal": 0, "drift_agents": 0, "drift_field_counts": {}, "errors": 0, "last_pull_per_agent": {}}

    async def go():
        async def no_emit(*a, **k):
            return None
        orig = ps._emit_drift_event
        ps._emit_drift_event = no_emit
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, json=card_served))) as client:
                await ps.AgentCardPullSync()._pull_one(None, client, row, stats)
        finally:
            ps._emit_drift_event = orig
    asyncio.run(go())
    return row, stats


def test_a_pulled_card_is_not_taken_under_on_and_is_under_off(mode):
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    url = "https://agent.probe-fixture.net/api/a2a"   # the pull-sync suite's own fixture host
    stored = ps.canonicalize_card_data(_card(url=url, supportedInterfaces=[{"url": url, "protocolBinding": "JSONRPC",
                                                                             "protocolVersion": "1.0"}]))
    served = copy.deepcopy(stored)
    served["extensions"][0]["params"]["data"]["ledger_keeps"] = ["circuits"]
    mode("on")
    row, stats = _pull(served, copy.deepcopy(stored))
    # the card was read: the attempt is stamped and no backoff builds, so a provider that fixes its card is read again
    # at the next cycle (a refusal counted as a failure waited out the doubling backoff, up to a week)
    assert row.last_pull_status == "quantum_refused" and row.pull_failures == 0 and stats.get("refused") == 1
    assert row.last_pull_attempt_at is not None and row.last_pulled_at is None
    assert row.card_data == stored, "the stored card stays"
    mode(None)
    row, _ = _pull(served, copy.deepcopy(stored))
    assert row.last_pull_status == "200" and row.card_data["extensions"][0]["params"]["data"]["ledger_keeps"] == ["circuits"]


# ── discovery ────────────────────────────────────────────────────────────────

KW = dict(q=None, origins=None, pricing=None, tag=None, verified_only=False, active_24h=False, encircled_only=False,
          foreign_only=False, answerable_only=False, bonded_only=False, include_unbonded=None, sort="newest",
          limit=30, offset=0, viewer=None)


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _DiscoverDb:
    def __init__(self, rows):
        self.rows = rows
        self.pages = []

    async def execute(self, stmt, params=None, *a, **k):
        sql = str(stmt)
        if "peer_registries" in sql:
            return _Res([])
        if "full_total" in sql:
            self.pages.append((sql, dict(params or {})))
            return _Res(self.rows)
        return _Res([])


def _row(**over):
    now = dt.datetime(2026, 11, 8, 3, 0, tzinfo=dt.timezone.utc)
    r = {"id": 1, "agent_did": "did:theprotocol:q-1", "name": "Quantum Sim", "description": "d", "created_at": now,
         "updated_at": now, "developer_id": 7, "is_local": True, "origin": "Local", "reputation_score": None,
         "last_active_at": None, "developer_verified": False, "is_paid": True, "is_live": False, "unlisted": False,
         "last_health": None, "last_health_at": None, "is_bonded": False, "reputation_bond_status": None,
         "staked_balance": None, "card_data": _card(), "is_enforced": False, "human_readable_id": "lab/qsim",
         "card_did": None, "tags": [], "pricing": None, "icon_url": None, "flare": {"tier": "x"}, "fee_ccy": None,
         "pricing_ccy": None, "source_registry": None, "full_total": 1,
         "facets_json": [{"origin": None, "count": 1, "live_24h": 0, "paid": 1}],
         "tags_json": []}
    r.update(over)
    return r


def _discover(db, **over):
    from agentvault_registry.routers import agent_cards as mod
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(mod.discover_agent_cards(db=db, **{**KW, **over}))
    finally:
        loop.close()


def test_the_quantum_statement_is_the_one_before_v0660_plus_two_edits():
    from agentvault_registry.routers import agent_cards as mod
    q = mod._DISCOVER_SLIM_CTE_QUANTUM
    assert ":quantum_rung" in q and "quantum_ext" in q and "quantum" not in mod._DISCOVER_SLIM_CTE
    restored = q.replace(",\n        " + Q.sql_extension("c") + " AS quantum_ext", "", 1).replace(Q.SQL_FILTERS, "", 1)
    assert restored == mod._DISCOVER_SLIM_CTE


def test_off_discovery_is_byte_inert_even_with_quantum_parameters(mode):
    plain = _DiscoverDb([_row()])
    before = _discover(plain)
    asked = _DiscoverDb([_row()])
    after = _discover(asked, quantum_only="true", quantum_min_qubits="not-a-number", quantum_modality="nonsense")
    assert asked.pages[0] == plain.pages[0], "the same statement with the same binds"
    assert "quantum" not in asked.pages[0][0]
    for out in (before, after):
        assert not any(k.startswith("quantum") for k in out["applied_filters"])
        assert "quantum" not in out["facets"] and all("quantum" not in it for it in out["items"])
    before.pop("generated_in_ms"); after.pop("generated_in_ms")
    assert json.dumps(before, sort_keys=True, default=str) == json.dumps(after, sort_keys=True, default=str)


def test_served_discovery_filters_echoes_and_states_the_facets(mode):
    mode("shadow")
    facets = {"total": 1, "max_qubits": 32, "roles": [{"name": "provider", "count": 1}],
              "kinds": [{"name": "simulator", "count": 1}], "modalities": [{"name": "simulator", "count": 1}],
              "formats": [{"name": "openqasm3", "count": 1}], "jurisdictions": [{"name": "DE", "count": 1}],
              "rungs": [{"name": "2", "count": 1}]}
    db = _DiscoverDb([_row(quantum_ext=_ext(), quantum_facets_json=json.dumps(facets))])
    out = _discover(db, quantum_only="true", quantum_modality="superconducting", quantum_min_qubits="20",
                    quantum_rung="2", quantum_jurisdiction="de")
    sql, binds = db.pages[0]
    assert "quantum_ext" in sql and "qfacet AS (" in sql and "AS quantum_facets_json" in sql
    assert binds["quantum_only"] is True and binds["quantum_modality"] == "superconducting"
    assert binds["quantum_min_qubits"] == 20 and binds["quantum_rung"] == 2 and binds["quantum_jurisdiction"] == "DE"
    assert binds["quantum_role"] is None and binds["quantum_format"] is None
    af = out["applied_filters"]
    assert af["quantum_only"] is True and af["quantum_min_qubits"] == 20 and af["quantum_role"] is None
    assert out["facets"]["quantum"]["max_qubits"] == 32 and out["facets"]["quantum"]["rungs"] == [{"name": 2, "count": 1}]
    item = out["items"][0]["quantum"]
    assert item["modalities"] == ["simulator", "superconducting"] and item["max_qubits"] == 32 and item["rungs"] == [1, 2, 3]
    plain = _DiscoverDb([_row(quantum_ext=None, quantum_facets_json=None)])
    assert _discover(plain)["items"][0]["quantum"] is None, "a card without the extension says so"


def test_served_discovery_refuses_a_malformed_filter(mode):
    mode("on")
    for bad in ({"quantum_min_qubits": "many"}, {"quantum_rung": "4"}, {"quantum_modality": "magic"},
                {"quantum_jurisdiction": "Europe"}, {"quantum_only": "perhaps"}):
        with pytest.raises(HTTPException) as e:
            _discover(_DiscoverDb([]), **bad)
        assert e.value.status_code == 422, bad


# ── the read routes ──────────────────────────────────────────────────────────

class _CardDb:
    def __init__(self, cards):
        self.cards = cards

    async def execute(self, *a, **k):
        return _Res(self.cards)


def test_the_routes_refuse_under_off_and_answer_when_served(mode):
    from agentvault_registry.routers import quantum_agent_cards as R
    with pytest.raises(HTTPException) as e:
        R.require_quantum_workloads_served()
    assert e.value.status_code == 403 and e.value.detail.startswith("quantum_workloads_off")
    mode("on")
    R.require_quantum_workloads_served()
    got = asyncio.run(R.get_quantum_workload_extension())
    assert got["uri"] == URI and got["mode"] == "on" and got["schema_sha256"] == SCHEMA_SHA256
    assert got["schema"]["properties"]["uri"]["const"] == URI
    mirror = SimpleNamespace(id=uuid.uuid4(), name="Mirror", card_data={**_card(), "federation_metadata": {
        "source_registry": "spiffe://peer", "origin_registry_name": "peer"}})
    native = SimpleNamespace(id=uuid.uuid4(), name="Quantum Sim", card_data=_card())
    out = asyncio.run(R.get_agent_quantum_workload(agent_did="did:theprotocol:q-1", db=_CardDb([mirror, native])))
    assert out["is_local"] is True and out["name"] == "Quantum Sim", "this registry's own card first"
    assert out["check"] == {"valid": True, "problems": [], "mode": "on"}
    assert out["index"]["roles"] == ["meter", "provider"] and len(out["freshness"]["backends"]) == 2
    assert out["freshness"]["backends"][1]["age_seconds"]["calibration"] > 0
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.get_agent_quantum_workload(agent_did="did:theprotocol:q-2",
                                                 db=_CardDb([SimpleNamespace(id=1, name="p", card_data={"name": "p"})])))
    assert e.value.status_code == 404 and e.value.detail.startswith("no_quantum_workload")


def test_off_leaves_the_routes_and_the_parameters_out_of_the_schema(mode):
    from agentvault_registry.main import app
    app.openapi_schema = None
    try:
        spec = app.openapi()
    finally:
        app.openapi_schema = None
    assert not [p for p in spec["paths"] if p.startswith("/api/v1/quantum/")]
    params = spec["paths"]["/api/v1/agent-cards/discover"]["get"]["parameters"]
    assert not [p["name"] for p in params if p["name"].startswith("quantum")]


def test_served_documents_the_routes_and_the_parameters():
    """A fresh process under QUANTUM_WORKLOADS_MODE=on (the schema follows the switch the process was started with)."""
    code = textwrap.dedent("""
        import json, os
        os.makedirs("/tmp/prom_multiproc_reg", exist_ok=True)
        from agentvault_registry.main import app
        from agentvault_registry.mcp import server as S
        spec = app.openapi()
        params = spec["paths"]["/api/v1/agent-cards/discover"]["get"]["parameters"]
        print("RESULT " + json.dumps({
            "paths": sorted(p for p in spec["paths"] if p.startswith("/api/v1/quantum/")),
            "params": sorted(p["name"] for p in params if p["name"].startswith("quantum")),
            "listed": sorted(t["name"] for t in S.filter_listed(S.ALL_TOOL_SCHEMAS) if "Quantum" in t["name"])}))
    """)
    env = dict(os.environ, QUANTUM_WORKLOADS_MODE="on")
    run = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300)
    line = next((x for x in run.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line, run.stderr[-2000:]
    got = json.loads(line[len("RESULT "):])
    # V0660 (b) adds the acceptance tests' three routes under the same switch (routers/quantum_acceptance.py)
    assert got["paths"] == ["/api/v1/quantum/acceptance", "/api/v1/quantum/acceptance/{rail}/{ref}",
                            "/api/v1/quantum/agents/{agent_did}", "/api/v1/quantum/verdicts",
                            "/api/v1/quantum/workload-extension"]
    assert got["params"] == sorted(Q.DISCOVER_PARAMS)
    assert got["listed"] == ["theprotocol_discoverQuantumAgents", "theprotocol_getQuantumWorkload",
                             "theprotocol_getQuantumWorkloadSchema"]


# ── the MCP reads ────────────────────────────────────────────────────────────

TOOLS = {"theprotocol_discoverQuantumAgents", "theprotocol_getQuantumWorkload", "theprotocol_getQuantumWorkloadSchema"}


def _listed():
    from agentvault_registry.mcp import server
    return {t["name"] for t in asyncio.new_event_loop().run_until_complete(server._handle_tools_list())["tools"]}


def test_the_reads_are_wired_tier_one_and_listed_only_where_served(mode):
    from agentvault_registry.mcp import audit, server, tool_categories as tc, tool_switches
    assert TOOLS <= set(server.TOOL_DISPATCH) and not (TOOLS & (server.TIER2_TOOLS | server.TIER3_TOOLS))
    assert TOOLS <= audit._TIER_1_TOOLS and tool_switches.NEEDS_QUANTUM_WORKLOADS == TOOLS
    assert {tc.get_category(n) for n in TOOLS} == {"discovery"}
    assert not (_listed() & TOOLS), "off: the listing is the one before V0660"
    for m in ("shadow", "on"):
        mode(m)
        assert TOOLS <= _listed(), m


class _FakeClient:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return self.answer


def test_the_search_tool_says_the_switch_when_the_filters_did_not_run(monkeypatch):
    from agentvault_registry.mcp import tools_quantum as TQ
    off = _FakeClient(httpx.Response(200, json={"items": [{"agent_did": "did:x", "name": "plain"}], "total": 1,
                                                "applied_filters": {"q": None, "limit": 10}}))
    monkeypatch.setattr(TQ, "mcp_http_client", lambda timeout=None: off)
    got = asyncio.run(TQ.discover_quantum_agents(modality="superconducting", min_qubits=20, rung=2))
    assert got == {"error": Q.OFF_SENTENCE}, "an unfiltered page is not the answer"
    url, params = off.calls[0]
    assert url.endswith("/api/v1/agent-cards/discover")
    assert params["quantum_only"] == "true" and params["quantum_min_qubits"] == "20" and params["quantum_rung"] == "2"
    on = _FakeClient(httpx.Response(200, json={
        "items": [{"agent_did": "did:q", "name": "Quantum Sim", "quantum": {"max_qubits": 32}, "is_local": True}],
        "total": 1, "has_more": False, "facets": {"quantum": {"total": 1}},
        "applied_filters": {"quantum_only": True, "quantum_modality": "superconducting", "quantum_role": None}}))
    monkeypatch.setattr(TQ, "mcp_http_client", lambda timeout=None: on)
    got = asyncio.run(TQ.discover_quantum_agents(modality="superconducting"))
    assert got["agents"][0]["did"] == "did:q" and got["agents"][0]["quantum"] == {"max_qubits": 32}
    assert got["facets"] == {"total": 1} and got["filters"] == {"quantum_only": True, "quantum_modality": "superconducting"}
    assert asyncio.run(TQ.discover_quantum_agents(min_qubits=0))["error"].startswith("min_qubits")
    assert asyncio.run(TQ.get_quantum_workload(did=" "))["error"].startswith("did is required")


def test_the_read_tools_carry_the_route_refusal(monkeypatch):
    from agentvault_registry.mcp import tools_quantum as TQ
    refused = _FakeClient(httpx.Response(403, json={"detail": Q.OFF_SENTENCE}))
    monkeypatch.setattr(TQ, "mcp_http_client", lambda timeout=None: refused)
    got = asyncio.run(TQ.get_quantum_workload(did="did:theprotocol:q-1"))
    assert got["error"].startswith("HTTP 403") and "quantum_workloads_off" in got["error"]
    assert refused.calls[0][0].endswith("/api/v1/quantum/agents/did:theprotocol:q-1"), "one segment (seg keeps a DID's colons)"
    assert "quantum_workloads_off" in asyncio.run(TQ.get_quantum_workload_schema())["error"]


def test_the_descriptions_keep_the_value_word_rule():
    import re
    from agentvault_registry.mcp import tools_quantum as TQ
    word = re.compile(r"\b(staking|staked|stakes?|rewards?|yields?|APY|APR|dividends?|stocks?|invest\w*|profits?|revenue|"
                      r"earn(?:s|ed|ing|ings)?|tokenomics|tokens?|insurance|premiums?|advantage|supremacy)\b", re.I)
    for t in TQ.QUANTUM_TOOL_SCHEMAS:
        texts = [t["description"]] + [v.get("description") or "" for v in t["inputSchema"]["properties"].values()]
        for text in texts:
            assert not word.search(text), (t["name"], text)
    assert "—" not in json.dumps(TQ.QUANTUM_TOOL_SCHEMAS, ensure_ascii=False) + Q.OFF_SENTENCE


def test_the_tester_holds_the_three_reads_to_contracts():
    """The MCP tester walks the listed catalog, so it meets the three reads only where they are listed (shadow and on);
    each is held to a contract there: the schema read and the search to their shape, the one-card read to the route's
    own refusal for the sentinel (whose card states no quantum workload)."""
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS, get_contract
    schema_c = get_contract("theprotocol_getQuantumWorkloadSchema")
    assert schema_c.tier == "1" and {"uri", "version", "schema_sha256", "mode", "schema"} <= set(schema_c.expect_keys)
    search = get_contract("theprotocol_discoverQuantumAgents")
    assert search.expect_status == "success" and {"agents", "total", "facets", "filters"} <= set(search.expect_keys)
    one = MCP_CONTRACTS["theprotocol_getQuantumWorkload"]
    assert one.arguments == {"did": "${sentinel_did}"} and one.requires_fixtures == ["sentinel_did"]
    assert one.expect_status == "error_4xx"
    assert set(one.expect_error_message_contains) == {"no_quantum_workload", "agent_card_not_found"}
