"""§MCPTEST30 (V0541): the canary judge's 24 h totals are the asking registry's own, the sum of its per-path rows.

Round 11's federation run failed `canary_judge_pass_rate_above_threshold` on 37.6 % (2,012 passed, 3,343 failed) while
sbx-alpha's own results held 191 passes and 1 timeout. The totals came from Prometheus,
`sum by (outcome) (increase(canary_transfer_total[24h]))`, with no label for the asking registry, so every registry
reported the whole scraped fleet: Frame A's paths still fire at the stopped legacy nodes (~114 failures a day each), and
its ~3,600 failures were printed as the sandbox's. The per-path list beside them was always the registry's own.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.routers import canary_judge_admin as J

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "canary_judge_admin.py"


def test_the_totals_are_the_sum_of_the_registrys_own_paths():
    per_path = [{"passes_24h": 48, "failures_24h": 0}, {"passes_24h": 47, "failures_24h": 1},
                {"passes_24h": 48, "failures_24h": 0}, {"passes_24h": 48, "failures_24h": 0}]
    assert J._summary_from_paths(per_path) == {"cycles_24h": 192, "passes_24h": 191, "failures_24h": 1,
                                               "pass_rate_24h": 99.5}


def test_no_firing_reads_as_no_rate():
    assert J._summary_from_paths([])["pass_rate_24h"] is None
    assert J._summary_from_paths([{"passes_24h": 0, "failures_24h": 0}])["pass_rate_24h"] is None


def test_the_status_no_longer_reads_the_fleets_outcome_counter():
    """The control on the source: no PromQL string asks for the outcome totals, and the summary is built from the rows."""
    tree = ast.parse(SRC.read_text())
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if s.startswith("sum by (outcome)")]
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_summary_from_paths"]
    assert len(calls) == 1
