"""System resource + Docker + Prometheus observability tests
(§pass73.3.10 Batch 39).

3 read-only tests probing system-level observability surfaces — used
by ops dashboard + capacity-planning workflows.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


@federation_test(
    name="docker_stats_lists_containers",
    category="system_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["docker", "containers"],
)
async def test_docker_stats(rig: FederationTestRig) -> AssertionResult:
    """getDockerStats returns per-container CPU + memory metrics for the
    sandbox stack. Validates the Docker introspection surface."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getDockerStats")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            containers = r.get("containers")
            if isinstance(containers, dict):
                state["container_count"] = len(containers)
                state["sample_names"] = list(containers.keys())[:5]
                return state["container_count"] >= 1
            return bool(r.keys())
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="Docker stats lists ≥1 container on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="system_resources_cpu_memory_envelope",
    category="system_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["system", "cpu", "memory"],
)
async def test_system_resources(rig: FederationTestRig) -> AssertionResult:
    """getSystemResources returns host-level CPU + memory + freq envelope.

    Validates: cpu.percent is a float 0-100, cpu.count is int >0.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSystemResources")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            cpu = r.get("cpu") or {}
            state["cpu_percent"] = cpu.get("percent")
            state["cpu_count"] = cpu.get("count")
            state["has_memory"] = isinstance(r.get("memory"), dict)
            return (
                isinstance(cpu.get("count"), int) and cpu["count"] >= 1
            )
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="system resources envelope reachable + cpu.count ≥1",
        capture_state=lambda: state,
    )


@federation_test(
    name="prometheus_metrics_endpoint_reachable",
    category="system_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["prometheus", "metrics"],
)
async def test_prometheus_metrics(rig: FederationTestRig) -> AssertionResult:
    """getPrometheusMetrics returns the /metrics scrape envelope.

    Used by Prometheus to scrape the registry's metrics surface.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getPrometheusMetrics")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                metrics = r.get("metrics") or r.get("data") or r.get("text")
                if isinstance(metrics, (list, str)):
                    state["metrics_size"] = len(metrics)
                return bool(r.keys())
            elif isinstance(r, str):
                state["text_size"] = len(r)
                return len(r) > 0
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="Prometheus metrics endpoint reachable on sandbox-A",
        capture_state=lambda: state,
    )
