"""V0660 (c): the QPU proxy's backend layer — the OpenQASM 3 reader and the built-in simulator.

Simulators only (V0660's ground rules), and no advantage claims anywhere: this is a small state-vector
simulator whose job is to make the recipe runnable and honest, never to be fast.

The rules these tests hold, each one a defect we have paid for before:
  * A circuit the reader cannot run is REFUSED by name, never run approximately. A simulator that
    silently drops a gate it does not implement returns counts that look right and are wrong, which
    is the worst failure available to it (§29e: name what you could not do).
  * A seed makes a run reproducible, so a receipt over counts means something.
  * The shot count the caller asked for is the shot count returned, because the meter proves shots.
  * `facts()` answers every field the card extension requires, from the backend itself.
"""
from __future__ import annotations

import pytest

from theprotocol.proxy.quantum.backends import SimulatorBackend
from theprotocol.proxy.quantum.qasm import QasmUnsupported, read_openqasm3

BELL = """
OPENQASM 3;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c = measure q;
"""

SIXTEEN_WAYS = """
OPENQASM 3;
include "stdgates.inc";
qubit[4] q;
bit[4] c;
h q[0];
h q[1];
h q[2];
h q[3];
c = measure q;
"""

ONE_QUBIT_X = """
OPENQASM 3;
qubit[1] q;
bit[1] c;
x q[0];
c[0] = measure q[0];
"""


class TestTheReader:
    def test_it_reads_a_bell_circuit(self):
        circuit = read_openqasm3(BELL)
        assert circuit.qubits == 2
        assert [op.name for op in circuit.ops] == ["h", "cx", "measure"]
        assert circuit.measured == (0, 1)

    def test_it_refuses_a_gate_it_cannot_run_by_name(self):
        with pytest.raises(QasmUnsupported) as e:
            read_openqasm3(BELL.replace("h q[0];", "ccx q[0], q[1], q[0];"))
        assert "ccx" in str(e.value)

    def test_it_refuses_a_circuit_with_no_measurement(self):
        """Counts come from measurements: a circuit that measures nothing has no counts, and saying so
        is better than returning one all-zero outcome that reads like a result."""
        with pytest.raises(QasmUnsupported) as e:
            read_openqasm3("OPENQASM 3;\nqubit[1] q;\nh q[0];\n")
        assert "measure" in str(e.value).lower()

    def test_it_refuses_a_version_it_does_not_speak(self):
        with pytest.raises(QasmUnsupported) as e:
            read_openqasm3('OPENQASM 2.0;\nqreg q[1];\nmeasure q -> c;\n')
        assert "2.0" in str(e.value)

    def test_it_names_every_gate_it_does_support(self):
        """The supported set is published, so a provider's card can state its native gates from it
        rather than from a comment that rots."""
        from theprotocol.proxy.quantum.qasm import SUPPORTED_GATES

        assert {"h", "x", "cx", "rz", "measure"} <= set(SUPPORTED_GATES)


class TestTheSimulator:
    async def test_x_gate_gives_one_every_shot(self):
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4})
        result = await backend.run(read_openqasm3(ONE_QUBIT_X), shots=64, seed=7)
        assert result.counts == {"1": 64}
        assert sum(result.counts.values()) == 64

    async def test_a_bell_pair_is_correlated_and_never_the_odd_outcomes(self):
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4})
        result = await backend.run(read_openqasm3(BELL), shots=512, seed=7)
        assert set(result.counts) <= {"00", "11"}, "a Bell pair never measures 01 or 10"
        assert sum(result.counts.values()) == 512
        assert all(n > 0 for n in result.counts.values()), "both outcomes appear over 512 shots"

    async def test_the_same_seed_gives_the_same_counts(self):
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4})
        a = await backend.run(read_openqasm3(BELL), shots=256, seed=11)
        b = await backend.run(read_openqasm3(BELL), shots=256, seed=11)
        assert a.counts == b.counts

    async def test_a_different_seed_gives_different_counts(self):
        """Without this the reproducibility test above would pass on a simulator that ignores its seed and
        always returns the same thing — a control, not a nicety.

        It samples SIXTEEN outcomes rather than the Bell pair's two on purpose. Over two outcomes, two
        honest runs of 256 shots land on the same split about one time in twenty, so the obvious version of
        this control would fail a correct simulator every twentieth run, and a test that flakes is a test
        that gets ignored. Over sixteen, matching every bucket by luck is vanishingly unlikely."""
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4})
        a = await backend.run(read_openqasm3(SIXTEEN_WAYS), shots=256, seed=11)
        b = await backend.run(read_openqasm3(SIXTEEN_WAYS), shots=256, seed=12)
        assert a.counts != b.counts

    async def test_the_spread_covers_what_the_circuit_can_produce(self):
        """A simulator that collapsed to one outcome would pass most tests above; this one says the
        distribution is really spread over the sixteen the circuit allows."""
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4})
        result = await backend.run(read_openqasm3(SIXTEEN_WAYS), shots=4096, seed=5)
        assert len(result.counts) == 16, f"four qubits in superposition give sixteen outcomes, got {len(result.counts)}"
        assert sum(result.counts.values()) == 4096

    async def test_it_refuses_more_qubits_than_it_has(self):
        backend = SimulatorBackend({"id": "sim-1", "qubits": 1})
        with pytest.raises(QasmUnsupported) as e:
            await backend.run(read_openqasm3(BELL), shots=8, seed=1)
        assert "2" in str(e.value) and "1" in str(e.value)

    async def test_it_refuses_more_shots_than_its_limit(self):
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4, "max_shots": 100})
        with pytest.raises(QasmUnsupported) as e:
            await backend.run(read_openqasm3(ONE_QUBIT_X), shots=101, seed=1)
        assert "101" in str(e.value) and "100" in str(e.value)

    async def test_it_reports_the_shots_it_ran(self):
        backend = SimulatorBackend({"id": "sim-1", "qubits": 4})
        result = await backend.run(read_openqasm3(ONE_QUBIT_X), shots=33, seed=1)
        assert result.shots == 33


