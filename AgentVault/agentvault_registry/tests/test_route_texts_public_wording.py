"""§DOCSFIX D6-019: the route texts every registry serves keep the public wording.

Every registry serves its whole OpenAPI document, admin routes included, as interactive API docs (/docs, /redoc and
/api/v1/openapi.json), and docs.theprotocol.cloud publishes its reference pages from it. The production wording gate is
the console suite's lifecycle 51 (e2e/suite/lifecycles/51-public-wording.spec.ts, on the suite branches): the words
the network does not use on a public page, held to the frames' switches. With production's switches (rewards,
distributions and the euro lane all off) every tier applies, so this test carries the whole rule list. As on the docs
pages, a hit inside an identifier-shaped word (one that carries "." "/" or "_") is a code name and passes.

Measured 2026-10-16 on V0618 plus the corrected texts: 38 hits in 27 route texts (AVT, "tokens" as units, veToken,
Frame A/B/C, "staking rewards"), 32 of them on admin routes; 0 since.

Second pass (agentvault2-69, 2026-10-26, for V0645): lifecycle 51 holds "staking rewards" but not plain stake, reward
or mint, and V0643 still served them: 85 hits in 59 route texts on 46 routes ("Mint new units into this frame",
"Claim all pending rewards ... staking, attestation, and governance rewards", "The TEG's staking tiers"). The rules gain
stake, reward and mint (his "yes all approved." 2026-10-25 21:15Z to the word: issue for units and credentials, create
for keys, codes and grants), a parameter's description is read too, and a code span is a name (a status such as
`MINTED`, a route such as `mint-agent-proxy`), as on the docs pages. 0 since.
"""
import re

import pytest

CREDENTIAL_WORDS = set("auth authentication access bearer refresh api jwt capability payment bootstrap session csrf pull "
                       "push device agent developer verification reset invite invitation signed spiffe oauth id one-time "
                       "join att_ apt_".split())


def _w(alts: str):
    return re.compile(r"\b(?:" + alts + r")\b", re.I)


# lifecycle 51's RULES, in its order (aacc02ab); "tokens-as-units" checks the word before "tokens" below
RULES = [
    ("apy", _w("APY|APR")), ("yield", _w("yields?")), ("reward-flow", _w(r"rewards?\s(?:distribute|daily|rate)")),
    ("staking-rewards", _w(r"staking\srewards?")), ("reward-rate", _w(r"reward\srate")),
    ("earn", _w(r"earn\s(?:AVT|units|tokens?|rewards|interest|yield)|earn\sthrough|earn\sadditional")),
    ("interest-rate", _w(r"interest\srate")), ("passive-income", _w(r"passive\sincome")),
    ("profit-share", _w(r"profit\sshare")), ("invest", _w("invest(?:s|ed|ing|ment|or)?")), ("ipo", _w("IPO")),
    ("dividend", _w("dividends?")), ("vetoken", _w("veToken")), ("bank-stock", _w("banks?|banking|stocks?")),
    ("returns", re.compile(r"\breturns?\son\b|\d+\s?%\s?returns?\b|\bannual\sreturns?\b", re.I)),
    ("shares", _w(r"share\sprice|shareholders?|org\sshares|buy\sshares")),
    ("distribution", _w(r"distributions?\sof\s(?:rewards|fees|profits?)|dividend")),
    ("euro-near-money", re.compile(r"\b(?:buy|purchase|price|per month)\b[^.\n]{0,40}\beuros?\b"
                                   r"|\beuros?\b[^.\n]{0,40}\b(?:buy|purchase|price|per month)\b", re.I)),
    ("euro-amount", re.compile(r"€\s?\d[\d.,]*|\b\d[\d.,]*\s?(?:€|EUR\b)")),
    ("backer", _w(r"become\sa\sbacker|backer\stier")),
    ("legacy-unit", re.compile(r"\b(?:AVT|JDAY|BVT)\b")), ("utility-token", _w(r"utility\stoken")),
    ("tokens-as-units", re.compile(r"\btoken\s+grants?\b|\btokens\b", re.I)),
    ("legacy-frames", re.compile(r"\bFrame [ABC]\b|\bthree mainframes\b")),
    # the second pass: the plan's lock words and the word "mint" (PLAN_2026-10-25_COMPLIANT_OPENING.md)
    ("stake", re.compile(r"\b(?:stak(?:e|ed|es|ing|er|ers)|unstak\w*)\b", re.I)),
    ("reward", re.compile(r"\brewards?\b", re.I)),
    ("mint", re.compile(r"\bmint(?:s|ed|ing|able)?\b", re.I)),
]


def _code_name(line: str, at: int, phrase: str) -> bool:
    a, b = at, at + len(phrase)
    while a > 0 and not line[a - 1].isspace():
        a -= 1
    while b < len(line) and not line[b].isspace():
        b += 1
    word = re.sub(r"\.+$", "", re.sub(r"[,;:!?)\]}\"'`]+$", "", re.sub(r"^[(\"'`\[{]+", "", line[a:b])))
    return word != phrase and re.search(r"[./_]", word) is not None


def hits(text: str):
    out = []
    for raw in (text or "").split("\n"):
        line = re.sub(r"\s+", " ", re.sub(r"`[^`\n]*`", " ", raw)).strip()   # a code span is a name
        for rule, rx in RULES:
            for m in rx.finditer(line):
                if _code_name(line, m.start(), m.group(0)):
                    continue
                if rule == "tokens-as-units" and m.group(0).lower() == "tokens":
                    prev = re.search(r"\b([\w-]+?)[\s-]$", line[:m.start()])
                    if prev and prev.group(1).lower() in CREDENTIAL_WORDS:
                        continue   # a credential called a token (an access token, pull tokens)
                out.append(f"[{rule}] {m.group(0)!r} in: {line[max(0, m.start() - 50):m.end() + 50]}")
    return out


def test_the_rules_catch_what_they_are_for():
    assert hits("Mint new AVT tokens (admin only)") and hits("Manually pause staking rewards")
    assert hits("Get veToken voting power") and hits("Registry — Frame B (sovereign, prod)")
    assert not hits("Issue a short-lived access token; returns the pull tokens once")
    assert not hits("the `staking_rewards.max_apy_percent` key and /staking/apy-tiers")
    # the second pass: the plain lock words and mint are caught; the names in code spans and the words chosen pass
    assert hits("Mint a short-lived access token") and hits("Lock units in a staking position")
    assert hits("Claim all pending rewards via TEG Layer") and hits("mint-agent-proxy for a peer operator")
    assert not hits("Status: `INITIATED` → `LOCKED` → `MINTED`") and not hits("`mint-agent-proxy` for a peer operator")
    assert not hits("Claim all pending payouts on locked units; locking is a switch per registry")


@pytest.fixture(scope="module")
def spec():
    from agentvault_registry.main import app
    return app.openapi()


def test_every_served_route_text_keeps_the_public_wording(spec):
    found = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            for field in ("summary", "description"):
                found += [f"{method.upper()} {path} {field}: {h}" for h in hits(op.get(field) or "")]
            for prm in op.get("parameters") or []:
                found += [f"{method.upper()} {path} parameter {prm.get('name')}: {h}" for h in hits(prm.get("description") or "")]
    assert found == [], f"{len(found)} route text(s) fail the public wording:\n" + "\n".join(found)
