"""V0660 (c): tp-proxy generates the card extension from the backend's own facts.

The point of generating it is that nothing in a published card is prose a human typed and then forgot to
update. So the tests here mostly check that changing the MACHINE changes the CARD, and that anything the
recipe cannot read from a machine is refused rather than filled in.

The models and the schema are (a)'s, shipped in theprotocol.quantum: this module builds them, it does not
restate their rules.
"""
from __future__ import annotations

import sys

import pytest

from theprotocol.proxy.quantum.backends import CloudBackend, SimulatorBackend
from theprotocol.proxy.quantum.card import CardIncomplete, extension_for
from theprotocol.proxy.quantum.meter import METERING_CIRCUIT
from theprotocol.quantum import QuantumWorkload
from theprotocol.quantum.models import QUANTUM_WORKLOAD_EXTENSION_URI, QUANTUM_WORKLOAD_VERSION

RECEIPT = {"schema_version": "1.0", "signing_algorithm": "Ed25519"}


def sim(**kw):
    return SimulatorBackend({"id": "sim-1", "qubits": 4, **kw})


class TestItIsAValidExtension:
    def test_it_validates_through_a_s_own_models(self):
        ext = extension_for(sim(), receipt=RECEIPT)
        assert ext["uri"] == QUANTUM_WORKLOAD_EXTENSION_URI
        assert ext["params"]["version"] == QUANTUM_WORKLOAD_VERSION
        card = {"extensions": [ext]}
        assert QuantumWorkload.from_card(card) is not None, "the card we generate must parse as a card"

    def test_whole_numbers_are_integers(self):
        """(a)'s rule: a card is signed over python's json.dumps and verified with JSON.stringify, which
        writes 180 for both, so 180.0 would break a signature check."""
        ext = extension_for(sim(qubits=8), receipt=RECEIPT)
        qubits = ext["params"]["backends"][0]["qubits"]["physical"]
        assert isinstance(qubits, int) and not isinstance(qubits, bool)
        assert qubits == 8

    def test_the_extension_sits_at_the_top_level_shape_a_card_expects(self):
        ext = extension_for(sim(), receipt=RECEIPT)
        assert set(ext) <= {"uri", "params", "description", "required"}


class TestTheFactsComeFromTheMachine:
    def test_changing_the_backend_changes_the_card(self):
        small = extension_for(sim(qubits=2), receipt=RECEIPT)["params"]["backends"][0]
        large = extension_for(sim(qubits=16), receipt=RECEIPT)["params"]["backends"][0]
        assert small["qubits"]["physical"] == 2 and large["qubits"]["physical"] == 16
        assert small["limits"]["max_width"] != large["limits"]["max_width"]

    def test_the_shot_limit_on_the_card_is_the_backend_s_real_ceiling(self):
        ext = extension_for(sim(max_shots=4096), receipt=RECEIPT)
        assert ext["params"]["backends"][0]["limits"]["max_shots"] == 4096

    def test_the_gates_on_the_card_are_the_gates_it_runs(self):
        from theprotocol.proxy.quantum.qasm import MEASURE, SUPPORTED_GATES

        gates = set(extension_for(sim(), receipt=RECEIPT)["params"]["backends"][0]["native_gates"])
        assert gates and gates <= set(SUPPORTED_GATES) - {MEASURE}

    def test_it_says_simulator_because_that_is_what_it_is(self):
        b = extension_for(sim(), receipt=RECEIPT)["params"]["backends"][0]
        assert b["kind"] == "simulator" and b["modality"] == "simulator"


class TestTheMeteringCircuitIsTheRealOne:
    def test_the_card_names_the_circuit_the_meter_actually_proves_against(self):
        """Two places could drift apart: what the card advertises and what the meter builds a claim for.
        They read the same constant, and this test is what keeps that true."""
        ext = extension_for(sim(), receipt=RECEIPT)
        assert ext["params"]["evidence"]["metering_circuit"] == METERING_CIRCUIT

    def test_that_constant_is_the_one_a_shot_claim_carries(self, tmp_path):
        from theprotocol.proxy.quantum.meter import ShotMeter

        m = ShotMeter(dir=str(tmp_path), agent_did="did:theprotocol:eu/x")
        m.record("job-1", shots=10)
        assert m.claim("job-1", reported_units=10).circuit_id == METERING_CIRCUIT