class TestTheFacts:
    def test_facts_answer_every_field_the_card_requires(self):
        """The eleven the extension's schema requires of a backend entry. (c) generates the card from
        these, so a missing one is a card we could not publish honestly."""
        required = ("id", "kind", "modality", "as_of", "location", "qubits",
                    "connectivity", "native_gates", "formats", "limits", "queue")
        facts = SimulatorBackend({"id": "sim-1", "qubits": 4}).facts()
        missing = [k for k in required if k not in facts]
        assert missing == [], f"the card would be missing {missing}"

    def test_it_says_it_is_a_simulator_and_nothing_else(self):
        facts = SimulatorBackend({"id": "sim-1", "qubits": 4}).facts()
        assert facts["kind"] == "simulator"
        assert facts["modality"] == "simulator"

    def test_its_native_gates_are_the_ones_it_really_runs(self):
        from theprotocol.proxy.quantum.qasm import SUPPORTED_GATES

        facts = SimulatorBackend({"id": "sim-1", "qubits": 4}).facts()
        gates = set(facts["native_gates"])
        assert gates <= set(SUPPORTED_GATES), "a card must not advertise a gate the backend refuses"
        assert "measure" not in gates, "measurement is not a native gate"

    def test_facts_validate_against_the_cards_own_model(self):
        """The real contract, stronger than counting required keys: (a)'s strict model. Written as a key
        count first, this test passed while SEVEN fields were wrong — location wanted a jurisdiction, the
        limits were max_* and the queue's status is one of five words. Validate against the model that
        judges a published card, not against a list of names."""
        from theprotocol.quantum.models import Backend as CardBackend

        CardBackend.model_validate(SimulatorBackend({"id": "sim-1", "qubits": 4}).facts())

    def test_its_as_of_is_a_real_timestamp(self):
        import datetime as dt

        facts = SimulatorBackend({"id": "sim-1", "qubits": 4}).facts()
        parsed = dt.datetime.fromisoformat(facts["as_of"].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, "every device fact carries its as_of, and it is a real date-time"


class TestAProviderBringsItsOwnSimulator:
    """The recipe ships a small built-in simulator and no accelerated one, because an accelerated path we
    cannot run here is a path we cannot test: this box has no numpy, no qiskit and no aer. What it ships
    instead is the seam — `kind` may be a "module:Class" path to a provider's own Backend — so a bigger
    simulator or a real QPU client is installed and named by whoever has it, and nothing here pretends to
    support a library it never imported.
    """

    def test_a_dotted_kind_loads_a_provider_s_own_backend(self):
        from theprotocol.proxy.quantum.backends import backend_from

        backend = backend_from({"kind": "theprotocol.proxy.quantum.backends:SimulatorBackend",
                                "id": "theirs-1", "qubits": 3})
        assert backend.id == "theirs-1"
        assert backend.facts()["qubits"]["physical"] == 3

    def test_a_dotted_kind_that_is_not_a_backend_is_refused_by_name(self):
        from theprotocol.proxy.quantum.backends import backend_from
        from theprotocol.proxy.quantum.qasm import QasmUnsupported

        with pytest.raises(QasmUnsupported) as e:
            backend_from({"kind": "json:JSONDecoder", "id": "x"})
        assert "Backend" in str(e.value)

    def test_a_dotted_kind_that_does_not_import_says_so(self):
        from theprotocol.proxy.quantum.backends import backend_from
        from theprotocol.proxy.quantum.qasm import QasmUnsupported

        with pytest.raises(QasmUnsupported) as e:
            backend_from({"kind": "nope.not_here:Thing", "id": "x"})
        assert "nope.not_here" in str(e.value)

    def test_the_named_kinds_still_work(self):
        """The control: adding the dotted path must not break the two words a spec normally uses."""
        from theprotocol.proxy.quantum.backends import CloudBackend, SimulatorBackend, backend_from

        assert isinstance(backend_from({"kind": "simulator", "id": "s", "qubits": 2}), SimulatorBackend)
        assert isinstance(backend_from({"kind": "qpu", "id": "i", "vendor": "ibm"}), CloudBackend)
