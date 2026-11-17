"""V0659 (b): the file drop source — stable ids, and a cursor that survives a restart.

⚠ The two properties are not the same, and the shipped harness only tests the first. `check_source(twice=True)`
collects a second pass with a FRESH FakeContext and requires the same record ids, which proves the ids are derived from
the input. It does NOT prove resumption: with fresh state a correct source yields everything again. The cursor is
tested here with a SHARED context across two source instances, which is what a restart looks like.
"""
from __future__ import annotations

import asyncio
import json
import os
import textwrap

import pytest

from theprotocol.proxy.sources import FileDropSource
from theprotocol.proxy.plugins import PluginError
from theprotocol.proxy.testing import FakeContext, check_resume, check_source

CSV = "id,name\n1,ada\n2,grace\n3,edsger\n"


def _drop(tmp_path, name: str, body: str):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _cfg(tmp_path, **kw):
    cfg = {"path": str(tmp_path), "format": "csv", "settle_seconds": 0}
    cfg.update(kw)
    return cfg


async def _collect(src):
    out = []
    await src.start()
    try:
        async for r in src.records():
            out.append(r)
            await src.committed(r)
    finally:
        await src.stop()
    return out


# --- the harness's own contract ------------------------------------------------------------------------------------
def test_it_passes_the_shipped_source_contract(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(check_source(FileDropSource, _cfg(tmp_path), limit=10))
    assert [r.record_id for r in got] == ["a.csv#0", "a.csv#1", "a.csv#2"]
    assert got[0].payload["data"] == {"id": "1", "name": "ada"}


# --- resumption, which check_source does not test -------------------------------------------------------------------
def test_a_restart_sends_no_row_twice_and_skips_none(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()                      # ONE context across both runs: this is what a restart looks like

    async def go():
        first = await _collect(FileDropSource(_cfg(tmp_path), ctx))
        second = await _collect(FileDropSource(_cfg(tmp_path), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert [r.record_id for r in first] == ["a.csv#0", "a.csv#1", "a.csv#2"]
    assert second == [], "a restart re-sent rows the cursor had already committed"


def test_a_restart_picks_up_rows_that_arrived_while_it_was_down(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()

    async def go():
        first = await _collect(FileDropSource(_cfg(tmp_path), ctx))
        _drop(tmp_path, "b.csv", "id,name\n4,barbara\n")
        _drop(tmp_path, "a.csv", CSV + "9,alan\n")          # the same file grew
        second = await _collect(FileDropSource(_cfg(tmp_path), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert len(first) == 3
    assert [r.record_id for r in second] == ["a.csv#3", "b.csv#0"], "a gap or a duplicate after the restart"


def test_a_partial_run_resumes_mid_file(tmp_path):
    """The cursor counts committed ROWS, so a run that stops after one row resumes at the second, not the file."""
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()

    async def go():
        src = FileDropSource(_cfg(tmp_path), ctx)
        await src.start()
        async for r in src.records():        # take one row and stop, as a crash would
            await src.committed(r)
            break
        await src.stop()
        return await _collect(FileDropSource(_cfg(tmp_path), ctx))

    rest = asyncio.run(go())
    assert [r.record_id for r in rest] == ["a.csv#1", "a.csv#2"]


# --- the canonical cursor check, now that (a) ships it -------------------------------------------------------------
def test_it_passes_the_shipped_resume_contract(tmp_path):
    """check_resume (V0659 (a), added after this source's own cases found the gap): two instances over one shared
    state, no record twice, none skipped, in order, against a full fresh read."""
    _drop(tmp_path, "a.csv", CSV)
    ids = asyncio.run(check_resume(FileDropSource, _cfg(tmp_path), first=2))
    assert ids == ["a.csv#0", "a.csv#1", "a.csv#2"], "check_resume returns both phases (before + after)"


# --- replay (Source.rewind) ----------------------------------------------------------------------------------------
def test_rewind_reads_a_named_file_again(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()

    async def go():
        await _collect(FileDropSource(_cfg(tmp_path), ctx))
        src = FileDropSource(_cfg(tmp_path), ctx)
        await src.start()
        await src.rewind("a.csv")
        return await _collect(FileDropSource(_cfg(tmp_path), ctx))

    assert [r.record_id for r in asyncio.run(go())] == ["a.csv#0", "a.csv#1", "a.csv#2"]


def test_rewind_to_a_row_reads_from_there(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()

    async def go():
        await _collect(FileDropSource(_cfg(tmp_path), ctx))
        src = FileDropSource(_cfg(tmp_path), ctx)
        await src.start()
        await src.rewind("a.csv#2")
        return await _collect(FileDropSource(_cfg(tmp_path), ctx))

    assert [r.record_id for r in asyncio.run(go())] == ["a.csv#2"]


def test_rewind_also_reads_the_files_after_it_again(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    _drop(tmp_path, "b.csv", "id,name\n4,barbara\n")
    ctx = FakeContext()

    async def go():
        await _collect(FileDropSource(_cfg(tmp_path), ctx))
        src = FileDropSource(_cfg(tmp_path), ctx)
        await src.start()
        await src.rewind("b.csv")
        return await _collect(FileDropSource(_cfg(tmp_path), ctx))

    assert [r.record_id for r in asyncio.run(go())] == ["b.csv#0"], "rewinding b must not replay a"


@pytest.mark.parametrize("bad", ["", "   ", "a.csv#x", "a.csv#-1", "nosuch.csv"])
def test_rewind_refuses_a_point_it_cannot_honour(tmp_path, bad):
    _drop(tmp_path, "a.csv", CSV)
    src = FileDropSource(_cfg(tmp_path), FakeContext())
    with pytest.raises(PluginError):
        asyncio.run(src.rewind(bad))


# --- the formats ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fmt,name,body,first", [
    ("json", "a.json", '[{"id": 1}, {"id": 2}]', {"id": 1}),
    ("jsonl", "a.jsonl", '{"id": 1}\n{"id": 2}\n', {"id": 1}),
    ("xml", "a.xml", '<rows><row id="1"><name>ada</name></row><row id="2"><name>grace</name></row></rows>',
     {"id": "1", "name": "ada"}),
])
def test_each_format_yields_its_rows(tmp_path, fmt, name, body, first):
    _drop(tmp_path, name, body)
    got = asyncio.run(check_source(FileDropSource, _cfg(tmp_path, format=fmt), limit=10))
    assert len(got) == 2 and got[0].payload["data"] == first


def test_an_object_with_one_list_inside_is_read_as_its_rows(tmp_path):
    _drop(tmp_path, "a.json", json.dumps({"exported_at": "x", "items": [{"id": 1}, {"id": 2}]}))
    got = asyncio.run(check_source(FileDropSource, _cfg(tmp_path, format="json"), limit=10))
    assert [r.payload["data"] for r in got] == [{"id": 1}, {"id": 2}]


# --- a drop is not atomic -------------------------------------------------------------------------------------------
def test_a_file_still_being_written_is_not_read(tmp_path):
    """Without the settle wait a 2 GB export is read mid-write and its tail is lost, which no cursor can repair."""
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(check_source(FileDropSource, _cfg(tmp_path, settle_seconds=3600), limit=10, twice=False))
    assert got == []


def test_a_marker_file_replaces_the_settle_wait(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    cfg = _cfg(tmp_path, settle_seconds=3600, require_marker=".done")
    assert asyncio.run(check_source(FileDropSource, cfg, limit=10, twice=False)) == []
    (tmp_path / "a.csv.done").write_text("", encoding="utf-8")
    got = asyncio.run(check_source(FileDropSource, cfg, limit=10))
    assert len(got) == 3
    assert all(".done" not in r.payload["file"] for r in got), "the marker itself must not be read as data"


# --- the awkward cases ----------------------------------------------------------------------------------------------
def test_an_unreadable_file_does_not_stop_the_rows_behind_it(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    _drop(tmp_path, "b.json", "{this is not json")
    cfg = _cfg(tmp_path, format="json")
    _drop(tmp_path, "c.json", '[{"id": 9}]')
    got = asyncio.run(check_source(FileDropSource, cfg, limit=10))
    assert [r.payload["data"] for r in got] == [{"id": 9}], "a bad file hid the file behind it"


def test_an_unreadable_file_does_not_advance_a_cursor_it_never_produced(tmp_path):
    _drop(tmp_path, "b.json", "{this is not json")
    ctx = FakeContext()
    asyncio.run(_collect(FileDropSource(_cfg(tmp_path, format="json"), ctx)))
    assert asyncio.run(ctx.state.get("filedrop.rows_done", {})) in ({}, None), \
        "a file that produced nothing must leave no cursor behind"


def test_the_legacy_systems_own_id_is_used_when_named(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(check_source(FileDropSource, _cfg(tmp_path, id_field="id"), limit=10))
    assert [r.record_id for r in got] == ["1", "2", "3"]


def test_the_suffix_filter_keeps_other_files_out(tmp_path):
    _drop(tmp_path, "a.csv", CSV)
    _drop(tmp_path, "notes.txt", "ignore me")
    got = asyncio.run(check_source(FileDropSource, _cfg(tmp_path, suffix=".csv"), limit=10))
    assert len(got) == 3


def test_an_unknown_format_is_refused_at_construction(tmp_path):
    with pytest.raises(ValueError, match="format"):
        FileDropSource(_cfg(tmp_path, format="yaml"), FakeContext())


# ═══ V0664 (Migrate a system, M2): poll_seconds ═════════════════════════════════════════════════════════════════════════════
#
# `poll_seconds: 0` lists the folder once, reads every settled file, then FINISHES (as sources/sftp.py does), so `tp-proxy run
# --once` ends. A positive number keeps listing the folder every that many seconds (a file dropped later is read too). With none
# the source behaves as it always has: one pass, then it finishes.

import asyncio as _asyncio


async def _drain(src, limit, timeout=3.0):
    got = []

    async def run():
        async for rec in src.records():
            got.append(rec)
            await src.committed(rec)
            if len(got) >= limit:
                return
    await _asyncio.wait_for(run(), timeout)
    return got


async def test_poll_seconds_zero_reads_what_is_there_and_finishes(tmp_path):
    from theprotocol.proxy.sources import FileDropSource
    from theprotocol.proxy.testing import FakeContext
    (tmp_path / "a.csv").write_text("id,v\n1,x\n2,y\n")
    (tmp_path / "b.csv").write_text("id,v\n3,z\n")
    src = FileDropSource({"path": str(tmp_path), "format": "csv", "settle_seconds": 0, "poll_seconds": 0}, FakeContext())
    await src.start()
    got = []

    async def run():
        async for rec in src.records():
            got.append(rec.record_id)
    await _asyncio.wait_for(run(), 3)                                     # it returns: the source finished
    assert got == ["a.csv#0", "a.csv#1", "b.csv#0"]


async def test_a_positive_poll_keeps_watching_and_reads_a_file_dropped_later(tmp_path):
    from theprotocol.proxy.sources import FileDropSource
    from theprotocol.proxy.testing import FakeContext
    (tmp_path / "a.csv").write_text("id,v\n1,x\n")
    src = FileDropSource({"path": str(tmp_path), "format": "csv", "settle_seconds": 0, "poll_seconds": 0.05}, FakeContext())
    await src.start()

    async def drop_later():
        await _asyncio.sleep(0.15)
        (tmp_path / "b.csv").write_text("id,v\n2,y\n3,z\n")
    task = _asyncio.ensure_future(drop_later())
    got = await _drain(src, 3)
    await task
    assert [r.record_id for r in got] == ["a.csv#0", "b.csv#0", "b.csv#1"]


async def test_a_row_appended_to_a_read_file_is_read_on_the_next_poll_and_none_twice(tmp_path):
    from theprotocol.proxy.sources import FileDropSource
    from theprotocol.proxy.testing import FakeContext
    f = tmp_path / "a.csv"
    f.write_text("id,v\n1,x\n")
    src = FileDropSource({"path": str(tmp_path), "format": "csv", "settle_seconds": 0, "poll_seconds": 0.05}, FakeContext())
    await src.start()

    async def append_later():
        await _asyncio.sleep(0.15)
        f.write_text("id,v\n1,x\n2,y\n")
    task = _asyncio.ensure_future(append_later())
    got = await _drain(src, 2)
    await task
    assert [r.record_id for r in got] == ["a.csv#0", "a.csv#1"]


async def test_with_no_poll_seconds_the_source_reads_once_and_finishes_as_it_always_did(tmp_path):
    from theprotocol.proxy.sources import FileDropSource
    from theprotocol.proxy.testing import FakeContext
    (tmp_path / "a.csv").write_text("id,v\n1,x\n")
    src = FileDropSource({"path": str(tmp_path), "format": "csv", "settle_seconds": 0}, FakeContext())
    await src.start()
    got = []

    async def run():
        async for rec in src.records():
            got.append(rec.record_id)
    await _asyncio.wait_for(run(), 3)
    assert got == ["a.csv#0"]


def test_poll_seconds_is_a_number_of_at_least_zero_in_the_schema():
    from jsonschema import ValidationError, validate
    from theprotocol.proxy.sources import FileDropSource
    validate({"path": "/d", "poll_seconds": 0}, FileDropSource.config_schema)
    validate({"path": "/d", "poll_seconds": 2.5}, FileDropSource.config_schema)
    with pytest.raises(ValidationError):
        validate({"path": "/d", "poll_seconds": -1}, FileDropSource.config_schema)


async def test_a_file_not_settled_yet_is_looked_at_again_on_the_next_pass_and_read_once_it_has(tmp_path):
    """A drop is not atomic: a file still being written is passed over (settle_seconds), and with poll_seconds the next pass reads it
    once it has stopped changing: not never (the source used to list the folder once and so lost it), and not twice."""
    import os
    import time
    from theprotocol.proxy.sources import FileDropSource
    from theprotocol.proxy.testing import FakeContext
    f = tmp_path / "late.csv"
    f.write_text("id,v\n1,x\n2,y\n")
    os.utime(f, None)                                                # modified just now: not settled for 0.4 s
    src = FileDropSource({"path": str(tmp_path), "format": "csv", "settle_seconds": 0.4, "poll_seconds": 0.05}, FakeContext())
    await src.start()
    t0 = time.time()
    got = await _drain(src, 2, timeout=5.0)
    assert time.time() - t0 >= 0.3                                   # it did wait: the first passes found nothing ready
    assert [r.record_id for r in got] == ["late.csv#0", "late.csv#1"]


async def test_without_poll_seconds_a_file_not_settled_yet_is_passed_over_and_the_source_finishes(tmp_path):
    """The old behaviour, kept for poll_seconds 0: one pass, an unsettled file is not read, the source ends (a --once run)."""
    from theprotocol.proxy.sources import FileDropSource
    from theprotocol.proxy.testing import FakeContext
    (tmp_path / "late.csv").write_text("id,v\n1,x\n")
    src = FileDropSource({"path": str(tmp_path), "format": "csv", "settle_seconds": 3600}, FakeContext())
    await src.start()
    got = []
    async for rec in src.records():
        got.append(rec)
    assert got == []
