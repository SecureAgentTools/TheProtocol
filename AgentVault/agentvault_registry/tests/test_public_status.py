"""§STATUSPAGE — the pure helpers behind /api/v1/public/status (no network, no files)."""
from datetime import datetime, timezone
import pytest
from agentvault_registry.routers import public_status as ps


def test_job_for_name_maps_every_frame_shape_and_the_renamed_ops():
    assert ps.job_for_name("Registry A") == "registry-a"
    assert ps.job_for_name("Registry-A") == "registry-a"
    assert ps.job_for_name("TEG Layer A") == "teg-layer-a"
    assert ps.job_for_name("Event Store") == "event-store"
    assert ps.job_for_name("OPA Engine") == "opa"
    assert ps.job_for_name("Frame-B") == "frame-b-registry"
    assert ps.job_for_name("Frame-B Registry") == "frame-b-registry"
    assert ps.job_for_name("Frame-C Registry") == "frame-c-registry"
    assert ps.job_for_name("op-berlin") == "op-berlin"
    # §RENAMEFIX — probed under the original slug, scraped under the new one
    assert ps.job_for_name("op-losangeles") == "op-singapore"
    assert ps.job_for_name("op-houston") == "op-seoul"
    assert ps.job_for_name("op-chicago") == "op-sydney"
    assert ps.job_for_name("op-newyork") == "op-tokyo"
    # §STATUSCOVERAGE — scraped since 2026-09-02
    assert ps.job_for_name("Frame-C TEG") == "frame-c-teg"
    assert ps.job_for_name("Frame-C Event Store") == "frame-c-event-store"
    assert ps.job_for_name("qatest16") == "qatest16"
    # honest None for components nothing scrapes (OPA on frame-c has no host port)
    assert ps.job_for_name("Frame-C OPA") is None
    assert ps.job_for_name("Sandbox Reg A") is None


def test_sandbox_components_stay_off_the_public_page():
    assert ps.is_public_component({"name": "Sandbox Reg A"}) is False
    assert ps.is_public_component({"name": "Registry A"}) is True


def test_overall_state_orders_outage_over_degraded():
    core_up = {"group": "core", "status": "up"}
    op_down = {"group": "operator", "status": "down"}
    core_down = {"group": "core", "status": "down"}
    assert ps.overall_state([]) == "unknown"
    assert ps.overall_state([core_up]) == "operational"
    assert ps.overall_state([core_up, op_down]) == "degraded"
    assert ps.overall_state([core_down, op_down]) == "outage"


def test_merge_rollup_prometheus_wins_on_overlap_and_the_file_keeps_old_days():
    stored = {"registry-a": {"2026-06-01": 0.5, "2026-08-30": 0.9}}
    fresh = {"registry-a": {"2026-08-30": 1.0, "2026-08-31": 1.0}, "opa": {"2026-08-31": 0.99}}
    merged = ps.merge_rollup(stored, fresh)
    assert merged["registry-a"] == {"2026-06-01": 0.5, "2026-08-30": 1.0, "2026-08-31": 1.0}
    assert merged["opa"] == {"2026-08-31": 0.99}
    assert stored["registry-a"]["2026-08-30"] == 0.9  # inputs untouched


def test_measured_dips_lists_only_days_below_the_threshold_newest_first():
    comps = [{"key": "a", "name": "A", "days": [{"date": "2026-09-01", "up": 1.0}, {"date": "2026-09-02", "up": 0.95}, {"date": "2026-08-31", "up": None}]},
             {"key": "b", "name": "B", "days": [{"date": "2026-09-02", "up": 0.9995}]}]
    assert ps.measured_dips(comps) == [{"date": "2026-09-02", "component_key": "a", "name": "A", "up": 0.95}]


