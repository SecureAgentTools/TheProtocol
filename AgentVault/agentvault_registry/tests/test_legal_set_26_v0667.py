"""V0667 legal set 2.6: the public code host's paragraphs (order gwo_662c03447bcd627afa4a11e5; the draft
sessionlogs2026/DRAFT_2026-11-16_LEGAL_CODE_HOST.md; session-lead room seq 5175 and 5178). Terms § 10.2 decides the dates: a material
change binds existing members 30 days after publication, and whoever presses "Link repository account" accepts the new Terms at the
press. The texts go live only on his V0667 card, which quotes the new paragraphs.

  - the versions: the set 2.6, the Terms 2.5, the Privacy Policy and the Software License Notice 2.4, the same in the console and
    the registry (the console shows its numbers, the acceptance record stores the registry's)
  - ONE pair of dates, in step in both places: published, and effective 30 days later (the V0667 cut sets the publication day)
  - the paragraphs: Terms 5.12 (a) to (g), Privacy 3.8, 4.9, a retention line in 4.8 and a sentence in 5.1, the licence's § 6, the
    change log's entry; the German set carries the same subsections (its own spec refuses any structural drift)
RED: the set is 2.5 and none of the paragraphs exists.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re

from agentvault_registry.core import legal_versions as lv

_REG = pathlib.Path(__file__).resolve().parents[1]
_LEGAL = _REG / "src/agentvault_registry/static/new_registry_frontend/src/content/legal"
if not _LEGAL.is_dir():                     # the image layout
    _LEGAL = pathlib.Path("/app/src/agentvault_registry/static/new_registry_frontend/src/content/legal")
EN, DE = (_LEGAL / "suiteV2.ts").read_text(), (_LEGAL / "suiteV2.de.ts").read_text()
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _page(text: str, page: str) -> str:
    m = re.search(rf"(?m)^  {page}: \{{\n(.*?)(?=^  [a-zA-Z]+: \{{\n|\Z)", text, re.S)
    assert m, page
    return m.group(1)


def _const(text: str, name: str) -> str:
    m = re.search(rf"(?m)^(?:export )?const {name} = '([^']+)'", text)
    assert m, name
    return m.group(1)


def _sub(page: str, title: str) -> str:
    m = re.search(r"\{ title: '" + re.escape(title) + r"'[^`]*`((?:[^`\\]|\\.)*)`", page)
    assert m, title
    return m.group(1)


def test_the_versions_are_the_set_26_in_both_places():
    from agentvault_registry.config import settings
    assert lv.DOCUMENTS_VERSION == "2.6" and _const(EN, "LEGAL_DOCUMENTS_VERSION") == "2.6"
    assert lv.TOS_VERSION == settings.TOS_VERSION == "2.5"
    assert re.search(r"version: '2\.5'", _page(EN, "terms")) and re.search(r"version: '2\.5'", _page(DE, "terms"))
    for page in ("privacy", "license"):
        assert re.search(r"version: '2\.4'", _page(EN, page)), page
    assert re.search(r"version: '2\.4'", _page(DE, "privacy"))
    assert lv.OPERATOR_TERMS_SET_VERSION == "2.4"                   # the Operator Terms did not change: no operator is asked again


def test_one_pair_of_dates_thirty_days_apart_and_in_step():
    pub, eff = dt.date.fromisoformat(lv.PUBLISHED), dt.date.fromisoformat(lv.EFFECTIVE)
    assert eff - pub == dt.timedelta(days=30)
    label = lambda d: f"{d.day} {d.strftime('%B')} {d.year}"          # noqa: E731
    assert lv.EFFECTIVE_LABEL == label(eff)
    assert _const(EN, "LEGAL_PUBLISHED") == label(pub) and _const(EN, "EFFECTIVE_26") == label(eff)
    assert re.search(r"export const LEGAL_EFFECTIVE = EFFECTIVE_26\b", EN)
    assert re.search(r"effectiveDate: EFFECTIVE_26\b", _page(EN, "terms"))
    assert _const(DE, "EFFECTIVE_26_DE") == f"{eff.day}. {MONTHS_DE[eff.month - 1]} {eff.year}"
    assert _const(DE, "PUBLISHED_26_DE") == f"{pub.day}. {MONTHS_DE[pub.month - 1]} {pub.year}"
    assert re.search(r"effectiveDate: EFFECTIVE_26_DE\b", _page(DE, "terms"))


def test_terms_512_says_what_the_draft_says():
    t = _sub(_page(EN, "terms"), "5.12 The code host and contributions")
    for part, words in (("(a)", "code.theprotocol.cloud"), ("(b)", "Link repository account"), ("(b)", "never created automatically"),
                        ("(c)", "git config user.email"), ("(d)", "Software License Notice § 6"), ("(e)", "suspended"),
                        ("(e)", "closed"), ("(f)", "secrets"), ("(g)", "beta")):
        assert part in t and words in t, (part, words)


def test_the_privacy_policy_says_what_the_code_host_processes_and_why():
    p = _page(EN, "privacy")
    assert "users.code.theprotocol.cloud" in _sub(p, "3.8 Code host account")
    basis = _sub(p, "4.9 Code host")
    assert "Art. 6 (1) (b)" in basis and "Art. 6 (1) (f)" in basis
    assert "code host" in _sub(p, "4.8 Retention schedule")
    assert "code host" in _sub(p, "5.1 Processors and service providers")


def test_the_licence_names_the_code_host_and_the_change_log_lists_the_set():
    assert "code.theprotocol.cloud" in _page(EN, "license")
    changes = _page(EN, "changes")
    # the title names its dates through the one pair (a template literal), never a copy of them
    m = re.search(r"number: '2\.6',\s*title: `([^`]+)`(.*?)\n      \},", changes, re.S)
    assert m and "Terms of Service 2.5" in m.group(1) and "${LEGAL_PUBLISHED}" in m.group(1) and "${EFFECTIVE_26}" in m.group(1)
    for ref in ("§ 5.12", "§ 3.8", "§ 4.9"):
        assert ref in m.group(2), ref


def test_the_german_set_carries_the_same_new_subsections():
    for page, title in (("terms", "'5.12 "), ("privacy", "'3.8 "), ("privacy", "'4.9 ")):
        assert ("title: " + title) in _page(DE, page), (page, title)


def test_the_privacy_policy_names_what_a_home_sends_for_code_governance_and_why():
    # V0667 the developer passport (gwo_fb84e57318de0802725ab511; session-lead room seq 5371: Privacy 4.10 in set 2.6, its German twin)
    p = _sub(_page(EN, "privacy"), "4.10 Taking part from another registry")
    for words in ("public name", "developer number", "never your e-mail address", "Art. 6 (1) (b)", "Stop taking part",
                  "record of every card", "standing"):
        assert words in p, words
    m = re.search(r"number: '2\.6',.*?\n      \},", _page(EN, "changes"), re.S)
    assert m and "§ 4.10" in m.group(0)
    assert "title: '4.10 " in _page(DE, "privacy")
