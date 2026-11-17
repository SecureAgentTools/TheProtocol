"""V0666 (session-code, docs order gwo_625e48367c502d57578bb2e9; session-lead seq 4932 from the OPA backstop order
gwo_1a4154ea17186d81c42e4845 part 3, room seq 4924): the docs say that Rego invariants are PLANNED for every
security- and control-critical area, so that with OPA enforcing no governed code change could alter behaviour there, and
that today OPA runs in shadow. Never claimed as done.

The Code changes section of chapter 06 and the compliance chapter (19) carry the paragraph; each names the plan as planned,
says OPA runs in shadow today, and no sentence of it says OPA enforces now. The wording rules of the doc folder
(test_docs_public_wording.py) hold for the new words as for every other.
RED on 5e4893a8b: neither chapter carries the paragraph.
"""
from __future__ import annotations

import re
from pathlib import Path

DOCS = (Path(__file__).resolve().parent.parent / "src" / "agentvault_registry" / "static" / "new_registry_frontend" / "src"
        / "assets" / "docs" / "oracle")


def _paragraph(chapter: str) -> str:
    text = (DOCS / chapter).read_text(encoding="utf-8")
    hits = [p for p in re.split(r"\n\s*\n", text) if "OPA" in p and "backstop" in p.lower()]
    assert len(hits) == 1, f"{chapter}: want one OPA backstop paragraph, found {len(hits)}"
    return hits[0]


# V0666 after V0665's flip (session-lead room seq 5250): since 16 November 2026 the production frames and their operators run OPA in
# enforce. What that decides, read from the code: only the three permission checks keep OPA's answer (security.py: a request
# passes when Python AND OPA allow; an OPA that does not answer leaves the Python check alone deciding); the invariant sites
# evaluate their Rego and discard it. So the backstop stays planned, and no sentence may say production runs OPA in shadow.
TRUE_NOW = ("both the Python check and OPA allow", "the Python check alone decides", "not yet decisive")


def test_the_code_changes_chapter_names_the_opa_backstop_as_planned():
    p = _paragraph("06_governance.md")
    assert "planned" in p.lower() and all(t in p for t in TRUE_NOW), p
    assert "Rego" in p and "outside the paths a code change may touch" in p


def test_the_compliance_chapter_names_it_as_planned_too():
    p = _paragraph("19_compliance.md")
    assert "planned" in p.lower() and "Rego" in p and all(t in p for t in TRUE_NOW), p


def test_no_sentence_of_either_paragraph_claims_the_invariants_are_enforced():
    # what OPA enforces today is the permission checks; a sentence about enforcing names those, or reads as planned
    for chapter in ("06_governance.md", "19_compliance.md"):
        p = _paragraph(chapter)
        for sentence in re.split(r"(?<=[.!?])\s+", p):
            if re.search(r"\benforc", sentence, re.I):
                assert re.search(r"sign-in and permission checks|\bplanned\b|\bwould\b|\bonce\b|\bwith OPA enforcing\b|"
                                 r"\bnothing\b|\bnot\b|\bno\b", sentence, re.I), f"{chapter}: a sentence reads as done: {sentence!r}"
            if re.search(r"\binvariant", sentence, re.I):
                assert re.search(r"\bplanned\b|not yet decisive", sentence, re.I), f"{chapter}: {sentence!r}"


def test_no_page_says_production_runs_opa_in_shadow():
    gone = {"08_security.md": "The production frames and their cloud operators run it in shadow mode",
            "19_compliance.md": "OPA evaluates the same decisions in shadow on the production frames",
            "00_welcome.md": "policy decisions are also evaluated by OPA in shadow mode (it records, Python decides"}
    for chapter, old in gone.items():
        assert old not in (DOCS / chapter).read_text(encoding="utf-8"), chapter
    assert "OPA in shadow<br/>" not in (DOCS / "19_compliance.md").read_text(encoding="utf-8")
    assert "enforces the sign-in and permission checks" in (DOCS / "08_security.md").read_text(encoding="utf-8")


def test_the_code_changes_section_still_says_what_is_built():
    text = (DOCS / "06_governance.md").read_text(encoding="utf-8")
    sec = text.split("## Code Changes: Members Vote on the Code", 1)[1].split("\n## ", 1)[0]
    assert "This section says what is built." in sec
    assert sec.index("OPA") > sec.index("**The limits of this release.**")      # the plan sits with the limits, not the flow


def test_the_limits_name_the_policy_backstop_as_forbidden_and_the_card_rule():
    """OPA phase 2 step 1 (gwo_fb0b8c005e61af124e579601, item 3): the backstop's files are forbidden by name, and a Rego policy
    changes only on a card of the platform maintainer, never through governed code (services/code_changes._BACKSTOP)."""
    text = (DOCS / "06_governance.md").read_text(encoding="utf-8")
    sec = text.split("**The limits of this release.**", 1)[1].split("\n## ", 1)[0]
    bullet = next(b for b in sec.split("\n- ") if b.startswith("**Never the policy backstop.**"))
    for word in ("identity-fabric/", ".rego", "opa_shadow", "security.py", "middleware", "the policy backstop",
                 "approval card", "never through a code change"):
        assert word in bullet, word
    assert "whatever the open set says" in bullet