def test_incident_validation_refuses_a_resolution_before_the_start_and_bad_ids():
    ok = ps.Incident(id="reboot-2026-08-17", title="Host reboot", impact="major", status="resolved",
                     started_at=datetime(2026, 8, 17, 10, tzinfo=timezone.utc), resolved_at=datetime(2026, 8, 17, 12, 35, tzinfo=timezone.utc))
    assert ok.resolved_at > ok.started_at
    with pytest.raises(ValueError):
        ps.Incident(id="x", title="t", impact="minor", status="resolved",
                    started_at=datetime(2026, 8, 17, 12, tzinfo=timezone.utc), resolved_at=datetime(2026, 8, 17, 11, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        ps.Incident(id="Bad Id", title="t", impact="minor", status="resolved", started_at=datetime(2026, 8, 17, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        ps.Incident(id="ok", title="t", impact="huge", status="resolved", started_at=datetime(2026, 8, 17, tzinfo=timezone.utc))


# ── §FRAMEKIT P3.1 (2026-09-12) — the flagship showed 0 of 90 days: jobs for a frame's own tiles and its peers ──

def test_job_for_name_derives_own_components_and_bare_peers():
    # the frame's own tiles ("<display> Registry/TEG/Event Store/OPA") map to the container prefix the sidecar writes
    assert ps.job_for_name("EU Registry", "EU", "eu") == "eu-registry"
    assert ps.job_for_name("EU TEG", "EU", "eu") == "eu-teg"
    assert ps.job_for_name("EU Event Store", "EU", "eu") == "eu-event-store"
    assert ps.job_for_name("Sandbox Alpha TEG", "Sandbox Alpha", "sbx-alpha") == "sbx-alpha-teg"   # display != prefix
    # peers and operators arrive under a bare identity: the job every frame/operator registry is scraped as
    assert ps.job_for_name("ASIA", "EU", "eu") == "asia-registry"
    assert ps.job_for_name("amsterdam", "EU", "eu") == "amsterdam-registry"
    assert ps.job_for_name("sbxalphaop") == "sbxalphaop-registry"
    # the legacy table still wins for the retiring nodes, and a spaced name that is not ours stays honest None
    assert ps.job_for_name("Registry-A", "EU", "eu") == "registry-a"
    assert ps.job_for_name("Frame-C OPA", "EU", "eu") is None
    assert ps.job_for_name("Test Federation Peer 1788475364797", "EU", "eu") is None


def test_own_identity_reads_the_env(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "Sandbox Alpha"); monkeypatch.setenv("TEG_LAYER_URL", "http://sbx-alpha-teg:8080")
    assert ps.own_identity() == ("Sandbox Alpha", "sbx-alpha")


def test_sandbox_filter_drops_the_old_replicas_only():
    assert ps.is_public_component({"name": "Sandbox Reg A"}) is False
    assert ps.is_public_component({"name": "Sandbox TEG"}) is False
    assert ps.is_public_component({"name": "Sandbox Alpha Registry"}) is True   # a frame NAMED Sandbox Alpha is public
    assert ps.is_public_component({"name": "Sandbox Beta"}) is True


def test_dedupe_by_job_keeps_the_stack_health_row_and_drops_the_synthetic_twin():
    # the flagship listed "EU Registry" (stack-health, live probe) AND "EU registry" (FRESH_NETWORK_JSON names the frame itself)
    stack = [{"name": "EU Registry", "group": "core", "status": "healthy", "ms": 39},
             {"name": "ASIA", "group": "operator", "status": "healthy", "ms": 55},
             {"name": "Test Federation Peer 1788475364797", "group": "operator", "status": "down"}]
    synthetic = [{"name": "EU registry", "job": "eu-registry", "group": "sandbox"},
                 {"name": "ASIA registry", "job": "asia-registry", "group": "sandbox"},
                 {"name": "ASIA TEG", "job": "asia-teg", "group": "sandbox"}]
    out = ps.dedupe_by_job(stack + synthetic, "EU", "eu")
    assert [x["name"] for x in out] == ["EU Registry", "ASIA", "Test Federation Peer 1788475364797", "ASIA TEG"]
    # a row with no job is never deduped (two honest "no history" rows are two rows)
    assert len(ps.dedupe_by_job([{"name": "X Y"}, {"name": "Z W"}])) == 2


def test_a_sandbox_strip_entry_is_not_a_status_component(monkeypatch):
    """§AGORASIM-2: FRESH_NETWORK_JSON rows filed under the sandbox ledger strip feed the landing page's sandbox
    ledger only; the flagship's public status page keeps its 0 sandbox rows. The control: a peer frame still lists."""
    import json as _json
    from agentvault_registry.routers import public_status as _ps
    monkeypatch.setenv("FRESH_NETWORK_JSON", _json.dumps([
        {"name": "ASIA", "slug": "asia", "role": "frame", "ws_path": "/ws/events-asia"},
        {"name": "Sandbox Alpha", "slug": "sbx-alpha", "strip": "sandbox", "ws_path": "/ws/events-sbxalpha"},
        {"name": "Sandbox Beta", "slug": "sbx-beta", "strip": "SANDBOX", "ws_path": "/ws/events-sbxbeta"},
    ]))
    names = [c["name"] for c in _ps._fresh_network_components()]
    assert names == ["ASIA registry", "ASIA EventStore", "ASIA TEG"], names

