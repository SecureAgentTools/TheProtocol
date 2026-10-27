"""§SECFIX (2026-09-26) — a re-provision replaces the operator's Redis ACL instead of opening it.

`write_redis_acl` wrote the file in place and then chowned it to Redis's uid (999). The writer is uid 1000 (the
registry, or the runner's one-shot), so the NEXT write, a re-provision after a failed attempt, could not open the file
it had given away. Measured on the test frame secfixt with V0452: a re-provision of `secfixop` after an earlier failed
attempt failed with "PermissionError: [Errno 13] Permission denied: '.../cloud-op-secfixop/redis-users.acl'" (the file
owned by 999, mode 0600, in a directory owned by 1000). host_work's own docstring had named this retry class on
2026-09-16 (beacon) without closing it.

The fix renames a fresh file over the old one: a rename needs write permission on the DIRECTORY, not on the file.

The suite runs as root, which bypasses file permissions, so the unopenable file is simulated where it matters: an
`os.open` of the final path for writing raises PermissionError, as it does for uid 1000 against a 999-owned 0600 file.
RED control: OPDIST_SRC pointing at the pre-fix services/ fails the first three tests (the old code opens the final path
and never renames, so a failed rename cannot even happen there); measured against the V0452 image: 3 failed, 1 passed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry" / "services")


def _load():
    rel = "operator_provisioner.py"
    path = (_SRC / rel) if (_SRC / rel).exists() else (_SRC / "services" / rel)
    spec = importlib.util.spec_from_file_location("_secfix_acl_operator_provisioner", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def opprov():
    return _load()


def _values(opprov):
    return opprov.generate_operator_secrets()


def _refuse_opening(monkeypatch, final_path):
    """uid 1000 against a 999-owned 0600 file: opening it for writing raises; anything else behaves as usual."""
    real_open = os.open

    def guarded(path, flags, *args, **kwargs):
        if os.fspath(path) == os.fspath(final_path) and flags & (os.O_WRONLY | os.O_RDWR):
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)


def test_a_retry_replaces_an_acl_it_cannot_open(opprov, tmp_path, monkeypatch):
    first, second = _values(opprov), _values(opprov)
    acl = tmp_path / "redis-users.acl"
    opprov.write_redis_acl(str(tmp_path), first, "fixture")
    ino = os.stat(acl).st_ino
    _refuse_opening(monkeypatch, acl)
    opprov.write_redis_acl(str(tmp_path), second, "fixture")   # the old code raised PermissionError here
    text = acl.read_text()
    assert hashlib.sha256(second["REDIS_PASSWORD_REGISTRY"].encode()).hexdigest() in text
    assert hashlib.sha256(first["REDIS_PASSWORD_REGISTRY"].encode()).hexdigest() not in text
    assert os.stat(acl).st_ino != ino, "replaced by a rename, not rewritten in place"
    assert oct(os.stat(acl).st_mode & 0o777) == "0o600"


def test_no_write_opens_the_final_path(opprov, tmp_path, monkeypatch):
    """Even the FIRST write goes through a temporary file, so there is one code path and it is the one that retries."""
    _refuse_opening(monkeypatch, tmp_path / "redis-users.acl")
    opprov.write_redis_acl(str(tmp_path), _values(opprov), "fixture")
    assert (tmp_path / "redis-users.acl").exists()


def test_a_failed_rename_leaves_no_temporary_file(opprov, tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        opprov.write_redis_acl(str(tmp_path), _values(opprov), "fixture")
    assert sorted(p.name for p in tmp_path.iterdir()) == [], "the temporary file is removed when the rename fails"


def test_the_file_still_carries_hashes_only(opprov, tmp_path):
    v = _values(opprov)
    opprov.write_redis_acl(str(tmp_path), v, "fixture")
    text = (tmp_path / "redis-users.acl").read_text()
    assert not any(value in text for value in v.values()), "the ACL file carries hashes, never passwords"
    assert [p.name for p in tmp_path.iterdir()] == ["redis-users.acl"]
