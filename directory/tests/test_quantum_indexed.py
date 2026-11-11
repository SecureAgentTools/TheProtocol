"""V0660 (a) (session-code, 2026-11-08): the Directory indexes the quantum workload extension a card states.

The index (directory/quantum_reader.py) is the spec's section 8 derivation, the same a registry's discovery states:
roles, backend kinds and modalities, the backend count, the most physical and logical qubits, the formats, the
jurisdictions, the verification rungs and the metering model. The store keeps it beside the agent (quantum_json) and
`agents(...)` filters on it (quantumOnly, quantumRole, quantumKind, quantumModality, quantumMinQubits, quantumFormat,
quantumJurisdiction, quantumRung); `agent { quantum { ... } }` answers it. A query that asks none of the filters lists
what it listed before.

Registry-free (the reader-gate CI job runs it in a plain container); the ingest wiring is test_quantum_indexed_ingest.py.
RED on origin/master (ad4e9748): directory.quantum_reader does not exist, the store has no quantum_json and the schema
no quantum field.
"""
import copy
import json

from directory import quantum_reader as QR
from directory.schema import schema
from directory.store import Store

URI = "https://theprotocol.cloud/extensions/v1/quantum/workload"


def _ext():
    return {"uri": URI, "params": {
        "version": "1.0", "roles": ["provider", "meter"],
        "backends": [
            {"id": "statevector-32", "kind": "simulator", "modality": "simulator", "qubits": {"physical": 32},
             "formats": ["openqasm3"], "location": {"jurisdiction": "DE"}},
            {"id": "heavy-hex-27", "kind": "emulator", "modality": "superconducting",
             "qubits": {"physical": 27, "logical": {"count": 2, "code": "surface-d3"}},
             "formats": ["openqasm3", "qir"], "location": {"jurisdiction": "DE"}},
        ],
        "pricing": {"model": "per_shot", "unit": "shot",
                    "payment_extension": "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"},
        "evidence": {"verification_rungs": [1, 2, 3]},
        "data": {"ledger_keeps": ["hashes", "verdicts"]}}}


def _card(ext=None):
    return {"name": "Quantum Sim", "extensions": [{"uri": "https://example.org/other"}, ext or _ext()]}


def test_the_index_follows_the_spec_derivation():
    assert QR.facets_from_card(_card()) == {
        "version": "1.0", "roles": ["meter", "provider"], "kinds": ["emulator", "simulator"],
        "modalities": ["simulator", "superconducting"], "backends": 2, "max_qubits": 32, "max_logical_qubits": 2,
        "formats": ["openqasm3", "qir"], "jurisdictions": ["DE"], "rungs": [1, 2, 3], "pricing_model": "per_shot"}


def test_a_value_of_the_wrong_type_or_vocabulary_is_left_out():
    ext = _ext()
    p = ext["params"]
    p["roles"] = ["provider", "oracle", 7]
    p["backends"][0]["qubits"]["physical"] = "32"
    p["backends"][1]["modality"] = "magic"
    p["backends"].append("not a backend")
    p["evidence"]["verification_rungs"] = [True, 2, 9, "3"]
    got = QR.facets_from_card(_card(ext))
    assert got["roles"] == ["provider"] and got["modalities"] == ["simulator"] and got["max_qubits"] == 27
    assert got["backends"] == 2 and got["rungs"] == [2]
    assert QR.facets_from_card(_card({"uri": URI, "params": "x"})) is None


def test_a_card_states_it_at_the_top_level_or_not_at_all():
    assert QR.facets_from_card({"name": "plain"}) is None and QR.facets_from_card(None) is None
    assert QR.facets_from_card({"capabilities": {"extensions": [_ext()]}}) is None


