"""§FRAMEKIT P3.2 (2026-09-12) — the FRAME context of the operator CLI: a stack dir the standup driver built,
its three databases read from its own env, its two load-bearing volumes read from its compose, and the
refusals (a dir that is not a frame; a production frame; another frame's archive)."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator.config import FrameNotFound, frame_context  # noqa: E402

COMPOSE = """services:
  juice-db:
    image: postgres:16-alpine
  juice-registry:
    ports:
      - "127.0.0.1:8750:8000"
  juice-event-store:
    ports:
      - "127.0.0.1:8761:8200"
volumes:
  juice_pg_registry_1788800000:
    name: juice_pg_registry_1788800000
  juice_spire_data_1788800000:
    name: juice_spire_data_1788800000
  juice_registry_data_1788800000:
    name: juice_registry_data_1788800000
"""
ENV = """FT_DB_POSTGRES_USER=registry
FT_DB_POSTGRES_DB=frame_test_registry
FT_TEGDB_POSTGRES_USER=teg
FT_TEGDB_POSTGRES_DB=frame_test_teg
FT_ESDB_POSTGRES_USER=eventstore
FT_ESDB_POSTGRES_DB=frame_test_events
SPIRE_TRUST_DOMAIN=juice.theprotocol.cloud
"""


def _stack(tmp_path, name="juice", env_label="sandbox", env=ENV):
    d = tmp_path / f"{name}-1788800000"; d.mkdir()
    (d / ".env.frame-test").write_text(env)
    (d / "docker-compose.frame-test.yml").write_text(COMPOSE.replace("juice", name))
    (d / "hetzner-demo-run.json").write_text(json.dumps({"name": name, "env_label": env_label, "trust_domain": f"{name}.theprotocol.cloud"}))
    return d


def test_frame_context_reads_databases_volumes_and_ports_from_the_stack(tmp_path):
    ctx = frame_context(_stack(tmp_path))
    assert ctx.is_frame and ctx.name == "juice" and ctx.frame_env_label == "sandbox" and ctx.frame_trust_domain == "juice.theprotocol.cloud"
    assert ctx.compose_file.name == "docker-compose.frame-test.yml" and ctx.env_path.name == ".env.frame-test"
    dbs = ctx.frame_db_services()
    assert [(d["service"], d["user"], d["db"], d["dump"]) for d in dbs] == [
        ("juice-db", "registry", "frame_test_registry", "registry.dump"),
        ("juice-teg-db", "teg", "frame_test_teg", "teg.dump"),
        ("juice-es-db", "eventstore", "frame_test_events", "eventstore.dump")]
    # the two load-bearing volumes only (pg volumes are the dumps' job)
    assert ctx.frame_volumes() == ["juice_spire_data_1788800000", "juice_registry_data_1788800000"]
    assert ctx.frame_registry_port == 8750 and ctx.frame_es_port == 8761
    assert ctx.frame_app_services()[0] == "juice-registry" and ctx.frame_app_services()[-1] == "juice-spire-server"


def test_frame_context_refuses_a_dir_that_is_not_a_frame(tmp_path):
    d = tmp_path / "not-a-frame"; d.mkdir(); (d / ".env.frame-test").write_text("X=1\n")
    with pytest.raises(FrameNotFound) as e:
        frame_context(d)
    assert "docker-compose.frame-test.yml" in str(e.value) and "hetzner-demo-run.json" in str(e.value)


def test_a_pre_d12_frame_reads_its_databases_from_the_containers(tmp_path):
    # the 2026-09-03 sandbox pair carries no FT_*_POSTGRES_* keys: the DB container's own env is the source
    ctx = frame_context(_stack(tmp_path, env="SPIRE_TRUST_DOMAIN=juice.theprotocol.cloud\n"))
    fake = {"juice-db": {"POSTGRES_USER": "registry", "POSTGRES_DB": "frame_test_registry"},
            "juice-teg-db": {"POSTGRES_USER": "teg", "POSTGRES_DB": "frame_test_teg"},
            "juice-es-db": {"POSTGRES_USER": "eventstore", "POSTGRES_DB": "frame_test_events"}}
    dbs = ctx.frame_db_services(inspect=lambda c: fake.get(c, {}))
    assert [(d["service"], d["user"], d["db"]) for d in dbs] == [("juice-db", "registry", "frame_test_registry"),
                                                                 ("juice-teg-db", "teg", "frame_test_teg"), ("juice-es-db", "eventstore", "frame_test_events")]
    # a container that does not exist yields nothing for that database: the backup then refuses (len != 3)
    assert len(ctx.frame_db_services(inspect=lambda c: {})) == 0


def test_restore_refusals_are_decided_from_the_manifest_and_the_meta(tmp_path, monkeypatch):
    """The two refusals sit at the top of _do_frame_restore: another trust domain, a production frame."""
    from tp_operator.commands import restore as rs
    import tarfile, tempfile, hashlib
    ctx = frame_context(_stack(tmp_path, env_label="prod"))
    # an archive of ANOTHER frame, well-formed
    td = tmp_path / "arc"; td.mkdir()
    (td / "MANIFEST.json").write_text(json.dumps({"schema_version": "2.0", "kind": "frame", "frame": "brrr", "trust_domain": "brrr.theprotocol.cloud", "entries": []}))
    arc = tmp_path / "frame-backup-brrr.tar.gz"
    with tarfile.open(arc, "w:gz") as t:
        t.add(td / "MANIFEST.json", arcname="MANIFEST.json")
    class _Out:
        def line(self, *a, **k): pass
        def warn(self, *a, **k): pass
    with pytest.raises(RuntimeError) as e:
        rs._do_frame_restore(ctx, _Out(), arc, snapshot_first=False)
    assert "trust_domain" in str(e.value) and "--force-cross-frame" in str(e.value)
    with pytest.raises(RuntimeError) as e2:
        rs._do_frame_restore(ctx, _Out(), arc, snapshot_first=False, force_cross_frame=True)
    assert "PRODUCTION" in str(e2.value) and "--i-mean-production" in str(e2.value)
    # an operator archive under --frame is refused by kind
    (td / "MANIFEST.json").write_text(json.dumps({"schema_version": "1.0", "operator": "op-x", "entries": []}))
    arc2 = tmp_path / "operator-backup.tar.gz"
    with tarfile.open(arc2, "w:gz") as t:
        t.add(td / "MANIFEST.json", arcname="MANIFEST.json")
    with pytest.raises(RuntimeError) as e3:
        rs._do_frame_restore(ctx, _Out(), arc2, snapshot_first=False)
    assert "not a frame backup" in str(e3.value)


def test_doctor_verdict_helpers_are_pure():
    from tp_operator.commands import doctor as dc
    assert dc.limiter_verdict("1200", "prod")[0] == "ok" and dc.limiter_verdict("", "prod")[0] == "fail"
    assert dc.limiter_verdict("", "sandbox")[0] == "ok" and dc.limiter_verdict("1200", "sandbox")[0] == "warn"
    assert dc.limiter_verdict("", "unknown")[0] == "not-measured"
    assert dc.rails_verdict({"a": 200, "b": 200}) == ("ok", "2/2 answer 200") and dc.rails_verdict({"a": 500, "b": 200})[0] == "fail"
    assert dc.delta_verdict("0.0", "OK")[0] == "ok" and dc.delta_verdict(0, "ok")[0] == "ok" and dc.delta_verdict("3", "BREACH")[0] == "fail"
    assert dc.delta_verdict(None, None)[0] == "not-measured"
    act = [{"labels": {"job": "juice-registry", "frame": "juice"}, "health": "up"}, {"labels": {"job": "juice-teg", "frame": "juice"}, "health": "up"},
           {"labels": {"job": "juice-event-store", "frame": "juice"}, "health": "down"}, {"labels": {"job": "eu-registry", "frame": "eu"}, "health": "up"}]
    v, d = dc.targets_verdict(act, "juice"); assert v == "warn" and "juice-event-store" in d
    assert dc.targets_verdict(act, "brrr")[0] == "fail"           # nothing scrapes it: the §STATUSCOVERAGE class
    eu = [{"labels": {"job": f"eu-{c}", "frame": "eu"}, "health": "up"} for c in ("registry", "teg", "event-store")]
    assert dc.targets_verdict(eu, "eu")[0] == "ok"
    assert dc.targets_verdict(eu[:1], "eu")[0] == "warn"        # two of three missing is a warning, not silence
