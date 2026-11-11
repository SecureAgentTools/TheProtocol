"""The quantum workload agent card extension (V0660 (a)), TheProtocol's proposed standard for quantum workload agents.

    from theprotocol.quantum import QuantumWorkload, load_schema

The spec: PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md. ``load_schema()`` returns the JSON Schema a registry
checks cards against (the same bytes, SCHEMA_SHA256); ``QuantumWorkload`` carries its rules as Pydantic models, reads an
extension off a card and writes one for it, and states the index facets discovery reads.

V0660 (b): ``theprotocol.quantum.receipts`` is the job receipt chain and the acceptance tests, byte for byte the code a
registry runs at its verify and release steps (``check_job``, ``verify_chain``, ``check_agreement``, ``append_step``);
``python -m theprotocol.quantum.verify`` checks a job offline. Signatures need the cryptography package
(``theprotocol-sdk[anp]``).
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any, Dict

from .models import (  # noqa: F401
    PAYMENT_EXTENSION_URI, QUANTUM_WORKLOAD_EXTENSION_URI, QUANTUM_WORKLOAD_VERSION, AcceptanceTest, Availability,
    Backend, Calibration, Connectivity, CouplingMap, DataTerms, Decoder, Evidence, ExportControl, Limits, Location,
    LogicalQubits, Operator, Pricing, QuantumWorkload, Qubits, Queue, Receipt, Retention, Snapshot, Window, as_datetime,
)

from .receipts import (  # noqa: F401
    ACCEPTANCE_RUNGS, METERING_CIRCUIT, RECEIPT_SCHEMA_VERSION, SIGNING_ALGORITHMS, TEMPLATES, ChainReport, JobReport,
    ReceiptError, append_step, check_agreement, check_job, digest_of, verify_chain,
)

SCHEMA_FILE = "quantum_workload_v1.0.schema.json"
# the bytes the spec publishes and every registry carries (agentvault_registry/static_schemas/, pinned there too)
SCHEMA_SHA256 = "99af03a3ac40a0977c85a7c4aebdd94c9e06020b55e63a95f31184b2732abfab"


def schema_bytes() -> bytes:
    return resources.files(__name__).joinpath(SCHEMA_FILE).read_bytes()


def load_schema() -> Dict[str, Any]:
    """The extension's JSON Schema (Draft 2020-12), as shipped in this package."""
    return json.loads(schema_bytes())


__all__ = [
    "QUANTUM_WORKLOAD_EXTENSION_URI", "QUANTUM_WORKLOAD_VERSION", "PAYMENT_EXTENSION_URI", "SCHEMA_FILE", "SCHEMA_SHA256",
    "schema_bytes", "load_schema", "as_datetime", "QuantumWorkload", "Backend", "Operator", "Location", "Qubits",
    "LogicalQubits", "Decoder", "Connectivity", "CouplingMap", "Limits", "Calibration", "Snapshot", "Queue",
    "Availability", "Window", "Pricing", "Evidence", "Receipt", "AcceptanceTest", "DataTerms", "Retention",
    "ExportControl",
    # V0660 (b): the receipts and the acceptance tests
    "RECEIPT_SCHEMA_VERSION", "SIGNING_ALGORITHMS", "ACCEPTANCE_RUNGS", "METERING_CIRCUIT", "TEMPLATES", "ReceiptError",
    "ChainReport", "JobReport", "append_step", "check_agreement", "check_job", "digest_of", "verify_chain",
]
