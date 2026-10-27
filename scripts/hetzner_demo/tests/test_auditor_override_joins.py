"""§MTLSHOPS (a) (2026-09-15, agentvault2-b5; agentvault2-85's find and calls): the host auditor's frame network joins live
in an untracked docker-compose.override.yml derived from its frames file, never in the tracked compose.

- A slot's network comes from its store URL (<id>-event-store) or, for a slot whose URL is public but whose DSNs still read
  over the frame's network (public_read, T2), from its id; a public_only slot joins nothing. A hyphenated id keeps the
  provisioner's rule: sbx-alpha -> sbx_alpha_network.
- The override holds the derived networks less the ones the tracked compose already joins, renders idempotently, and a
  parity check tells a lost or edited override from a current one.
- auditor_slot writes the join into the override and leaves the tracked compose untouched; a public_only slot writes no
  network at all; unwire removes a network from the override.
RED on master's sidecars and standup_extras (no override, and master's auditor_slot edits the tracked compose).
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidecars  # noqa: E402

TRACKED = ("services:\n  auditor-agent:\n    environment:\n      AUDITOR_EXTRA_FRAMES_JSON: ${AUDITOR_EXTRA_FRAMES_JSON:-[]}\n"
           "      SBX_EVENT_STORE_KEY: x\n    volumes:\n      - ./frames:/app/frames:ro\n    networks:\n      - agentvault_main_network\n"
           "      - eu_network\nnetworks:\n  agentvault_main_network:\n    external: true\n  eu_network:\n    external: true\n")
FRAMES = [
    {"id": "eu", "mode": "prod", "url": "http://eu-event-store:8200", "key": "k", "dsn": "postgresql://u:p@eu-es-db:5432/e"},
    {"id": "lantern", "mode": "sandbox", "url": "http://lantern-event-store:8200", "key": "k"},
    {"id": "sbx-alpha", "mode": "sandbox", "url": "https://sbx-alpha-es.example.test", "public_read": True,
     "dsn": "postgresql://u:p@sbx-alpha-es-db:5432/e"},
    {"id": "t3", "mode": "prod", "url": "https://t3-es.example.test", "public_only": True},
]


@pytest.fixture()
def host(tmp_path):
    d = tmp_path / "TheAuditor"
    (d / "frames").mkdir(parents=True)
    (d / "docker-compose.yml").write_text(TRACKED)
    (d / "frames" / "frames.json").write_text(json.dumps(FRAMES))
    m = {"_root": str(tmp_path), "auditor": {"compose": str(d / "docker-compose.yml"), "frames_file": str(d / "frames" / "frames.json"),
                                             "service": "auditor-agent", "container": "auditor-agent", "env": str(d / ".env")}}
    return d, m


def test_red_networks_come_from_store_urls_and_dsn_slot_ids_and_a_public_only_slot_joins_none(host):
    _d, m = host
    assert sidecars.auditor_frame_networks(m) == ["eu_network", "lantern_network", "sbx_alpha_network"]


def test_red_the_override_holds_the_derived_networks_less_the_tracked_ones_and_parity_sees_a_lost_one(host):
    d, m = host
    assert sidecars.auditor_override_expected(m) == ["lantern_network", "sbx_alpha_network"]
    assert sidecars.render_auditor_override_from_frames(m) == ["lantern_network", "sbx_alpha_network"]
    text = (d / "docker-compose.override.yml").read_text()
    assert "      - lantern_network\n" in text and "  sbx_alpha_network:\n    external: true\n" in text
    assert "eu_network" not in text
    first = text
    sidecars.render_auditor_override_from_frames(m)
    assert (d / "docker-compose.override.yml").read_text() == first
    assert sidecars.auditor_override_parity(m) == (True, ["lantern_network", "sbx_alpha_network"], ["lantern_network", "sbx_alpha_network"])
    (d / "docker-compose.override.yml").unlink()
    assert sidecars.auditor_override_parity(m)[0] is False
    assert (d / "docker-compose.yml").read_text() == TRACKED


def _fake_docker(monkeypatch, calls):
    env = "DATABASE_URL=postgresql+asyncpg://events:pw@f-es-db:5432/events\nINTERNAL_API_KEY=k-es\nPOSTGRES_USER=u\nPOSTGRES_PASSWORD=p\nPOSTGRES_DB=d\n"

    def run(argv, *a, **k):
        calls.append(list(argv))
        out = env if argv[:2] == ["docker", "inspect"] else ""
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(sidecars.extras.subprocess, "run", run)


def test_red_auditor_slot_writes_the_join_into_the_override_and_leaves_the_tracked_compose_alone(host, monkeypatch):
    d, m = host
    calls = []
    _fake_docker(monkeypatch, calls)
    monkeypatch.setattr(sidecars.extras, "AUDITOR_DIR", str(d))
    monkeypatch.setattr(sidecars.extras, "auditor_reload", lambda *a, **k: (200, "ok"))
    sidecars.extras.auditor_slot("sbx-beta", "Sandbox Beta", "SBXB", "sbx-beta-event-store", "sbx-beta-es-db", mode="sandbox",
                                 frames_file=str(d / "frames" / "frames.json"))
    assert (d / "docker-compose.yml").read_text() == TRACKED
    assert sidecars.extras.auditor_override_networks(str(d)) == ["sbx_beta_network"]
    assert ["docker", "network", "connect", "sbx_beta_network", "auditor-agent"] in calls
    entry = [f for f in json.loads((d / "frames" / "frames.json").read_text()) if f["id"] == "sbx-beta"][0]
    assert entry["key"] == "k-es" and entry["dsn"].startswith("postgresql://")


def test_red_a_public_only_slot_needs_the_listed_shape_joins_nothing_and_reads_no_container(host, monkeypatch):
    d, m = host
    calls = []
    _fake_docker(monkeypatch, calls)
    monkeypatch.setattr(sidecars.extras, "AUDITOR_DIR", str(d))
    monkeypatch.setattr(sidecars.extras, "auditor_reload", lambda *a, **k: (200, "ok"))
    monkeypatch.setattr(sidecars.extras, "auditor_slot_shapes", lambda *a, **k: [])
    before = (d / "frames" / "frames.json").read_text()
    with pytest.raises(RuntimeError):
        sidecars.extras.auditor_slot("t4", "T4", "T4C", "t4-event-store", "t4-es-db", mode="prod", public_only=True,
                                     public_url="https://t4-es.example.test", frames_file=str(d / "frames" / "frames.json"))
    assert (d / "frames" / "frames.json").read_text() == before and calls == []
    monkeypatch.setattr(sidecars.extras, "auditor_slot_shapes", lambda *a, **k: ["public_only", "public_read"])
    sidecars.extras.auditor_slot("t4", "T4", "T4C", "t4-event-store", "t4-es-db", mode="prod", public_only=True,
                                 public_url="https://t4-es.example.test/", frames_file=str(d / "frames" / "frames.json"))
    entry = [f for f in json.loads((d / "frames" / "frames.json").read_text()) if f["id"] == "t4"][0]
    assert entry == {"mode": "prod", "id": "t4", "name": "T4", "currency": "T4C", "url": "https://t4-es.example.test", "public_only": True}
    assert not any(c[:2] == ["docker", "inspect"] or c[:3] == ["docker", "network", "connect"] or c[:3] == ["docker", "exec", "-i"] for c in calls)
    assert not (d / "docker-compose.override.yml").exists() and (d / "docker-compose.yml").read_text() == TRACKED


def test_red_unwire_removes_the_network_from_the_override(host, monkeypatch):
    d, m = host
    sidecars.render_auditor_override_from_frames(m)
    monkeypatch.setattr(sidecars.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(sidecars.extras, "auditor_reload", lambda *a, **k: (200, "ok"))
    assert sidecars._auditor_remove_slot(m, "lantern", "lantern_network") == (True, True)
    assert sidecars.extras.auditor_override_networks(str(d)) == ["sbx_alpha_network"]
    assert (d / "docker-compose.yml").read_text() == TRACKED
