"""§OPDIST — the solo auditor's frames.json: the frame's OWN currency, and a mode that matches what it holds.

Two defects agentvault2-6a measured on lantern, both in the writer rather than the file:
  · currency read AVT while the frame's rendered env carries LNT and its card says LNT. The env TEXT this function
    parses is the one that exists at that point in the standup, and the frame's ticker reaches those keys later, so
    a TEMPLATE DEFAULT was published as the frame's currency. The auditor keys `fx_reserve_floor` on it, which
    makes it a claim rather than a label — §LOCTRUTH, in a third place;
  · the file was written 0644 while holding three read-only database passwords, and the function's own docstring
    said 600. The auditor reads it as uid 0, so 0600 costs it nothing.

Parsed rather than run: the writer is one branch of a standup against a live host.
"""
from __future__ import annotations

import ast
import pathlib

_DRIVER = pathlib.Path(__file__).resolve().parents[1] / "standup_driver.py"


def _writer_source() -> str:
    tree = ast.parse(_DRIVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = ast.get_source_segment(_DRIVER.read_text(encoding="utf-8"), node) or ""
            if "frames.json" in src and "auditor" in src:
                return src
    raise AssertionError("no function writes the kit auditor's frames.json")


def test_the_currency_comes_from_the_ticker_the_standup_was_given():
    src = _writer_source()
    line = next(l for l in src.splitlines() if '"currency"' in l)
    assert "args" in line and "ticker" in line, f"the ticker must be the authority: {line.strip()}"
    # the env keys stay as a fallback, and nothing is defaulted to a currency
    assert "FRAME_CURRENCY" in src
    assert '"AVT"' not in src and "'AVT'" not in src, "no currency literal may appear in this writer"


def test_the_frames_file_is_written_0600_because_it_holds_passwords():
    src = _writer_source()
    assert "os.chmod(path, 0o600)" in src, "the file holds three read-only database passwords"
    assert "os.chmod(path, 0o644)" not in src
    assert "auditor_ro:" in src, "if this stops holding a credential, re-read the mode decision"