def _store(tmp_path):
    s = Store(str(tmp_path / "d.db"))
    q2 = _ext()
    q2["params"]["backends"] = [q2["params"]["backends"][0]]
    q2["params"]["backends"][0]["location"]["jurisdiction"] = "US-CA"
    q2["params"]["roles"] = ["provider"]
    q2["params"]["evidence"]["verification_rungs"] = [1]
    for i, (name, cd) in enumerate((("plain", {"name": "plain"}), ("qprov", _card()), ("qsim", _card(q2)))):
        f = QR.facets_from_card(cd)
        s.upsert_agent(id=f"c{i}", did=f"did:x:{i}", name=name, hri=None, description=None, is_active=1,
                       updated_at="2026-11-08T00:00:00", source="EU", source_td="eu.td", issuer=None, shape=None,
                       home="EU", bond_json=json.dumps({"status": "none", "is_bonded": False}),
                       enforcement_json=json.dumps({"is_enforced": False, "status": None}), verified=1, reachable=1,
                       fetched_at=0, card_json=json.dumps(cd), org_json=None,
                       quantum_json=json.dumps(f) if f else None)
    return s


def _names(store, **q):
    return sorted(r["name"] for r in store.list_agents(first=50, quantum=q)["rows"])


def test_the_store_filters_on_the_index(tmp_path):
    s = _store(tmp_path)
    assert _names(s) == ["plain", "qprov", "qsim"] == _names(s, only=False, role=None, min_qubits=None)
    assert _names(s, only=True) == ["qprov", "qsim"]
    assert _names(s, modality="superconducting") == ["qprov"] and _names(s, kind="simulator") == ["qprov", "qsim"]
    assert _names(s, min_qubits=30) == ["qprov", "qsim"] and _names(s, min_qubits=33) == []
    assert _names(s, format="qir") == ["qprov"] and _names(s, jurisdiction="US-CA") == ["qsim"]
    assert _names(s, rung=2) == ["qprov"] and _names(s, role="meter") == ["qprov"]
    assert s.list_agents(first=50, quantum={"only": True, "rung": 1})["total"] == 2


def _gql(store, q):
    out = schema.execute_sync(q, context_value={"store": store})
    assert not out.errors, out.errors
    return out.data


def test_graphql_answers_the_index_and_filters_on_it(tmp_path):
    s = _store(tmp_path)
    data = _gql(s, '{ agents(quantumOnly: true, quantumJurisdiction: "us-ca") { total edges { name quantum { '
                   'roles kinds modalities backends maxQubits formats jurisdictions rungs pricingModel } } } }')
    assert data["agents"]["total"] == 1
    assert data["agents"]["edges"][0] == {"name": "qsim", "quantum": {
        "roles": ["provider"], "kinds": ["simulator"], "modalities": ["simulator"], "backends": 1, "maxQubits": 32,
        "formats": ["openqasm3"], "jurisdictions": ["US-CA"], "rungs": [1], "pricingModel": "per_shot"}}
    plain = _gql(s, '{ agent(did: "did:x:0") { name quantum { roles } } }')
    assert plain["agent"] == {"name": "plain", "quantum": None}
    every = _gql(s, "{ agents { total edges { name } } }")
    assert every["agents"]["total"] == 3, "no filter asked: the list it gave before"
    picked = _gql(s, '{ agents(quantumModality: "superconducting", quantumMinQubits: 20, quantumRung: 2, '
                     'quantumFormat: "qir", quantumRole: "provider", quantumKind: "emulator") { edges { name } } }')
    assert [e["name"] for e in picked["agents"]["edges"]] == ["qprov"]


def test_a_store_written_before_v0660_gains_the_column(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, did TEXT, name TEXT, hri TEXT, description TEXT, is_active INTEGER, "
              "updated_at TEXT, source TEXT, source_td TEXT, issuer TEXT, shape TEXT, home TEXT, bond_json TEXT, "
              "enforcement_json TEXT, verified INTEGER NOT NULL DEFAULT 0, reachable INTEGER NOT NULL DEFAULT 1, "
              "fetched_at REAL, card_json TEXT)")
    c.commit()
    c.close()
    Store(path)
    c = sqlite3.connect(path)
    cols = {r[1] for r in c.execute("PRAGMA table_info(agents)")}
    c.close()
    assert {"org_json", "quantum_json"} <= cols
    assert copy.deepcopy(_ext()) == _ext()
