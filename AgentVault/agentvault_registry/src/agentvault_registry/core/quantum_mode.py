"""V0660: QUANTUM_WORKLOADS_MODE, the frame switch for quantum workloads (off, shadow, on).

The source default is off and byte-inert. shadow checks and reports what on would refuse, without refusing; on
refuses. Read on every call, so a recreate with a new value takes effect without a code change.
"""
from __future__ import annotations

import os

MODES = ("off", "shadow", "on")


def quantum_workloads_mode() -> str:
    """The frame's mode: off, shadow or on; any other value reads as off."""
    value = os.environ.get("QUANTUM_WORKLOADS_MODE", "off").strip().lower()
    return value if value in MODES else "off"
