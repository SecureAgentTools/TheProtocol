"""V0659 (b): the log tail source — an offset cursor that survives rotation, and no partial line.

The two cases worth the file. An offset ALONE is wrong the moment the log rotates: app.log becomes app.log.1 and a new
app.log starts at zero, so an offset of 40,000 into the new file skips its first 40,000 bytes. That is a silent gap, and
nobody sees it but the records that never arrive. The cursor therefore keeps the file's inode and size too, and a file
whose inode changed, or that is shorter than the cursor, is read from its start.

And a partial last line is not a record: emitting "2026-11-07 ERRO" would create a record that never existed, with an
id that can never match the complete line.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from theprotocol.proxy.plugins import PluginError
from theprotocol.proxy.sources import LogTailSource
from theprotocol.proxy.testing import FakeContext, check_resume, check_source

LINES = "one\ntwo\nthree\n"


def _log(tmp_path, body: str, name: str = "app.log"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _cfg(tmp_path, **kw):
    cfg = {"path": str(tmp_path / "app.log")}
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


def _lines(records):
    return [r.payload.get("line") for r in records]


# --- the shipped contracts -----------------------------------------------------------------------------------------
def test_it_passes_the_shipped_source_contract(tmp_path):
    _log(tmp_path, LINES)
    got = asyncio.run(check_source(LogTailSource, _cfg(tmp_path), limit=10))
    assert _lines(got) == ["one", "two", "three"]


def test_it_passes_the_shipped_resume_contract(tmp_path):
    _log(tmp_path, LINES)
    ids = asyncio.run(check_resume(LogTailSource, _cfg(tmp_path), first=2))
    assert len(ids) == 3 and len(set(ids)) == 3


# --- rotation: the case an offset alone gets wrong ------------------------------------------------------------------
def test_a_rotated_log_is_read_from_its_start_and_nothing_is_skipped(tmp_path):
    p = _log(tmp_path, LINES)
    ctx = FakeContext()

    async def go():
        first = await _collect(LogTailSource(_cfg(tmp_path), ctx))
        os.replace(str(p), str(tmp_path / "app.log.1"))      # rotate
        _log(tmp_path, "four\nfive\n")                        # a NEW file, starting at zero
        second = await _collect(LogTailSource(_cfg(tmp_path), ctx))
        return first, second

    first, second = asyncio.run(go())
    assert _lines(first) == ["one", "two", "three"]
    assert _lines(second) == ["four", "five"], "the new file's start was skipped: an offset-only cursor's silent gap"


def test_a_log_truncated_in_place_is_read_from_its_start(tmp_path):
    """`: > app.log` keeps the inode and resets the size; the cursor must notice the file got SHORTER."""
    _log(tmp_path, LINES)
    ctx = FakeContext()

    async def go():
        await _collect(LogTailSource(_cfg(tmp_path), ctx))
        _log(tmp_path, "fresh\n")                             # same inode on most filesystems, smaller
        return await _collect(LogTailSource(_cfg(tmp_path), ctx))

    assert _lines(asyncio.run(go())) == ["fresh"]


def test_appended_lines_after_a_restart_are_read_once(tmp_path):
    _log(tmp_path, LINES)
    ctx = FakeContext()

    async def go():
        await _collect(LogTailSource(_cfg(tmp_path), ctx))
        with open(tmp_path / "app.log", "a", encoding="utf-8") as fh:
            fh.write("four\n")
        return await _collect(LogTailSource(_cfg(tmp_path), ctx))

    assert _lines(asyncio.run(go())) == ["four"]


# --- a partial line is not a record ---------------------------------------------------------------------------------
def test_a_line_without_its_newline_is_not_a_record_yet(tmp_path):
    _log(tmp_path, "one\ntwo\npartial-no-newline")
    got = asyncio.run(check_source(LogTailSource, _cfg(tmp_path), limit=10))
    assert _lines(got) == ["one", "two"]


def test_the_partial_line_arrives_once_it_is_finished(tmp_path):
    _log(tmp_path, "one\npart")
    ctx = FakeContext()

    async def go():
        first = await _collect(LogTailSource(_cfg(tmp_path), ctx))
        _log(tmp_path, "one\npartial-now-complete\n")
        return first, await _collect(LogTailSource(_cfg(tmp_path), ctx))

    first, second = asyncio.run(go())
    assert _lines(first) == ["one"] and _lines(second) == ["partial-now-complete"]


# --- entries, fields and filtering ----------------------------------------------------------------------------------
def test_a_continuation_line_joins_the_entry_above_it(tmp_path):
    _log(tmp_path, "ERROR boom\n    at Foo.bar(Foo.java:1)\n    at Baz.qux(Baz.java:2)\nINFO fine\n")
    got = asyncio.run(check_source(LogTailSource, _cfg(tmp_path, continuation=r"^\s+at "), limit=10))
    assert len(got) == 2, "a stack trace belongs to the line that started it"
    assert got[0].payload["line"].count("\n") == 2 and got[1].payload["line"] == "INFO fine"


def test_a_pattern_with_named_groups_becomes_the_fields(tmp_path):
    _log(tmp_path, "2026-11-07 ERROR boom\n")
    cfg = _cfg(tmp_path, pattern=r"^(?P<day>\S+) (?P<level>\w+) (?P<message>.*)$")
    got = asyncio.run(check_source(LogTailSource, cfg, limit=10))
    assert got[0].payload["level"] == "ERROR" and got[0].payload["message"] == "boom"


def test_an_unmatched_line_is_carried_whole_unless_asked_to_drop_it(tmp_path):
    """The unmatched line is ONE word: "not in the format at all" parses as day=not level=in message=the rest, so a
    fixture meant to be unparseable has to be one the pattern genuinely cannot read."""
    _log(tmp_path, "2026-11-07 ERROR boom\ngarbage\n")
    cfg = _cfg(tmp_path, pattern=r"^(?P<day>\S+) (?P<level>\w+) (?P<message>.*)$")
    kept = asyncio.run(check_source(LogTailSource, cfg, limit=10))
    assert len(kept) == 2 and kept[1].payload["line"] == "garbage"
    assert "level" not in kept[1].payload, "it was parsed after all: the fixture is not the unmatched case"
    dropped = asyncio.run(check_source(LogTailSource, {**cfg, "skip_unmatched": True}, limit=10))
    assert [r.payload["line"] for r in dropped] == ["2026-11-07 ERROR boom"]


def test_a_pattern_without_named_groups_is_refused(tmp_path):
    with pytest.raises(PluginError, match="named groups"):
        LogTailSource(_cfg(tmp_path, pattern=r"^\w+"), FakeContext())


def test_from_start_false_takes_only_what_arrives_next(tmp_path):
    _log(tmp_path, LINES)
    ctx = FakeContext()

    async def go():
        first = await _collect(LogTailSource(_cfg(tmp_path, from_start=False), ctx))
        with open(tmp_path / "app.log", "a", encoding="utf-8") as fh:
            fh.write("after\n")
        return first, await _collect(LogTailSource(_cfg(tmp_path, from_start=False), ctx))

    first, second = asyncio.run(go())
    assert first == [] and _lines(second) == ["after"]


def test_a_log_that_is_not_there_yet_says_so_and_yields_nothing(tmp_path):
    got = asyncio.run(check_source(LogTailSource, _cfg(tmp_path), limit=10, twice=False))
    assert got == []


# --- replay ---------------------------------------------------------------------------------------------------------
def test_rewind_to_start_reads_the_whole_file_again(tmp_path):
    _log(tmp_path, LINES)
    ctx = FakeContext()

    async def go():
        await _collect(LogTailSource(_cfg(tmp_path), ctx))
        src = LogTailSource(_cfg(tmp_path), ctx)
        await src.start()
        await src.rewind("start")
        return await _collect(LogTailSource(_cfg(tmp_path), ctx))

    assert _lines(asyncio.run(go())) == ["one", "two", "three"]


def test_rewind_to_an_offset_reads_from_there(tmp_path):
    _log(tmp_path, LINES)
    ctx = FakeContext()

    async def go():
        await _collect(LogTailSource(_cfg(tmp_path), ctx))
        src = LogTailSource(_cfg(tmp_path), ctx)
        await src.start()
        await src.rewind("4")                                 # just past "one\n"
        return await _collect(LogTailSource(_cfg(tmp_path), ctx))

    assert _lines(asyncio.run(go())) == ["two", "three"]


@pytest.mark.parametrize("bad", ["nonsense", "-1", "99999"])
def test_rewind_refuses_a_point_it_cannot_honour(tmp_path, bad):
    _log(tmp_path, LINES)
    src = LogTailSource(_cfg(tmp_path), FakeContext())
    with pytest.raises(PluginError):
        asyncio.run(src.rewind(bad))


def test_a_parsed_record_still_carries_the_line_it_was_parsed_from(tmp_path):
    _log(tmp_path, "2026-11-07 ERROR boom\n")
    cfg = _cfg(tmp_path, pattern=r"^(?P<day>\S+) (?P<level>\w+) (?P<message>.*)$")
    got = asyncio.run(check_source(LogTailSource, cfg, limit=10))
    assert got[0].payload["line"] == "2026-11-07 ERROR boom"


def test_a_group_named_line_wins_over_the_raw_text(tmp_path):
    """The pattern's author asked for that name, so the group's value is what a consumer gets."""
    _log(tmp_path, "2026-11-07 ERROR boom\n")
    cfg = _cfg(tmp_path, pattern=r"^\S+ \w+ (?P<line>.*)$")
    got = asyncio.run(check_source(LogTailSource, cfg, limit=10))
    assert got[0].payload["line"] == "boom"
