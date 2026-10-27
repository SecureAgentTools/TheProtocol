"""W1 (agentvault2-69, 2026-10-26): the console's documentation keeps the public wording.

His words: "i want the illegal wording completly gone before opening" (2026-10-25). The doc folder (assets/docs) is the one
source of the console's #/docs and #/operator-docs, of docs.theprotocol.cloud (docs-site/sync-content.mjs) and of the open
source export's PUBLIC_DOCS. This test reads every chapter as a production frame shows it: a part marked
<!-- on: name --> is left out, since staking_rewards, agora_distributions and fiat_onramp are off on EU, ASIA and their
operators (composables/docs/switchBlocks.ts; the site's sync does the same). Code blocks, code spans and link addresses
are names, not prose; so is a word inside an identifier-shaped token, as in the route and refusal tests. The rules are
test_refusal_sentences_public_wording.py's with lifecycle 51's own "earn" (money earned; a mark or trust earned by work is
the reputation sense the chapters use), plus "mint" (his "yes all approved." 2026-10-25 21:15Z to the word: issue for
units and credentials, create for objects), tokenomics, insurance, market cap and valuation.

Measured 2026-10-26 on V0643 (c7531675d) by building docs.theprotocol.cloud from it: 17 hits in the whole folder, all in
the two generated reference pages (the generator's notes on the switched route and tool groups, one OpenAPI summary
that minted a token, one MCP description that minted an offer) and one whitepaper negation; the generator, the summary
and the description were reworded (fix/docs-reference-words); kept below, each with its reason. 0 since.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_refusal_rules", _HERE / "test_refusal_sentences_public_wording.py")
_RULES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RULES)

DOCS = _HERE.parent / "src" / "agentvault_registry" / "static" / "new_registry_frontend" / "src" / "assets" / "docs"
# the refusal test's rules, its broad "earn" left for lifecycle 51's (in the route rules): money earned, not marks or trust
RULES = [r for r in _RULES.RULES if r[0] != "earn" or r in _RULES._ROUTE_RULES.RULES]
MORE = [
    ("mint", re.compile(r"\bmint(?:s|ed|ing|able)?\b", re.I)),
    ("tokenomics", re.compile(r"\btokenomics\b", re.I)),
    ("insurance", re.compile(r"\binsur(?:e|ed|er|ers|ance|ances)\b", re.I)),
    ("market-cap", re.compile(r"\bmarket[\s-]cap(?:italisation|italization|s)?\b", re.I)),
    ("valuation", re.compile(r"\bvaluations?\b", re.I)),
]
# production's switches: all three off on the public network (sync-content.mjs PRODUCTION_SWITCHES)
PRODUCTION_SWITCHES = {"staking_rewards": False, "agora_distributions": False, "fiat_onramp": False}
SWITCH_BLOCK = re.compile(r"<!--\s*(on|off):\s*([a-z_]+)\s*-->([\s\S]*?)<!--\s*/\1\s*-->")
# kept on purpose, (file or "*", the line's start or a phrase in it), each with its reason
KEPT = [
    # the compliant statement every unit chapter makes (a negation: "They have no euro price, cannot be exchanged back
    # into money, and carry no ..."), as the legal texts keep theirs
    ("*", "They have no euro price, cannot be exchanged back into money"),
    # a verb: the registry card's ETag rule ("The tag a registry returns on the 304 path MUST equal ...")
    ("specs/registry-card-v0.6.md", "The tag a registry returns on the 304 path"),
    # the API page groups routes by their path prefix: /api/v1/staking/..., /api/v1/tokenomics/... are route names
    ("reference/api.md", "## staking ("),
    ("reference/api.md", "## tokenomics ("),
    # a negation: the slash ladder's default policy forbids insuring against a slash (the plan keeps negations)
    ("whitepaper/v2-draft.md", "The default policy prohibits slashing insurance."),
]


def production_view(md: str) -> str:
    def one(m):
        kind, name, body = m.group(1), m.group(2), m.group(3)
        assert name in PRODUCTION_SWITCHES, f"unknown switch {name!r}"
        return body if (kind == "on") == PRODUCTION_SWITCHES[name] else ""
    return SWITCH_BLOCK.sub(one, md)


def prose(md: str) -> str:
    md = production_view(md)
    md = re.sub(r"```[\s\S]*?```", lambda m: "\n" * m.group(0).count("\n"), md)   # keep line numbers
    md = re.sub(r"<!--[\s\S]*?-->", lambda m: "\n" * m.group(0).count("\n"), md)
    md = re.sub(r"`[^`\n]*`", " ", md)
    return re.sub(r"\]\([^)\n]*\)", "]", md)                                   # a link's address is a name


def hits(text: str) -> list[str]:
    out = []
    for raw in (text or "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        for rule, rx in RULES + MORE:
            for m in rx.finditer(line):
                if not _RULES._ROUTE_RULES._code_name(line, m.start(), m.group(0)):
                    out.append(f"[{rule}] {m.group(0)!r} in: {line[max(0, m.start() - 50):m.end() + 50]}")
    return out


def chapter_hits(rel: str, md: str) -> list[str]:
    found = []
    for n, line in enumerate(prose(md).split("\n"), 1):
        if any(f in (rel, "*") and k in line for f, k in KEPT):
            continue
        found += [f"{rel}:{n}: {h}" for h in hits(line)]
    return found


def test_the_rules_catch_what_they_are_for():
    for bad in ("> Staking and its reward program are switches per registry, off on the public network.",
                "| POST | `/api/v1/x` | Mint a short agent token for an agent you own |",
                "DESTRUCTIVE: mint a contract offer from a published template.",
                "The index is market-cap-weighted.", "Tokenomics in one page.", "A bond is a kind of insurance.",
                "Agents earn units for every task.", "Pay 5 euros to buy units."):
        assert chapter_hits("x.md", bad), bad
    for good in ("> Locks and their payout program are switches per registry, off on the public network.",
                 "Call `POST /api/v1/staking/stake` where locks are on; the kind `mint` counts as issued.",
                 "```\nPOST /api/v1/staking/unstake\n```", "See [the chapter](/docs/03#staking-rewards).",
                 "Issue a short agent token for an agent you own.", "Frames that share a machine share no trust.",
                 "Earned marks are engraved by verified work.", "They have no euro price, cannot be exchanged back into money."):
        assert not chapter_hits("x.md", good), good


def test_production_view_drops_what_production_hides():
    md = "a\n<!-- on: staking_rewards -->payouts reward you<!-- /on -->\n<!-- off: staking_rewards -->no payouts<!-- /off -->\nb"
    assert "reward" not in production_view(md) and "no payouts" in production_view(md)
    assert chapter_hits("x.md", md) == []


def test_the_reader_reads_the_chapters():
    # a control for the reader: a glob that matched nothing would pass the last test for the wrong reason
    files = sorted(DOCS.rglob("*.md"))
    assert len(files) > 60, len(files)
    assert any("Locks" in f.read_text(encoding="utf-8") for f in files)
    for f, k in KEPT:                     # a kept line that left its file would hide a new one with the same start
        texts = [g.read_text(encoding="utf-8") for g in files] if f == "*" else [(DOCS / f).read_text(encoding="utf-8")]
        assert any(k in t for t in texts), (f, k)


def test_every_chapter_keeps_the_public_wording():
    found = []
    for f in sorted(DOCS.rglob("*.md")):
        found += chapter_hits(str(f.relative_to(DOCS)), f.read_text(encoding="utf-8"))
    assert found == [], f"{len(found)} documentation line(s) fail the public wording:\n" + "\n".join(found)
