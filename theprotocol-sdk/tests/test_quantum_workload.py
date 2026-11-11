"""V0660 (a) (session-code, 2026-11-08): the quantum workload agent card extension in the SDK.

theprotocol.quantum ships the extension's JSON Schema (the same bytes a registry checks cards against; the registry pins
the same digest) and carries its rules as Pydantic models: the schema's own example is a QuantumWorkload, the models
refuse what the schema refuses (checked against the schema itself with jsonschema), a card's entry is read and written,
and the index facets are the spec's derivation.

RED on origin/master (ad4e9748): theprotocol.quantum does not exist.
"""
import copy
import hashlib
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from theprotocol.models import AgentCard
from theprotocol.quantum import (
    QUANTUM_WORKLOAD_EXTENSION_URI, SCHEMA_SHA256, QuantumWorkload, as_datetime, load_schema, schema_bytes,
)

PINNED = "99af03a3ac40a0977c85a7c4aebdd94c9e06020b55e63a95f31184b2732abfab"
SPEC = pathlib.Path(__file__).resolve().parents[2] / "PRODUCTION_DOCS" / "SPECS" / "Quantum_Agent_Card_Extension_v1.0_schema.json"


def _entry():
    return copy.deepcopy(load_schema()["examples"][0])


def test_the_package_ships_the_published_schema_bytes():
    assert hashlib.sha256(schema_bytes()).hexdigest() == PINNED == SCHEMA_SHA256
    s = load_schema()
    assert s["properties"]["uri"]["const"] == QUANTUM_WORKLOAD_EXTENSION_URI
    Draft202012Validator.check_schema(s)


def test_the_package_copy_is_the_specs_where_the_stack_is_checked_out():
    if not SPEC.exists():
        pytest.skip("the stack's PRODUCTION_DOCS is not beside this SDK here (an SDK-only checkout); the digest pin above "
                    "still holds the bytes")
    assert SPEC.read_bytes() == schema_bytes()


def test_the_example_is_a_workload_and_round_trips():
    e = _entry()
    w = QuantumWorkload.from_extension(e)
    assert w.version == "1.0" and [b.id for b in w.backends] == ["statevector-32", "heavy-hex-27-noisy"]
    assert w.model_dump(mode="json", exclude_none=True) == e["params"]
    assert w.to_extension_dict(description=e["description"]) == {k: v for k, v in e.items() if k != "required"}
    assert w.to_extension().uri == QUANTUM_WORKLOAD_EXTENSION_URI
    assert as_datetime(w.backends[1].calibration.as_of).isoformat() == "2026-11-07T11:30:00+00:00"


def test_the_index_is_the_specs_derivation():
    assert QuantumWorkload.from_extension(_entry()).facets() == {
        "version": "1.0", "roles": ["meter", "provider"], "kinds": ["emulator", "simulator"],
        "modalities": ["simulator", "superconducting"], "backends": 2, "max_qubits": 32, "max_logical_qubits": None,
        "formats": ["openqasm3", "qir"], "jurisdictions": ["DE"], "rungs": [1, 2, 3], "pricing_model": "per_shot"}


def test_a_card_is_read_at_the_top_level_only():
    card = {"name": "q", "extensions": [{"uri": "https://example.org/other"}, _entry()]}
    assert QuantumWorkload.from_card(card).roles == ["provider", "meter"]
    assert QuantumWorkload.from_card({"name": "plain"}) is None and QuantumWorkload.from_card(None) is None
    assert QuantumWorkload.from_card({"capabilities": {"extensions": [_entry()]}}) is None
    model = AgentCard.model_validate({
        "protocolVersion": "1.0", "humanReadableId": "lab/q", "agentVersion": "1", "name": "q", "description": "q",
        "url": "https://lab.example.org/a2a", "provider": {"name": "Lab"}, "capabilities": {"streaming": False},
        "authSchemes": [{"scheme": "bearer"}], "extensions": [_entry()]})
    assert QuantumWorkload.from_card(model).backends[0].qubits.physical == 32
    with pytest.raises(ValueError):
        QuantumWorkload.from_extension({"uri": "https://example.org/other", "params": {}})


