"""§MCPTEST30 V0536: the MCP tester's latency baseline belongs to one suite against one target.

WHY THIS EXISTS. `_record_latency_baseline` keeps the last ten elapsed times per tool and flags a row that runs over
twice the median of its prior three. It keyed that buffer by tool and a frame guess, and the console runs several
suites against one target: round 10's cloud-op alpha sweep (run 9b5d52c12a3048ea, 2026-10-01), which reaches its
tools through an operator registry, flagged 27 "latency regressions" against the main sweep's times (listToolsets 3206
ms against 86 ms), and pushed its own times into the main sweep's median in turn. The frame guess read "test-b" or
"8003", the retired tier's names, so sbx-beta-registry was labelled sandbox-a. The Prometheus gauges carried the same
blind spot: keyed by target alone, each read whichever suite ran last.

Test 2 is the fix; test 3 is its control (one suite really slowing down is still flagged), and test 4 reproduces the
old keying through the same function, so it fails if the key stops separating suites.
"""
from agentvault_registry.routers import mcp_tester as mt

MAIN = "flow_mcp_lifecycle_complete"
CLOUDOP = "flow_mcp_lifecycle_cloudop_sandboxalpha_complete"
ALPHA = "http://sbx-alpha-registry:8000"


class FakeRedis:
    """The four list calls the baseline makes, in memory."""

    def __init__(self):
        self.lists = {}

    async def lrange(self, key, start, end):
        return [v.encode() for v in self.lists.get(key, [])[start:end + 1]]

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, str(value))

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]

    async def expire(self, key, ttl):
        return True


async def _sweep(fake, monkeypatch, suite, elapsed_by_tool):
    async def _get_redis():
        return fake
    monkeypatch.setattr(mt, "get_redis", _get_redis)
    rows = [{"tool": t, "elapsed": e, "healthy": True} for t, e in elapsed_by_tool.items()]
    n = await mt._record_latency_baseline(suite, rows)
    return n, [r["tool"] for r in rows if r.get("latency_regression")]


def test_suite_key_names_the_flow_and_the_target():
    assert mt._suite_key(MAIN, ALPHA) == "flow_mcp_lifecycle_complete@sbx-alpha-registry:8000"
    assert mt._suite_key(MAIN, ALPHA) != mt._suite_key(CLOUDOP, ALPHA)
    assert mt._suite_key(MAIN, ALPHA) != mt._suite_key(MAIN, "http://sbx-beta-registry:8000")
    assert mt._suite_key("", "") == "unknown@?"


async def test_a_slower_suite_is_not_a_regression_of_a_faster_one(monkeypatch):
    """THE FIX: three main sweeps at ~86 ms, then the cloud-op sweep at 3206 ms, then the main sweep again."""
    fake = FakeRedis()
    for ms in (84, 86, 90):
        await _sweep(fake, monkeypatch, mt._suite_key(MAIN, ALPHA), {"theprotocol_listToolsets": ms})
    n, flagged = await _sweep(fake, monkeypatch, mt._suite_key(CLOUDOP, ALPHA), {"theprotocol_listToolsets": 3206})
    assert (n, flagged) == (0, [])
    n, flagged = await _sweep(fake, monkeypatch, mt._suite_key(MAIN, ALPHA), {"theprotocol_listToolsets": 88})
    assert (n, flagged) == (0, [])
    # each suite kept its own times: the cloud-op time is not in the main sweep's buffer
    main_key = mt._rk("latency", mt._suite_key(MAIN, ALPHA), "theprotocol_listToolsets")
    assert fake.lists[main_key] == ["88", "90", "86", "84"]


async def test_a_suite_that_really_slows_down_is_still_flagged(monkeypatch):
    """The control: the baseline still does its job inside one suite."""
    fake = FakeRedis()
    suite = mt._suite_key(CLOUDOP, ALPHA)
    for ms in (3100, 3206, 3150):
        await _sweep(fake, monkeypatch, suite, {"theprotocol_listToolsets": ms})
    n, flagged = await _sweep(fake, monkeypatch, suite, {"theprotocol_listToolsets": 9000})
    assert (n, flagged) == (1, ["theprotocol_listToolsets"])


async def test_one_buffer_for_two_suites_is_what_flagged_them(monkeypatch):
    """The old keying, reproduced through the same function: one key for both suites flags the slower one."""
    fake = FakeRedis()
    shared = "sandbox-a"
    for ms in (84, 86, 90):
        await _sweep(fake, monkeypatch, shared, {"theprotocol_listToolsets": ms})
    n, flagged = await _sweep(fake, monkeypatch, shared, {"theprotocol_listToolsets": 3206})
    assert (n, flagged) == (1, ["theprotocol_listToolsets"])


def test_the_frame_label_reads_the_target_host():
    assert mt._frame_label("http://sbx-beta-registry:8000") == "sandbox-b"
    assert mt._frame_label(ALPHA) == "sandbox-a"
    assert mt._frame_label("http://agentvault_registry_test_b:8003") == "sandbox-b"
    assert mt._frame_label("http://registry-test-b:8000") == "sandbox-b"
    assert mt._frame_label("") == "sandbox-a"


