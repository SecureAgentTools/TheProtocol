"""`update --apply` moves the stack to the release it announces (CB-295, CB-338).

It used to pull and recreate whatever ${VERSION} .env.operator already named and then write the target into the
VERSION file, so nothing moved unless the operator had edited the env first, while every later check read the target as
the running version. Now a release the verified channel lists is pulled BY DIGEST and tagged here, and the env names it
(the compose's tag and prefix variables, IMAGE_TAG kept equal) before `up`. Docker, the channel and the backup are
patched out: this pins what the apply writes and pulls.
"""
import os
import stat
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator.commands import backup, update  # noqa: E402
from tp_operator.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OPERATOR_COMPOSE = ROOT / "scripts" / "distribution" / "nginx-templates" / "docker-compose.operator.yml"
STANDALONE_COMPOSE = ROOT / "scripts" / "distribution" / "docker-compose.standalone.yml"
FRAME_COMPOSE = ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl"

COMPOSE = """services:
  registry:
    image: ${IMAGES_PREFIX:-images.theprotocol.cloud}/registry:${VERSION:-stable}
  teg-layer:
    image: ${IMAGES_PREFIX:-images.theprotocol.cloud}/teg-layer:${VERSION:-stable}
  cert-writer:
    image: ${IMAGES_PREFIX:-images.theprotocol.cloud}/cert-writer:${VERSION:-stable}
  redis:
    image: redis:8.10.2-alpine
"""
DIGESTS = {n: "sha256:" + c * 64 for n, c in (("registry", "a"), ("teg-layer", "b"), ("cert-writer", "c"))}


def _doc():
    return {"schema": "theprotocol-release/1", "releases": [
        {"version": "1.0.0-beta.20", "kind": "stable", "registry_software_version": "TheProtocolReleaseV0619",
         "images": {"prefix": "images.example.invalid/kit", "tag": "1.0.0-beta.20", "digests": dict(DIGESTS)}},
        {"version": "1.0.0-beta.19", "kind": "stable"}]}


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TP_OPERATOR_JSON", "TP_OPERATOR_REMOTE_AUDIT"):
        monkeypatch.delenv(var, raising=False)
    d = tmp_path / "cloud-op-x"
    d.mkdir()
    (d / "docker-compose.operator.yml").write_text(COMPOSE)
    env = d / ".env.operator"
    env.write_text("REGISTRY_NAME=cloud-op-x\nVERSION=1.0.0-beta.19\nIMAGES_PREFIX=images.example.invalid\n"
                   "IMAGE_TAG=1.0.0-beta.19\nVERSION=1.0.0-beta.19\n")
    env.chmod(0o600)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(update, "docker_info_ok", lambda: True)
    monkeypatch.setattr(update, "_fetch_channel", lambda: (_doc(), "ok"))
    monkeypatch.setattr(update, "run", fake_run)
    monkeypatch.setattr(update.subprocess, "run", fake_run)
    monkeypatch.setattr(update, "_wait_healthy", lambda ctx, timeout_s=120: True)
    monkeypatch.setattr(update, "acquire_lock", lambda name: nullcontext())
    monkeypatch.setattr(backup, "_do_backup", lambda ctx, out, path, include_volumes=False: {})
    return env, calls


def _env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def test_apply_pulls_the_release_by_digest_and_names_it_in_the_env(stack):
    env, calls = stack
    r = CliRunner().invoke(app, ["--config", str(env), "--yes", "--no-color", "update", "--apply",
                                 "--to-version", "1.0.0-beta.20"])
    assert r.exit_code == 0, r.output
    pulls = [c[2] for c in calls if c[:2] == ["docker", "pull"]]
    assert sorted(pulls) == sorted(f"images.example.invalid/kit/{n}@{d}" for n, d in DIGESTS.items())
    tags = [c[3] for c in calls if c[:2] == ["docker", "tag"]]
    assert sorted(tags) == sorted(f"images.example.invalid/kit/{n}:1.0.0-beta.20" for n in DIGESTS)
    got = _env(env)
    assert (got["VERSION"], got["IMAGES_PREFIX"], got["IMAGE_TAG"]) == (
        "1.0.0-beta.20", "images.example.invalid/kit", "1.0.0-beta.20")
    assert "VERSION=1.0.0-beta.19" not in env.read_text()          # both lines moved, compose reads the last
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert (env.parent / "VERSION").read_text().strip() == "1.0.0-beta.20"
    up = [c for c in calls if "up" in c]
    assert up and calls.index(up[0]) > max(calls.index(c) for c in calls if c[:2] == ["docker", "pull"])


def test_a_version_the_verified_channel_does_not_list_is_refused_and_nothing_moves(stack):
    env, calls = stack
    before = env.read_text()
    r = CliRunner().invoke(app, ["--config", str(env), "--yes", "update", "--apply", "--to-version", "9.9.9"])
    assert r.exit_code == 1 and "not a release the verified channel lists" in r.output
    assert env.read_text() == before and not [c for c in calls if c[:2] == ["docker", "pull"]]


def test_a_compose_that_names_its_images_another_way_is_refused(stack):
    env, calls = stack
    (env.parent / "docker-compose.operator.yml").write_text("services:\n  x-registry:\n    image: ${FT_REG_IMAGE}\n")
    r = CliRunner().invoke(app, ["--config", str(env), "--yes", "update", "--apply", "--to-version", "1.0.0-beta.20"])
    assert r.exit_code == 2 and "frame-update.py" in r.output


@pytest.mark.skipif(not (OPERATOR_COMPOSE.exists() and STANDALONE_COMPOSE.exists() and FRAME_COMPOSE.exists()),
                    reason="the kit's composes are not beside this tree")
def test_the_kits_composes_name_their_images_the_way_the_apply_reads():
    op = update.release_image_vars(OPERATOR_COMPOSE.read_text())
    assert (op["prefix_var"], op["tag_var"], op["names"]) == ("IMAGES_PREFIX", "VERSION",
                                                             ["cert-writer", "registry", "teg-layer"])
    sa = update.release_image_vars(STANDALONE_COMPOSE.read_text())
    assert (sa["prefix_var"], sa["tag_var"]) == ("IMAGE_REGISTRY", "VERSION")
    assert {"registry", "teg-layer", "event-store", "auditor"} <= set(sa["names"])
    assert update.release_image_vars(FRAME_COMPOSE.read_text()) is None


def test_upsert_env_rewrites_every_line_of_a_key_and_appends_a_new_one(tmp_path):
    p = tmp_path / ".env.operator"
    p.write_text("A=1\nVERSION=old\nB=2\nVERSION=older\n")
    os.chmod(p, 0o640)
    update.upsert_env(p, {"VERSION": "new", "IMAGE_TAG": "new"})
    assert p.read_text() == "A=1\nVERSION=new\nB=2\nVERSION=new\nIMAGE_TAG=new\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o640
