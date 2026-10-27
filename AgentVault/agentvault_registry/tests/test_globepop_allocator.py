"""§GLOBEPOP — unit tests for the fair per-registry quota allocator.

The allocator is the piece that decides which registries the globe shows.
These tests use the REAL populations measured on registry-a on 2026-08-11
(the day op-doha rendered 21 of its 111 agents because the old cap kept the
first 2000 DIDs by alphabet).
"""
import importlib.util
import os

import pytest

# Load the router by FILE so the test can run in-container against a copied
# module (docker cp + GLOBEPOP_MODULE=...) as well as in CI from the repo tree.
_MODULE_PATH = os.environ.get(
    "GLOBEPOP_MODULE",
    os.path.join(os.path.dirname(__file__),
                 "..", "src", "agentvault_registry", "routers", "agent_locations.py"),
)
_spec = importlib.util.spec_from_file_location("globepop_agent_locations", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_allocate_quotas = _mod._allocate_quotas

# Measured 2026-08-11 (distinct active DIDs per origin + locals):
MEASURED = {
    "Registry-A": 2884,   # locals
    "Frame-C": 3461,
    "Frame-B": 2806,
    "op-tokyo": 140,      # absorbed op-newyork
    "op-washington": 140,
    "op-london": 140,
    "op-singapore": 137,  # absorbed op-losangeles
    "op-sydney": 137,     # absorbed op-chicago
    "op-seoul": 137,      # absorbed op-houston
    "op-paris": 131,
    "op-berlin": 130,
    "op-doha": 111,
    "op-telaviv": 85,
    "op-abudhabi": 45,
    "op-riyadh": 45,
    "(unknown)": 5,
    "qatest16": 4,
}


def test_every_registry_gets_its_minimum_or_full_population():
    q = _allocate_quotas(MEASURED, budget=6000, min_per=50)
    for origin, pop in MEASURED.items():
        assert q[origin] >= min(pop, 50), f"{origin} starved: {q[origin]} < min({pop},50)"


def test_quota_never_exceeds_population():
    q = _allocate_quotas(MEASURED, budget=6000, min_per=50)
    for origin, pop in MEASURED.items():
        assert q[origin] <= pop, f"{origin} over-allocated: {q[origin]} > {pop}"


def test_budget_is_spent_exactly_when_population_allows():
    total_pop = sum(MEASURED.values())
    q = _allocate_quotas(MEASURED, budget=6000, min_per=50)
    assert sum(q.values()) == min(6000, total_pop)


def test_doha_beats_the_old_alphabet_lottery():
    # The whole point: doha showed 21 of 111 under the old cap. Fair sampling
    # at 6000/50 must show meaningfully more than the lottery did.
    q = _allocate_quotas(MEASURED, budget=6000, min_per=50)
    assert q["op-doha"] > 21
    assert q["op-doha"] >= 50


def test_budget_zero_means_everything():
    q = _allocate_quotas(MEASURED, budget=0, min_per=50)
    assert q == MEASURED


def test_minimums_outrank_the_budget():
    # 17 registries x min 50 = 850 > budget 100: every registry STAYS visible.
    q = _allocate_quotas(MEASURED, budget=100, min_per=50)
    for origin, pop in MEASURED.items():
        assert q[origin] == min(pop, 50)


def test_tiny_registry_is_fully_shown():
    q = _allocate_quotas(MEASURED, budget=6000, min_per=50)
    assert q["qatest16"] == 4
    assert q["(unknown)"] == 5


def test_proportionality_orders_the_big_three():
    q = _allocate_quotas(MEASURED, budget=6000, min_per=50)
    assert q["Frame-C"] > q["Registry-A"] > q["Frame-B"] > q["op-tokyo"]


def test_budget_larger_than_population_shows_everything():
    q = _allocate_quotas(MEASURED, budget=50000, min_per=50)
    assert q == MEASURED


def test_empty_populations():
    assert _allocate_quotas({}, budget=6000, min_per=50) == {}
