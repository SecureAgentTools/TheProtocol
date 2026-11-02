"""V0653 (am), item 4 (the hardening list in the sessions' room): the first-boot admin password goes to a 0600 file, the log
names the file, never the password; and the file is written before the account exists, so a failed write leaves none.

prod_seed.seed() with the module's own engine and session replaced by a small fake (no aiosqlite in the image): it reports
"no account yet", records what is added. BASE (a5ef48ddd, V0652): the password is printed to stdout, the container's log,
and no file is written.
"""
from __future__ import annotations

import os
import stat

import pytest

from agentvault_registry import prod_seed as ps


class _Result:
    def scalar_one_or_none(self):
        return None


class _Session:
    def __init__(self, added):
        self.added = added

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _Result()

    def add(self, obj):
        obj.id = 7
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


class _Engine:
    async def dispose(self):
        pass


@pytest.fixture()
def rig(monkeypatch):
    added = []
    monkeypatch.setattr(ps, "create_async_engine", lambda *a, **k: _Engine())
    monkeypatch.setattr(ps, "sessionmaker", lambda *a, **k: (lambda: _Session(added)))
    monkeypatch.delenv("FIRST_ADMIN_PASSWORD", raising=False)
    return added


async def test_the_generated_password_is_in_a_0600_file_and_never_in_the_output(rig, tmp_path, monkeypatch, capsys, caplog):
    target = tmp_path / "data" / "first-boot-admin-password"
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD_FILE", str(target))
    await ps.seed()
    assert len(rig) == 1
    password = target.read_text().strip()
    assert len(password) >= 20
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    out = capsys.readouterr().out + caplog.text
    assert password not in out
    assert str(target) in out


async def test_a_password_that_cannot_be_written_leaves_no_account(rig, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD_FILE", str(blocker / "first-boot-admin-password"))
    with pytest.raises(OSError):
        await ps.seed()
    assert rig == []


async def test_control_a_password_from_the_environment_writes_no_file_and_prints_nothing(rig, tmp_path, monkeypatch, capsys):
    target = tmp_path / "first-boot-admin-password"
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "env-given-password-0123456789")
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD_FILE", str(target))
    await ps.seed()
    assert len(rig) == 1 and not target.exists()
    assert "env-given-password" not in capsys.readouterr().out
