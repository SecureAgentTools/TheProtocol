"""§TESTBED (2026-09-19): the supply per-registry check asks each frame's own auditor.

A kit frame's Prometheus scrapes only itself, so the single-auditor version saw one registry and failed on a healthy
pair. Both answers together must hold two distinct healthy registries at delta 0.0 and none unhealthy.
"""
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult
from agentvault_registry.api_tests.federation_suite.tests import test_supply_audit_invariant as t


def _reg(rid, healthy=True, delta=0.0):
    return {"registry_id": rid, "healthy": healthy, "last_delta": delta}


class _Rig:
    def __init__(self, by_label):
        self.by_label = by_label

    def mcp(self, label):
        rig = self

        class _C:
            async def call(self, _tool, *_a, **_k):
                return {"per_registry": rig.by_label[label]}
        return _C()

    async def assert_within(self, *, budget_sec, predicate, description, capture_state=None, **_k):
        ok = bool(await predicate())
        return AssertionResult(passed=ok, description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=1, last_state=capture_state() if capture_state else None)


async def test_a_kit_pair_each_reporting_itself_passes():
    res = await t.test_per_registry_health(_Rig({"sandbox-A-admin": [_reg("Larch Sandbox")],
                                                 "sandbox-B-admin": [_reg("Larch Sandbox B")]}))
    assert res.passed is True


async def test_the_shared_monitor_shape_still_passes():
    both = [_reg("Sandbox Alpha"), _reg("Sandbox Beta")]
    assert (await t.test_per_registry_health(_Rig({"sandbox-A-admin": both, "sandbox-B-admin": both}))).passed


async def test_an_unhealthy_registry_fails_and_one_registry_is_not_enough():
    bad = await t.test_per_registry_health(_Rig({"sandbox-A-admin": [_reg("A")],
                                                 "sandbox-B-admin": [_reg("B", healthy=False, delta=3.0)]}))
    assert bad.passed is False
    one = await t.test_per_registry_health(_Rig({"sandbox-A-admin": [_reg("A")], "sandbox-B-admin": [_reg("A")]}))
    assert one.passed is False