def _mutations():
    def at(path, value):
        def f(p):
            node = p
            for k in path[:-1]:
                node = node[k]
            if value is _DEL:
                del node[path[-1]]
            else:
                node[path[-1]] = value
        return f
    return {
        "simulator of another modality": at(["backends", 0, "modality"], "superconducting"),
        "emulator states simulator": at(["backends", 1, "modality"], "simulator"),
        "qpu without calibration": lambda p: (p["backends"][0].update(kind="qpu", modality="photonic")),
        "ledger keeps circuits": at(["data", "ledger_keeps"], ["hashes", "circuits"]),
        "an amount in pricing": at(["pricing", "base_rate"], "5"),
        "per_shot metered in tasks": at(["pricing", "unit"], "task"),
        "no payment extension named": at(["pricing", "payment_extension"], _DEL),
        "rung 3 without its basis": at(["evidence", "rung_3_basis"], _DEL),
        "rung 1 test that is statistical": at(["evidence", "acceptance_tests", 0, "method"], "test_circuits"),
        "rung 2 without its rates": at(["evidence", "acceptance_tests", 1, "false_accept_rate"], _DEL),
        "heavy-hex without its map": at(["backends", 1, "connectivity", "coupling_map"], _DEL),
        "a provider without backends": at(["backends"], _DEL),
        "an unknown role": at(["roles"], ["provider", "oracle"]),
        "a format by another name": at(["backends", 0, "formats"], ["OpenQASM"]),
        "an x- format": at(["backends", 0, "formats"], ["openqasm3", "x-pulse"]),
        "a timestamp without an offset": at(["backends", 0, "as_of"], "2026-11-07T12:00:00"),
        "a decoder on the network": at(["backends", 1, "qubits", "logical"], {
            "count": 1, "code": "surface-d3", "decoder": {"name": "d", "version": "1", "placement": "network"}}),
        "a decoder next to the device": at(["backends", 1, "qubits", "logical"], {
            "count": 1, "code": "surface-d3", "decoder": {"name": "d", "version": "1", "placement": "co-located"}}),
        "a residency by name": at(["data", "residency"], ["Germany"]),
        "an extra key": at(["data", "notes"], "x"),
        "version 2": at(["version"], "2.0"),
        "an export note not self-declared": at(["data", "export_control", "self_declared"], False),
        # V0660 (a) review: JSON types are not coerced (the models are strict, as the schema is)
        "qubits written as a string": at(["backends", 0, "qubits", "physical"], "32"),
        "qubits written as true": at(["backends", 0, "qubits", "physical"], True),
        "qubits written 32.0": at(["backends", 0, "qubits", "physical"], 32.0),
        "an error rate written as a string": at(["backends", 1, "calibration", "median_1q_error"], "0.1"),
        "an error rate written as true": at(["backends", 1, "calibration", "median_1q_error"], True),
        "mid-circuit measurement written as a string": at(["backends", 0, "limits", "mid_circuit_measurement"], "true"),
        "mid-circuit measurement written as 1": at(["backends", 0, "limits", "mid_circuit_measurement"], 1),
        "a test's rung written as true": at(["evidence", "acceptance_tests", 0, "rung"], True),
        "a rung listed as true": at(["evidence", "verification_rungs"], [True, 2, 3]),
        "an export note self-declared as 1": at(["data", "export_control", "self_declared"], 1),
        "retention written as a string": at(["data", "retention", "circuits_days"], "0"),
    }


_DEL = object()


@pytest.mark.parametrize("label", sorted(_mutations()))
def test_the_models_refuse_what_the_schema_refuses(label):
    validator = Draft202012Validator(load_schema())
    e = _entry()
    _mutations()[label](e["params"])
    schema_ok = not list(validator.iter_errors(e))
    try:
        QuantumWorkload.from_extension(e)
        model_ok = True
    except ValidationError:
        model_ok = False
    assert model_ok == schema_ok, f"{label}: schema says {'valid' if schema_ok else 'invalid'}, the models disagree"
    if label in ("an x- format", "a decoder next to the device", "qubits written 32.0"):
        assert schema_ok, label
    else:
        assert not schema_ok, label


def test_the_example_entry_validates_against_the_shipped_schema():
    assert not list(Draft202012Validator(load_schema()).iter_errors(_entry()))
    assert json.loads(json.dumps(_entry())) == _entry()


def _floats_with_no_fraction(node, path=""):
    if isinstance(node, float) and node.is_integer():
        return [path]
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in _floats_with_no_fraction(v, f"{path}.{k}")]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _floats_with_no_fraction(v, f"{path}[{i}]")]
    return []


def test_whole_numbers_are_written_without_a_decimal_point():
    """V0660 (a) review: a card is signed over its canonical JSON (python json.dumps), which a browser verifier
    reproduces with JSON.stringify; 180.0 and 180 are the same number and not the same bytes. The schema's example, and
    what the models write, carry a whole number as an integer (spec section 7)."""
    assert _floats_with_no_fraction(load_schema()["examples"]) == []
    e = _entry()
    e["params"]["backends"][1]["calibration"]["median_t1_us"] = 180.0
    e["params"]["backends"][0]["qubits"]["physical"] = 32.0
    w = QuantumWorkload.from_extension(e)
    assert _floats_with_no_fraction(w.to_extension_dict()) == []
    assert '"median_t1_us": 180,' in json.dumps(w.to_extension_dict()) and w.backends[0].qubits.physical == 32
    assert w.backends[1].calibration.median_1q_error == e["params"]["backends"][1]["calibration"]["median_1q_error"]


def test_an_as_of_is_a_real_date_time():
    """V0660 (a) review: the schema's pattern accepts 2026-13-45T99:99:99Z (format is not asserted); the registry
    refuses it (spec section 7), and so do the models. A fraction of any length the pattern allows reads on Python 3.10."""
    for bad in ("2026-13-45T09:00:00Z", "2026-11-07T25:00:00Z", "2026-11-07T12:00:00+24:00"):
        e = _entry()
        e["params"]["backends"][0]["as_of"] = bad
        assert not list(Draft202012Validator(load_schema()).iter_errors(e)), "the pattern alone accepts it"
        with pytest.raises(ValidationError, match="not a date-time"):
            QuantumWorkload.from_extension(e)
    e = _entry()
    e["params"]["backends"][0]["as_of"] = "2026-11-07T12:00:00.5Z"
    e["params"]["backends"][0]["queue"]["as_of"] = "2026-11-07T12:00:00.1234+01:00"
    w = QuantumWorkload.from_extension(e)
    assert as_datetime(w.backends[0].as_of).isoformat() == "2026-11-07T12:00:00.500000+00:00"
    assert as_datetime(w.backends[0].queue.as_of).isoformat() == "2026-11-07T12:00:00.123400+01:00"
