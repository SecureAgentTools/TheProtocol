"""The QPU proxy recipe (V0660 (c)): simulators only, no advantage claims."""
from .backends import BACKENDS, Backend, CloudBackend, Result, SimulatorBackend, backend_from, simulate
from .qasm import MEASURE, SUPPORTED_GATES, Circuit, Op, QasmUnsupported, read_openqasm3

__all__ = [
    "BACKENDS", "Backend", "Circuit", "CloudBackend", "MEASURE", "Op", "QasmUnsupported",
    "Result", "SUPPORTED_GATES", "SimulatorBackend", "backend_from", "read_openqasm3", "simulate",
]
from .jobs import FAILED, FINISHED, SUBMITTED, Job, JobStore
from .meter import MeterRefused, ShotClaim, ShotMeter, derive_reference
from .plugins import QuantumReportAction, QuantumResultSource, QuantumSubmitSink
