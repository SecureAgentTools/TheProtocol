"""V0667 D8 (order gwo_589b1792026bd84e1da4e798): chapter 40 of the console's documentation, "Release lines: an organization's own line on top of our release"
(the Distributions chapter). Written from what the V0667 cut has (D1 to D5 and the developer passport; D6's builds and D7's packs are added
when their branches land), and pinned the way the passport paragraph is (tests/test_docs_code_passport_v0667.py).

Pinned:
  * the chapter exists, is registered in the console's reader (OracleView.vue) and shows no unfinished sentence;
  * it says what the design says (sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md): what a line is, who proposes, reviews and decides, what always goes
    through us (the checker, the inbox, the pause and the veto, the build on a card), the fast lane and its five kinds, upstream, the chat command;
  * NO COMMAND WITHOUT A ROUTE: every `/api/v1/...` path the chapter names is a route of the registry, found in the routers' source with its own method
    (a rename of a route reddens this test, never the reader); every chat command it names is in the console's door;
  * nothing is promised that the release does not have: a planned thing is said to be planned in the same sentence, and the chapter never says AGORA
    payouts (a line is code, never a payout).
RED: the chapter does not exist.
"""
from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
SRC = _HERE.parent / "src" / "agentvault_registry"
FE = SRC / "static" / "new_registry_frontend" / "src"
CHAPTER = FE / "assets" / "docs" / "oracle" / "40_distributions.md"
READER = FE / "views" / "OracleView.vue"
ROUTERS = SRC / "routers"


def _text() -> str:
    assert CHAPTER.exists(), "oracle/40_distributions.md does not exist"
    return CHAPTER.read_text(encoding="utf-8")


def _flat(t: str) -> str:
    return re.sub(r"\s+", " ", t)


def test_the_chapter_is_registered_in_the_reader_once():
    src = READER.read_text(encoding="utf-8")
    assert src.count("import ch40 from '@/assets/docs/oracle/40_distributions.md?raw'") == 1
    assert len(re.findall(r"\{ id: '40',", src)) == 1
    assert re.search(r"\{ id: '40', section: 'Build', number: '40', title: '(?:[^'\\]|\\.)+', subtitle: '(?:[^'\\]|\\.)+', content: ch40,", src)


def test_the_chapter_says_what_a_line_is_and_who_decides():
    t = _flat(_text())
    for words in ("release line", "V0666_lyceum", "on top of our release", "never forks away",
                  "not a guest", "never the proposer", "owners and admins", "leads of the team",
                  "quorum", "simple majority", "a vote is never changed"):
        assert words in t, words


def test_the_chapter_says_what_always_goes_through_us():
    t = _flat(_text())
    for words in ("signed checker", "contributions inbox", "pause", "veto", "money moves only through the existing rails",
                  "never open to a line"):
        assert words in t.lower(), words


def test_the_chapter_says_the_fast_lane_with_its_five_kinds_and_the_undo():
    t = _flat(_text())
    for words in ("fast lane", "six kinds", "kit", "proxy_spec", "policy_value", "console_text", "branding", "compliance_pack",
                  "no image is built", "own space", "the undo", "never code", "never another organization"):
        assert words in t.lower(), words


def test_the_chapter_says_upstream_and_the_chat_command():
    t = _flat(_text())
    for words in ("propose upstream", "same commit", "provenance", "upstream_since", "/change <title>", "/change content <title>", "change card"):
        assert words in t, words


def test_the_chapter_never_says_payout_and_names_no_unrun_example():
    t = _text()
    assert not re.search(r"\bpayouts?\b", t, re.I) or "never a payout" in _flat(t), "a line is code: say it is never a payout, or leave the word out"
    assert "TODO" not in t and "TBD" not in t and "XXX" not in t
    # the docs rule: a page's examples are run before they are written. This draft has none; a fenced block must carry the line "ran on" naming where.
    for block in re.findall(r"```[a-z]*\n(.*?)```", t, re.S):
        assert re.search(r"^# ran on ", block, re.M), "a fenced example must say where it ran: '# ran on <registry> <date>'"


