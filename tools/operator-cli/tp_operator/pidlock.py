"""PID lock — per-operator mutex for mutation commands.

Per Operator_CLI_Strategy.md §4.8. Concurrent mutation invocations against the
same operator are blocked; read commands are concurrency-safe and don't lock.

Uses fcntl LOCK_EX | LOCK_NB on a per-operator lockfile under either
/var/lock/ (preferred) or ~/.tp-operator/locks/ (fallback).
"""
from __future__ import annotations

import contextlib
import datetime
import errno
import fcntl
import os
from pathlib import Path
from typing import Iterator


class LockAcquireError(RuntimeError):
    pass


def _lock_dir() -> Path:
    for d in (Path("/var/lock"), Path.home() / ".tp-operator" / "locks"):
        try:
            d.mkdir(parents=True, exist_ok=True)
            test = d / ".write-test"
            test.write_text("")
            test.unlink()
            return d
        except (OSError, PermissionError):
            continue
    fallback = Path("/tmp") / "tp-operator-locks"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


@contextlib.contextmanager
def acquire_lock(operator_name: str) -> Iterator[Path]:
    """Acquire an exclusive lock on /var/lock/tp-operator-<name>.lock.

    Raises LockAcquireError on conflict (with PID of the existing holder).
    Released on context exit.
    """
    lock_path = _lock_dir() / f"tp-operator-{operator_name}.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EACCES):
                try:
                    other_pid = open(lock_path).read().strip()
                except OSError:
                    other_pid = "(unknown)"
                raise LockAcquireError(
                    f"Lock held by PID {other_pid} on {lock_path}; "
                    f"another tp-operator instance is mutating {operator_name}."
                )
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n{datetime.datetime.now(datetime.timezone.utc).isoformat()}\n".encode())
        os.fsync(fd)
        yield lock_path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
