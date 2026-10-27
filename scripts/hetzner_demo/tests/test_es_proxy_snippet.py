"""§SOVKIT T2/T5 (2026-09-14) — the event store's proxy marker on the HOST terminator lives in its own 600 snippet.

agentvault2-85's live flips write /etc/nginx/snippets/es-proxy-auth-<frame>.conf and the public <frame>-es vhost only
includes it, so the secret never sits in a vhost file (those are copied into /etc/nginx/vhost-backups/ and diffed
around). The driver writes the same shape for a new frame before it renders the vhost; teardown removes it.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import standup_extras as extras  # noqa: E402

GOOD = "a" * 64


def test_the_snippet_is_one_line_at_mode_600(tmp_path):
    p = extras.write_es_proxy_snippet("plum", GOOD, root=str(tmp_path))
    assert p == str(tmp_path / "es-proxy-auth-plum.conf")
    assert open(p).read() == f'proxy_set_header X-ES-Proxy-Auth "{GOOD}";\n'
    assert (os.stat(p).st_mode & 0o777) == 0o600


def test_a_rewrite_with_the_same_content_keeps_the_file_and_a_new_secret_replaces_it(tmp_path):
    p = extras.write_es_proxy_snippet("plum", GOOD, root=str(tmp_path))
    ino = os.stat(p).st_ino
    assert extras.write_es_proxy_snippet("plum", GOOD, root=str(tmp_path)) == p and os.stat(p).st_ino == ino
    other = "b" * 40
    extras.write_es_proxy_snippet("plum", other, root=str(tmp_path))
    assert other in open(p).read() and GOOD not in open(p).read()
    assert (os.stat(p).st_mode & 0o777) == 0o600


def test_a_loosened_mode_is_tightened_on_the_next_write(tmp_path):
    p = extras.write_es_proxy_snippet("plum", GOOD, root=str(tmp_path))
    os.chmod(p, 0o644)
    extras.write_es_proxy_snippet("plum", GOOD, root=str(tmp_path))
    assert (os.stat(p).st_mode & 0o777) == 0o600


@pytest.mark.parametrize("bad", ["", "short", "x" * 31, "a" * 40 + " ", "a" * 40 + '"', None])
def test_a_secret_of_the_wrong_shape_is_refused_and_never_written(tmp_path, bad):
    with pytest.raises(ValueError) as e:
        extras.write_es_proxy_snippet("plum", bad, root=str(tmp_path))
    assert "not printed" in str(e.value) and (bad or "") not in str(e.value).replace("ES_PROXY_TRUST_SECRET", "") or bad in (None, "")
    assert not (tmp_path / "es-proxy-auth-plum.conf").exists()


def test_teardown_removes_it_and_says_whether_it_was_there(tmp_path):
    assert extras.remove_es_proxy_snippet("plum", root=str(tmp_path)) is False
    extras.write_es_proxy_snippet("plum", GOOD, root=str(tmp_path))
    assert extras.remove_es_proxy_snippet("plum", root=str(tmp_path)) is True
    assert not (tmp_path / "es-proxy-auth-plum.conf").exists()


def test_the_es_vhost_template_includes_the_snippet_and_blanks_the_weaker_credentials():
    t = (pathlib.Path(__file__).resolve().parents[3] / "templates" / "frame-test" / "vhosts" / "es.conf.tmpl").read_text()
    assert "include /etc/nginx/snippets/es-proxy-auth-{{NAME}}.conf;" in t
    assert 'proxy_set_header X-Internal-Key       "";' in t and 'proxy_set_header X-Federation-License "";' in t
    assert "X-ES-Proxy-Auth" not in t, "the marker value must never be rendered into the vhost itself"
