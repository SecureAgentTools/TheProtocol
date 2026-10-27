"""§MTLSHOPS (a) (2026-09-15, agentvault2-b5; agentvault2-85's rollback order): before a host auditor image from before
mtlshops/aud-public starts again, every slot without a key leaves its frames file, and a file that still holds one refuses.

That older image fills a keyless slot's key with its mode key and sends the host's key to the slot's URL; a public_only or
public_read slot names a URL the frame serves. Red on master's sidecars (the helpers are absent).
"""
import json
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidecars  # noqa: E402

FRAMES = [
    {"id": "eu", "mode": "prod", "url": "http://eu-event-store:8200", "key": "k-eu", "dsn": "postgresql://u:p@eu-es-db:5432/e"},
    {"id": "t3", "mode": "prod", "url": "https://t3-es.example.test", "public_only": True},
    {"id": "t2", "mode": "prod", "url": "https://t2-es.example.test", "public_read": True, "dsn": "postgresql://u:p@t2-es-db:5432/e"},
    {"id": "lantern", "mode": "sandbox", "url": "http://lantern-event-store:8200", "key": "k-lantern"},
]


def _file(tmp_path, frames=FRAMES):
    p = tmp_path / "frames.json"
    p.write_text(json.dumps(frames))
    return str(p)


def test_the_keyless_slots_are_named_by_id(tmp_path):
    assert sidecars.keyless_extra_slots(_file(tmp_path)) == ["t3", "t2"]


def test_strip_removes_only_the_keyless_slots_and_leaves_the_file_safe(tmp_path):
    f = _file(tmp_path)
    lines = []
    assert sidecars.strip_keyless_extra_slots(f, log=lines.append) == ["t3", "t2"]
    assert [x["id"] for x in json.load(open(f))] == ["eu", "lantern"]
    assert sidecars.keyless_extra_slots(f) == []
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert lines and "t3, t2" in lines[0] and "k-eu" not in lines[0]


def test_a_missing_file_holds_nothing_and_an_unreadable_one_refuses(tmp_path):
    assert sidecars.keyless_extra_slots(str(tmp_path / "missing.json")) == []
    bad = tmp_path / "frames.json"
    bad.write_text("{not json")
    assert sidecars.keyless_extra_slots(str(bad)) == ["<unreadable frames file>"]
    with pytest.raises(ValueError):
        sidecars.strip_keyless_extra_slots(str(bad))