def test_every_api_path_the_chapter_names_is_a_route_of_the_registry():
    t = _text()
    paths = sorted(set(re.findall(r"`(?:GET|POST|PUT|PATCH|DELETE)\s+(/api/v1/[A-Za-z0-9_\-/{}]+)`", t)))
    assert len(paths) >= 12, paths
    # route paths as the routers declare them
    declared: set[tuple[str, str]] = set()
    for f in ROUTERS.glob("*.py"):
        for m in re.finditer(r"@router\.(get|post|put|patch|delete)\(\s*\"(/api/v1/[^\"]+)\"", f.read_text(encoding="utf-8")):
            declared.add((m.group(1).upper(), m.group(2)))
    # a path param's name is the router's own; the chapter may name it differently, so compare by shape
    def shape(p: str) -> str:
        return re.sub(r"\{[^}]+\}", "{}", p)
    have = {(m, shape(p)) for m, p in declared}
    named = re.findall(r"`(GET|POST|PUT|PATCH|DELETE)\s+(/api/v1/[A-Za-z0-9_\-/{}]+)`", t)
    missing = sorted({(m, p) for m, p in named if (m, shape(p)) not in have})
    assert not missing, f"the chapter names routes that no router declares: {missing}"


def test_every_chat_command_the_chapter_names_is_in_the_consoles_door():
    t = _text()
    door = (FE / "services" / "chat" / "changeDoor.ts").read_text(encoding="utf-8")
    cmds = set(re.findall(r"`(/change(?: content)?)(?: <title>)?`", t))
    assert cmds >= {"/change", "/change content"}, cmds
    assert "/change" in door and "content" in door


def test_what_the_release_does_not_have_is_said_to_be_planned_in_its_own_section():
    txt = _text()
    m = re.search(r"\n## What is planned and not built\n(.*)\Z", txt, re.S)
    assert m, "the chapter needs its 'What is planned and not built' section, last"
    tail = _flat(m.group(1))
    for words in ("not in the V0667 release", "A pack enforced by the rails", "planned, not built"):
        assert words in tail, words
    # and nothing above the section describes them as done
    head = _flat(txt[: m.start()])
    for words in ("scoped release channel", "our pipeline would build", "Builds of a line"):
        assert words not in head, f"{words!r} is planned: it belongs only in the planned section"


def test_the_glossary_has_the_release_line_once_and_points_to_the_chapter():
    g = (FE / "assets" / "docs" / "oracle" / "23_glossary.md").read_text(encoding="utf-8")
    hits = [l for l in g.splitlines() if l.startswith("- **Release line**")]
    assert len(hits) == 1
    assert "(/docs/40)" in hits[0] and "never a payout" in hits[0] and "V0666_lyceum" in hits[0]


GOVERNANCE = FE / "assets" / "docs" / "oracle" / "06_governance.md"


def test_the_governance_chapter_says_only_eu_governs_code_and_what_every_other_registry_shows():
    """session-lead, room seq 5542: the published governance page never said that only EU governs code changes (V0666 made it so)."""
    g = GOVERNANCE.read_text(encoding="utf-8")
    m = re.search(r"\n## Code Changes: Members Vote on the Code\n(.*?)(?=\n## )", g, re.S)
    assert m
    section = m.group(1)
    hits = [p for p in re.split(r"\n\s*\n", section) if "Only one registry governs code" in p]
    assert len(hits) == 1, f"want one governing-registry paragraph, found {len(hits)}"
    p = _flat(hits[0])
    for words in ("EU (theprotocol.cloud)", "propose, review and vote there", "every other registry", "read-only",
                  "link to EU", "developer passport", "CODE_CHANGES_GOVERNING_REGISTRY"):
        assert words in p, words
    # it comes before the first numbered step: a reader meets it before the flow
    assert section.index("Only one registry governs code") < section.index("1. **Propose**")


