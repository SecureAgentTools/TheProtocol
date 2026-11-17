"""V0667 the developer passport (order gwo_fb84e57318de0802725ab511): the Code changes section of chapter 06 says how a developer of
another registry takes part on the governing one, in prose (no example: none has run on a sandbox yet, and the docs rule is that a
page's examples are run before they are written). Pinned: the press and that it is never automatic, what the card carries and never
carries, that votes stay with the governing registry's members, that standing follows home (the code host account too), the routes.
RED: the section says nothing of the passport.
"""
from __future__ import annotations

import re
from pathlib import Path

CHAPTER = (Path(__file__).resolve().parent.parent / "src" / "agentvault_registry" / "static" / "new_registry_frontend" / "src"
           / "assets" / "docs" / "oracle" / "06_governance.md")


def _passport() -> str:
    text = CHAPTER.read_text(encoding="utf-8")
    m = re.search(r"\n## Code Changes: Members Vote on the Code\n(.*?)(?=\n## )", text, re.S)
    assert m
    hits = [p for p in re.split(r"\n\s*\n", m.group(1)) if "Taking part from another registry" in p]
    assert len(hits) == 1, f"want one passport paragraph, found {len(hits)}"
    return hits[0]


def test_the_passport_paragraph_says_what_happens_and_what_does_not():
    p = _passport()
    for words in ("Take part on", "never automatic", "public name", "never the e-mail address", "votes stay with",
                  "suspends or deletes", "code host account", "/api/v1/code-passport/changes", "/api/v1/developers/me/code-passport",
                  "five minutes"):
        assert words in p, words
