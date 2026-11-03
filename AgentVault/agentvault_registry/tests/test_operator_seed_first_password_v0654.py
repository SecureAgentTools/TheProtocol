"""V0654 (aq), CodeQL #381 (session-lead, the sessions' room seq 1110): operator_seed printed a randomly generated first-boot
admin password in its banner, which is the container's log, the thing V0653 (am) item 4 fixed in prod_seed. It goes the
same way now: into a 0600 file (prod_seed.write_first_password) before the account exists, the banner names the file.

operator_seed.seed() with its engine, session and account write replaced by small fakes. BASE (V0653, f8f1993fb): the
password is printed and no file is written.
"""
from __future__ import annotations

import os
import stat

import pytest

from agentvault_registry import operator_seed as os_


class _Result:
    def scalar_one_or_none(self):
        return None


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _Result()


class _Engine:
    async def dispose(self):
        pass


@pytest.fixture()
def rig(monkeypatch):
    created = []

    async def _create(db, admin, accepted):
        admin.id = 1
        created.append(admin)

    monkeypatch.setattr(os_, "create_async_engine", lambda *a, **k: _Engine())
    monkeypatch.setattr(os_, "sessionmaker", lambda *a, **k: (lambda: _Session()))
    monkeypatch.setattr(os_, "create_admin", _create)
    for name in ("FIRST_ADMIN_PASSWORD", "FIRST_ADMIN_EMAIL", "FIRST_ADMIN_ACCEPTED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REGISTRY_NAME", "seed-test")
    return created


async def test_no_first_admin_password_the_generated_one_is_in_a_0600_file_and_in_no_output(rig, tmp_path, monkeypatch,
                                                                                               capsys, caplog):
    target = tmp_path / "data" / "first-boot-admin-password"
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD_FILE", str(target))
    await os_.seed()
    assert len(rig) == 1
    password = target.read_text().strip()
    assert len(password) >= 20
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    out = capsys.readouterr()
    shown = out.out + out.err + caplog.text
    assert password not in shown
    assert str(target) in shown


async def test_a_password_that_cannot_be_written_leaves_no_account(rig, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD_FILE", str(blocker / "first-boot-admin-password"))
    with pytest.raises(OSError):
        await os_.seed()
    assert rig == []


async def test_control_a_password_from_the_environment_writes_no_file_and_prints_nothing(rig, tmp_path, monkeypatch, capsys):
    target = tmp_path / "first-boot-admin-password"
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "env-given-password-0123456789")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD_FILE", str(target))
    await os_.seed()
    assert len(rig) == 1 and not target.exists()
    assert "env-given-password" not in capsys.readouterr().out