def test_every_tester_series_names_its_suite(monkeypatch):
    """The gauges and the run counter carry `flow`, and the emitter labels every gauge with it."""
    if not mt._MCP_PROM_AVAILABLE:
        return
    for g in (mt.MCP_TESTER_PASS_RATE, mt.MCP_TESTER_TOTAL, mt.MCP_TESTER_HEALTHY, mt.MCP_TESTER_TIER_DRIFT,
              mt.MCP_TESTER_CONTRACT_GAP, mt.MCP_TESTER_AUTH_MATRIX_VIOLATIONS, mt.MCP_TESTER_CROSS_FRAME_DRIFT,
              mt.MCP_TESTER_LATENCY_REGRESSIONS, mt.MCP_TESTER_WRAPPER_DRIFT, mt.MCP_TESTER_EMISSION_INTEGRITY):
        assert tuple(g._labelnames) == ("target", "frame", "flow"), g
    assert tuple(mt.MCP_TESTER_RUNS._labelnames) == ("target", "frame", "flow", "outcome")

    seen = []

    class Rec:
        def __init__(self, name):
            self.name = name

        def labels(self, **kw):
            seen.append((self.name, kw))
            return self

        def set(self, value):
            return None

    for name in ("MCP_TESTER_PASS_RATE", "MCP_TESTER_TOTAL", "MCP_TESTER_HEALTHY", "MCP_TESTER_TIER_DRIFT",
                 "MCP_TESTER_CONTRACT_GAP", "MCP_TESTER_AUTH_MATRIX_VIOLATIONS", "MCP_TESTER_CROSS_FRAME_DRIFT",
                 "MCP_TESTER_LATENCY_REGRESSIONS", "MCP_TESTER_WRAPPER_DRIFT", "MCP_TESTER_EMISSION_INTEGRITY"):
        monkeypatch.setattr(mt, name, Rec(name))
    mt._emit_mcp_metrics(ALPHA, "sandbox-a", {"total": 10, "healthy": 9}, flow=CLOUDOP)
    assert len(seen) == 10
    assert all(kw == {"target": ALPHA, "frame": "sandbox-a", "flow": CLOUDOP} for _, kw in seen)


# ── §MCPTEST30 (V0544): a box under load slows every tool at once ───────────────────────────────────────────────────
# Round 11's strict run (186f01a3a7794b12) flagged 125 "latency regressions" while a build ran beside it, the cloud-op
# runs 46 and 29: the box, not the tools. A tool regresses only beyond twice the run's own slowdown (the median ratio of
# every baselined tool to its baseline, from 20 tools; never below 1.0).

TOOLS = [f"theprotocol_tool{i:02d}" for i in range(30)]


async def _baseline(fake, monkeypatch, suite, ms=100):
    for _ in range(3):
        await _sweep(fake, monkeypatch, suite, {t: ms for t in TOOLS})


async def _sweep_out(fake, monkeypatch, suite, elapsed_by_tool):
    async def _get_redis():
        return fake
    monkeypatch.setattr(mt, "get_redis", _get_redis)
    rows = [{"tool": t, "elapsed": e, "healthy": True} for t, e in elapsed_by_tool.items()]
    out = {}
    n = await mt._record_latency_baseline(suite, rows, out=out)
    return n, [r["tool"] for r in rows if r.get("latency_regression")], out


async def test_a_run_the_box_slowed_is_not_thirty_regressions(monkeypatch):
    fake, suite = FakeRedis(), mt._suite_key(MAIN, ALPHA)
    await _baseline(fake, monkeypatch, suite)
    n, flagged, out = await _sweep_out(fake, monkeypatch, suite, {t: 250 for t in TOOLS})   # every tool 2.5x
    assert (n, flagged) == (0, []) and out == {"run_factor": 2.5, "baselined_tools": 30}


async def test_a_tool_slower_than_the_slowed_run_is_still_flagged(monkeypatch):
    """The control: under the same load, the one tool that slowed far beyond the rest is a regression."""
    fake, suite = FakeRedis(), mt._suite_key(MAIN, ALPHA)
    await _baseline(fake, monkeypatch, suite)
    elapsed = {t: 250 for t in TOOLS}
    elapsed["theprotocol_tool07"] = 900                       # 9x its baseline, 3.6x the run's 2.5x
    n, flagged, out = await _sweep_out(fake, monkeypatch, suite, elapsed)
    assert (n, flagged) == (1, ["theprotocol_tool07"]) and out["run_factor"] == 2.5


async def test_too_few_baselined_tools_or_a_fast_run_keep_the_plain_rule(monkeypatch):
    fake, suite = FakeRedis(), mt._suite_key(MAIN, ALPHA)
    few = {t: 100 for t in TOOLS[:5]}
    for _ in range(3):
        await _sweep(fake, monkeypatch, suite, few)
    n, flagged, out = await _sweep_out(fake, monkeypatch, suite, {t: 250 for t in TOOLS[:5]})
    assert n == 5 and out == {"run_factor": 1.0, "baselined_tools": 5}      # five tools estimate no run factor
    fake2, suite2 = FakeRedis(), mt._suite_key(CLOUDOP, ALPHA)
    await _baseline(fake2, monkeypatch, suite2)
    fast = {t: 50 for t in TOOLS}
    fast["theprotocol_tool03"] = 250                         # 2.5x its baseline in a run otherwise twice as fast
    n, flagged, out = await _sweep_out(fake2, monkeypatch, suite2, fast)
    assert (n, flagged, out["run_factor"]) == (1, ["theprotocol_tool03"], 1.0)   # a fast run tightens nothing