class TestWhatItRefusesToInvent:
    def test_a_stub_cloud_backend_cannot_produce_a_card(self):
        """The adapters are stubs holding no credentials; a card built from one would carry device facts
        nobody read from a device."""
        with pytest.raises(Exception) as e:
            extension_for(CloudBackend({"id": "ibm-1", "vendor": "ibm"}), receipt=RECEIPT)
        assert "stub" in str(e.value) or "facts" in str(e.value)

    def test_without_a_receipt_block_it_refuses_rather_than_guessing(self, monkeypatch):
        """The receipt's schema version and signing algorithm belong to (b). Inventing them here would put
        a version on a published card that no receipt builder honours.

        It makes (b)'s module absent ITSELF rather than relying on the day it is not there yet. Written the
        naive way, this test passed today and would have failed the moment (b) merged, because with the
        module present receipt=None rightly takes (b)'s constants instead of refusing: it pinned the
        environment, not the contract. session-code caught that while landing (b) (room seq 2622)."""
        monkeypatch.setitem(sys.modules, "theprotocol.quantum.receipts", None)
        with pytest.raises(CardIncomplete) as e:
            extension_for(sim(), receipt=None)
        assert "receipt" in str(e.value).lower()

    def test_it_takes_the_receipt_block_from_b_when_that_module_is_there(self):
        """(b) owns the constants; this is the seam, and it is skipped loudly rather than silently while
        (b) is still being written."""
        try:
            from theprotocol.quantum.receipts import RECEIPT_SCHEMA_VERSION, RECEIPT_SIGNING_ALGORITHM
        except Exception:
            pytest.skip("theprotocol.quantum.receipts is not there yet: the (b) seam is NOT MEASURED")
        ext = extension_for(sim())
        assert ext["params"]["evidence"]["receipt"]["schema_version"] == RECEIPT_SCHEMA_VERSION
        assert ext["params"]["evidence"]["receipt"]["signing_algorithm"] == RECEIPT_SIGNING_ALGORITHM

    def test_a_provider_with_no_backend_is_refused_by_a_s_own_validator(self):
        with pytest.raises(Exception) as e:
            extension_for(None, roles=["provider"], receipt=RECEIPT)
        assert "backend" in str(e.value).lower()

    def test_rung_3_is_always_marked_signed_claims(self):
        """Written first as "offering rung 3 is refused", which was the wrong premise: signed_claims is the
        ONLY legal basis for rung 3, so filling it in is not a claim, it is the single meaning the rung
        has. What must be impossible is offering rung 3 SILENTLY, and that is what this now holds."""
        ext = extension_for(sim(), receipt=RECEIPT, verification_rungs=[1, 3])
        assert ext["params"]["evidence"]["rung_3_basis"] == "signed_claims"

    def test_a_card_without_rung_3_does_not_mention_its_basis(self):
        """The control for the test above: it would pass just as loudly if the basis were set always."""
        ext = extension_for(sim(), receipt=RECEIPT, verification_rungs=[1])
        assert "rung_3_basis" not in ext["params"]["evidence"]


class TestTheDataTerms:
    def test_the_ledger_keeps_hashes_and_verdicts_never_circuits(self):
        ext = extension_for(sim(), receipt=RECEIPT)
        keeps = ext["params"]["data"]["ledger_keeps"]
        assert set(keeps) <= {"hashes", "verdicts"}
        assert "circuits" not in keeps

    def test_residency_is_a_jurisdiction_code(self):
        ext = extension_for(sim(), receipt=RECEIPT, residency=["DE"])
        assert ext["params"]["data"]["residency"] == ["DE"]