def test_chapter_40_names_eu_as_the_registry_that_governs_lines_and_points_to_the_passport():
    t = _flat(_text())
    for words in ("EU (theprotocol.cloud)", "every other registry", "read-only", "developer passport"):
        assert words in t, words


def test_the_chapter_says_exactly_what_a_pack_is_and_is_not_and_the_report_is_checked_offline():
    """session-lead, room seq 5560: D7 built the packs as declarations (stored, voted, signed); enforcement by the rails is planned, not built."""
    t = _flat(_text())
    for words in ("compliance_pack", "data_residency", "retention", "approval_thresholds", "reporting", "closed set",
                  "A pack records the organization's own policy values", "stored, voted on and kept in the line's signed record",
                  "enforced by no rail in this release", "Nothing outside the content changes reads a pack",
                  "signed report", "offline", "not_measured", "a result nobody measured is never shown as a pass"):
        assert words in t, words
    tail = _flat(re.search(r"\n## What is planned and not built\n(.*)\Z", _text(), re.S).group(1))
    assert "planned, not built" in tail and "A pack enforced by the rails" in tail
    # a pack is never described as enforced anywhere else
    assert not re.search(r"\b(?:enforces|is enforced by)\b[^.]*\bpack", t.split("## ")[0] if False else t)


def test_no_example_names_a_regulator():
    """session-lead, room seq 5560: a regulator's name in our own example reads as a compliance claim while the inquiry is open."""
    t = _text()
    assert not re.search(r"bafin|\bgdpr\b", t, re.I)


def test_the_builds_paragraph_is_session_leads_words_and_the_protected_set_check_is_the_gate():
    """session-lead, room seq 5606 (room seq 5604: no conflict, the pipeline builds; any conflict, it stops and the line's team resolves it; publishing is an approval
    in the admin queue), its last sentence replaced by his seq 5609 (room seq 5608: on production distributions are on for EU and ASIA). The protected-set check
    is the gate (seq 5590)."""
    t = _flat(_text())
    para = ("When distributions are switched on, our pipeline carries each line to every new release of ours and builds it whenever nothing conflicts: our checker, "
            "the gates of our own releases and the protected-set check run on every build, and a built line is published after an approval in the platform's admin queue. "
            "On any conflict the pipeline stops and the line's team resolves it: we never merge for anyone. On production they are switched on for EU and ASIA.")
    assert para in t, "the builds paragraph is not in session-lead's words"
    assert t.count("On production they are switched on for EU and ASIA.") == 1
    for words in ("protected set", "byte for byte", "federation", "compliance", "money", "identity", "the build's own inputs",
                  "intact", "refused", "each removed module", "optional module"):
        assert words in t, words
    assert "builds and publishes no organization's line" not in t and "own to build" not in t
    # the planned list no longer carries a build by our pipeline
    tail = _flat(re.search(r"\n## What is planned and not built\n(.*)\Z", _text(), re.S).group(1))
    assert "pipeline" not in tail and "Builds of a line" not in tail and "Lean lines" not in tail


def test_the_true_sentence_about_the_pipeline_follows_the_builds_paragraph():
    """session-lead, room seq 5618: the pipeline's steps have passed their tests on real git and have not yet made a full run end to end; the first line switched on will be its first."""
    sentence = ("The pipeline's steps, carry-forward, build and publishing, run by us for each line, have passed their tests on real git and have not yet made a full run "
                "end to end; the first line switched on will be its first.")
    paras = [_flat(p) for p in re.split(r"\n\s*\n", _text())]
    i = next(k for k, p in enumerate(paras) if p.startswith("When distributions are switched on, our pipeline carries each line"))
    assert paras[i + 1] == sentence, paras[i + 1][:160]
    assert sum(sentence in p for p in paras) == 1
