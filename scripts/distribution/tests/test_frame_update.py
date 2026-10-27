"""§TESTBED P5 (2026-09-19): frame-update.py's pure parts. The live update and rollback are proven on a sandbox
(sessionlogs2026/FINDINGS_2026-09-19_TESTBED.md)."""
import importlib.util
import json
import os
import stat

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_update", os.path.join(HERE, "..", "frame-update.py"))
fu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fu)

COMPOSE = """services:
  larchsbx-cert-writer:
    image: ${FT_CERT_WRITER_IMAGE:-agentvault2-cert-writer-test-a:latest}
  larchsbx-event-store:
    image: ${FT_ES_IMAGE:-theprotocol/event-store:1.0.0}
  larchsbx-registry:
    image: ${FT_REG_IMAGE:-theprotocol/registry:1.0.0}
  larchsbx-redis:
    image: redis:7-alpine
  larchsbx-auditor-cert-writer:
    image: ${FT_CERT_WRITER_IMAGE:-agentvault2-cert-writer-test-a:latest}
"""


def test_retag_keeps_the_repository_and_changes_the_tag():
    assert fu.retag("theprotocol/registry:1.0.0-beta.6-dev3", "1.0.0-mine.1") == "theprotocol/registry:1.0.0-mine.1"
    assert fu.retag("images.example.org/ns/registry:v1", "v2") == "images.example.org/ns/registry:v2"
    assert fu.retag("", "v2") is None and fu.retag("registry@sha256:abc", "v2") is None


def test_the_services_each_image_key_feeds():
    m = fu.services_by_key(COMPOSE)
    assert m["FT_CERT_WRITER_IMAGE"] == ["larchsbx-cert-writer", "larchsbx-auditor-cert-writer"]
    assert m["FT_REG_IMAGE"] == ["larchsbx-registry"] and m["FT_ES_IMAGE"] == ["larchsbx-event-store"]
    assert "larchsbx-redis" not in sum(m.values(), [])


def test_only_a_sandbox_is_updated():
    assert fu.posture({"sandbox_of": "larch"}, {}) == "sandbox"
    assert fu.posture({}, {"FRAME_POSTURE": "sandbox"}) == "sandbox"
    assert fu.posture({}, {"FRAME_POSTURE": "production"}) == "production"
    assert fu.posture({}, {}) == "production"          # unknown is never treated as a sandbox


def test_upsert_env_keeps_the_files_mode(tmp_path):
    p = tmp_path / ".env.frame-test"
    p.write_text("A=1\nFT_REG_IMAGE=theprotocol/registry:1.0.0\n")
    os.chmod(p, 0o600)
    fu.upsert_env(str(p), {"FT_REG_IMAGE": "theprotocol/registry:2.0.0", "VERSION": "2.0.0"})
    assert p.read_text() == "A=1\nFT_REG_IMAGE=theprotocol/registry:2.0.0\nVERSION=2.0.0\n"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def _frame(tmp_path, posture):
    """A frame stack dir as frame-up leaves it, with one release applied from the channel in its history."""
    sd = tmp_path / "zz-1788800000"
    sd.mkdir()
    (sd / "frame-up.json").write_text(json.dumps({"ports": {"registry": 1, "es": 2}}))
    (sd / ".env.frame-test").write_text(f"FRAME_POSTURE={posture}\nFT_REG_IMAGE=theprotocol/registry:1.0.0-beta.20\n")
    (sd / "docker-compose.frame-test.yml").write_text(COMPOSE)
    (sd / "frame-update.json").write_text(json.dumps([{
        "at": "2026-10-16T10:00:00Z", "release": "1.0.0-beta.20", "rollback_note": "the image alone",
        "from": {"FT_REG_IMAGE": "theprotocol/registry:1.0.0-beta.19"},
        "to": {"FT_REG_IMAGE": "theprotocol/registry:1.0.0-beta.20"}}]))
    return sd


def test_a_release_on_a_production_frame_can_be_rolled_back(tmp_path, monkeypatch):
    """CB-340: the posture gate meant for --version ran before the rollback branch, so a production frame refused
    --rollback of a release it had taken from the channel (exit 2)."""
    sd = _frame(tmp_path, "production")
    applied = []
    monkeypatch.setattr(fu, "apply", lambda rec, sd_, name, env, reason: applied.append(env) or ({}, 0.0, 0.0))
    assert fu.main(["--name", "zz", "--rollback", "--stack-root", str(tmp_path)]) == 0
    assert applied == [{"FT_REG_IMAGE": "theprotocol/registry:1.0.0-beta.19"}]
    assert json.loads((sd / "frame-update.json").read_text()) == []


def test_a_local_build_is_still_refused_on_a_production_frame(tmp_path, monkeypatch):
    _frame(tmp_path, "production")
    monkeypatch.setattr(fu, "apply", lambda *a: pytest.fail("a local build reached a production frame"))
    with pytest.raises(SystemExit) as e:
        fu.main(["--name", "zz", "--version", "1.0.0-mine.1", "--stack-root", str(tmp_path)])
    assert e.value.code == 2
