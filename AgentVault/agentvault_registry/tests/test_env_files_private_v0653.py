"""V0653 (am), item 10 (the hardening list in the sessions' room): a frame's and an operator's env file is private from
its first byte.

frame_test_provisioner._render_template wrote every rendered file through the process's umask, the frame's .env.frame-test
(its database passwords, signing keys and internal keys) included, and cloud_provisioner._generate_env_file the same for a
minimal .env.operator. Both are created 0600 now, and a file that already exists with a wider mode is narrowed before
anything is written. Other rendered files keep their mode. BASE (a5ef48ddd, V0652): the env files come out 0644 under a
022 umask, and a re-render keeps a wider old mode.
"""
from __future__ import annotations

import os
import stat

import pytest

from agentvault_registry.services import cloud_provisioner as cp
from agentvault_registry.services import frame_test_provisioner as ftp


@pytest.fixture()
def umask022():
    old = os.umask(0o022)
    yield
    os.umask(old)


def mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_the_frame_env_file_is_rendered_0600(tmp_path, umask022):
    tmpl = tmp_path / "frame-test.env.tmpl"
    tmpl.write_text("FT_PG_PASS={{PG}}\n")
    out = tmp_path / ".env.frame-test"
    ftp._render_template(str(tmpl), str(out), {"PG": "s3cret-value"})
    assert out.read_text() == "FT_PG_PASS=s3cret-value\n" and mode(out) == 0o600


def test_a_re_render_narrows_a_wider_existing_env_file(tmp_path, umask022):
    tmpl = tmp_path / "frame-test.env.tmpl"
    tmpl.write_text("FT_PG_PASS={{PG}}\n")
    out = tmp_path / ".env.frame-test"
    out.write_text("old\n")
    os.chmod(out, 0o644)
    ftp._render_template(str(tmpl), str(out), {"PG": "new"})
    assert out.read_text() == "FT_PG_PASS=new\n" and mode(out) == 0o600


def test_control_other_rendered_files_keep_their_mode(tmp_path, umask022):
    tmpl = tmp_path / "server.conf.tmpl"
    tmpl.write_text("x={{X}}\n")
    out = tmp_path / "server.conf"
    ftp._render_template(str(tmpl), str(out), {"X": "1"})
    assert mode(out) == 0o644


def test_the_operator_env_file_is_generated_0600(tmp_path, umask022):
    out = tmp_path / ".env.operator"
    cp._generate_env_file(str(out), "testop")
    assert mode(out) == 0o600 and "REGISTRY_NAME=cloud-op-testop" in out.read_text()
