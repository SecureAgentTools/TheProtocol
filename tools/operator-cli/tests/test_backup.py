"""The operator backup is atomic (CB-293): a failed database dump fails the backup, and the archive appears under its
name, mode 0600, only when it is complete.

It used to warn and carry on: a registry or TEG dump that failed still produced an archive, reported as backed up, and
`update` took that archive as the snapshot it would roll back to. The tar was written in place with the process umask
although it carries .env.operator. The databases are patched out: this pins the two decisions, not docker.
"""
import os
import stat
import sys
import tarfile
from pathlib import Path

import pytest

pytest.importorskip("typer")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator.commands import backup  # noqa: E402
from tp_operator.config import OperatorContext  # noqa: E402
from tp_operator.output import Output  # noqa: E402


def _ctx(tmp_path):
    d = tmp_path / "cloud-op-x"
    d.mkdir()
    (d / ".env.operator").write_text("REGISTRY_NAME=cloud-op-x\nPG_PASS_REGISTRY=not-a-real-one\n")
    (d / "docker-compose.operator.yml").write_text("services: {}\n")
    return OperatorContext(name="cloud-op-x", dir=d, env_path=d / ".env.operator", env={})


def _dumps(monkeypatch, failing=()):
    def fake_dump(ctx, service, user, db, out_path):
        out_path.write_bytes(b"PGDMP" + service.encode())
        return 1 if service in failing else 0

    monkeypatch.setattr(backup, "_pg_dump", fake_dump)


@pytest.mark.parametrize("failing", ["db", "teg-db"])
def test_a_failed_dump_fails_the_backup_and_leaves_no_archive(tmp_path, monkeypatch, failing):
    _dumps(monkeypatch, failing=(failing,))
    archive = tmp_path / "out" / "operator-backup.tar.gz"
    with pytest.raises(RuntimeError) as e:
        backup._do_backup(_ctx(tmp_path), Output("plain"), archive)
    assert "pg_dump" in str(e.value)
    assert not archive.exists() and not archive.with_name(archive.name + ".tmp").exists()


def test_a_complete_backup_is_one_0600_archive_with_both_dumps(tmp_path, monkeypatch):
    _dumps(monkeypatch)
    archive = tmp_path / "out" / "operator-backup.tar.gz"
    old = os.umask(0o022)
    try:
        res = backup._do_backup(_ctx(tmp_path), Output("plain"), archive)
    finally:
        os.umask(old)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert res["mode"] == "0600" and not archive.with_name(archive.name + ".tmp").exists()
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert {".env.operator", "registry.dump", "teg.dump", "MANIFEST.json"} <= names
