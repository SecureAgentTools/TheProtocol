"""W1/API (agentvault2-69, 2026-10-25): the sentences the registry hands a caller keep the public wording.

His words that day: "i want the illegal wording completly gone before opening". The route texts are held by
test_route_texts_public_wording.py (lifecycle 51's rules over the served OpenAPI document); this test holds what a route
answers: every HTTPException detail, every error/message/reason/note/hint a route or a tool returns in a dict (since the
second pass also every title/description/label/summary/headline/body/text/explanation, since the third every
sentence/notice/caption/subtitle/tooltip/warning/remedy/advice/help), and the module constants they
name, read from the source with ast (nothing is imported or called). The rules are that file's,
less the three whose subject is not a money word (legacy unit codes, legacy frame names, "tokens" as units: an access
token is not money, and FRAME_CURRENCY's default is a code), plus the plan's lock words (stake, staking, unstake, reward,
earn: sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md). A word inside an identifier-shaped token ("stake_held",
"/staking/apy-tiers", "staking_disabled:") is a code name and passes, as there.

Measured on b033a895 (V0642 + W3) before the rewording: 76 sentences in 26 files (the list:
scratchpad/compliant/api/sentences_v0643.md); 0 since. The second pass widened the keys and measured 7 more sentences (9 rule
hits) on 51c1988b in 6 files (the stuck-funds title, the MCP server's description, the flexible lock tier's label, the organization treasury's
two descriptions, two arena tool texts); 0 since. The third pass (2026-10-25 23:25Z, after agentvault2-5b's inventory of the
V0643 trial console on sbx-beta) widened them again and measured 2 more sentences on 1b93060bf: the desk's undelivered
payouts ("Earned, computed, and never paid", key sentence) and the showcase identity's notice ("IPO shares", "real
money on the public ledger", key notice); 0 since. The fourth pass (2026-10-26, found while building the docs site from
V0643) adds "mint" (his "yes all approved." 2026-10-25 21:15Z to the word: issue for units and credentials) and the key
instructions, and measured 20 sentences on c7531675d in 7 files (the token bridge's refusals, the treasury's shortfall and
issuance errors, the dispute settlement's two messages, mTLS enrolment's two, the simulation's frames, the canary
bootstrap's reason, the treasury watch's notice); 0 since. A key whose values are codes ("action": "stake") is not read.
"stock-card" is AGORA's own word and waits for his AGORA call.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_route_text_rules", _HERE / "test_route_texts_public_wording.py")
_ROUTE_RULES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ROUTE_RULES)

_NOT_MONEY = {"legacy-frames", "legacy-unit", "tokens-as-units"}
RULES = [r for r in _ROUTE_RULES.RULES if r[0] not in _NOT_MONEY] + [
    ("stake", re.compile(r"\b(?:stak(?:e|ed|es|ing|er|ers)|unstak\w*)\b", re.I)),
    ("reward", re.compile(r"\brewards?\b", re.I)),
    ("earn", re.compile(r"\bearn(?:s|ed|ing|ings)?\b", re.I)),
    ("mint", re.compile(r"\bmint(?:s|ed|ing|able)?\b", re.I)),
]
# what a route or a tool hands back for a person to read; title, description, label and summary since the second pass
# (the stuck-funds title, the MCP server's description, the tier labels, the arena tools' texts)
KEYS = {"detail", "message", "error", "reason", "note", "hint", "why", "msg",
        "title", "description", "label", "summary", "headline", "body", "text", "explanation",
        "sentence", "notice", "caption", "subtitle", "tooltip", "warning", "remedy", "advice", "help", "instructions"}
# words kept on purpose, each with its reason: AGORA's own words wait for his AGORA call
KEPT_WORDS = {"stock-card"}
SKIP_PARTS = {"tests", "api_tests", "static", "alembic", "__pycache__"}


def hits(text: str) -> list[str]:
    out = []
    for raw in (text or "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        for rule, rx in RULES:
            for m in rx.finditer(line):
                if _ROUTE_RULES._code_name(line, m.start(), m.group(0)):
                    continue
                if any(w in line[max(0, m.start() - 12):m.end() + 12] for w in KEPT_WORDS):
                    continue
                out.append(f"[{rule}] {m.group(0)!r} in: {line[max(0, m.start() - 50):m.end() + 50]}")
    return out


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{…}" for v in node.values)
    return None


def caller_sentences(src_root: Path):
    """(file, line, text) for every string a caller can read in a refusal or a returned error."""
    for f in sorted(src_root.rglob("*.py")):
        if SKIP_PARTS & set(f.relative_to(src_root).parts):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        consts = {n.targets[0].id: n.value for n in tree.body
                  if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}

        def texts(node, depth=0):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in consts and depth < 2:
                    yield from texts(consts[sub.id], depth + 1)
                elif isinstance(sub, ast.JoinedStr):
                    yield sub.lineno, _text(sub)
                elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    yield sub.lineno, sub.value

        for n in ast.walk(tree):
            nodes = []
            if isinstance(n, ast.Call):
                fn = n.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if name == "HTTPException":
                    nodes += [k.value for k in n.keywords if k.arg == "detail"] + list(n.args[1:2])
            elif isinstance(n, ast.Dict):
                nodes += [v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value in KEYS]
            for node in nodes:
                for line, t in texts(node):
                    if t:
                        yield str(f.relative_to(src_root)), line, t


def _src_root() -> Path:
    return _HERE.parent / "src" / "agentvault_registry"


def test_the_rules_catch_what_they_are_for():
    # controls: each money word the rewording removed is still caught, and the words it chose pass
    for bad in ("No rewards to claim", "Only agents with staked tokens can vote", "Minimum stake amount is 10",
                "Nothing was unstaked.", "Unable to fetch APY tiers", "a backstopped bond pays nothing from your own earnings",
                "Earned, computed, and never paid.", "It can buy showcase services and IPO shares",
                "TEG Layer unavailable for minting operation", "These wrapped units were minted to another agent"):
        assert hits(bad), bad
    for good in ("No payouts to claim", "Only agents with locked units can vote", "Minimum lock amount is 10",
                 "Nothing was unlocked.", "staking_disabled: Locking is not enabled on this registry (STAKING_ENABLED=false).",
                 "Task with collateral: home-held collateral of {…} required (asserted: {…})",
                 "TEG Layer unavailable for the issuance",
                 "Use the registry's issuance rail (POST /api/v1/teg/treasury/mint), then retry."):
        assert not hits(good), good


def test_the_reader_finds_the_sentences_it_holds():
    # a control for the reader itself: a scan that found nothing would pass this file for the wrong reason
    found = list(caller_sentences(_src_root()))
    assert len(found) > 1000, len(found)
    joined = "\n".join(t for _f, _l, t in found)
    for sentence in ("Lock amount must be positive", "No payouts to claim", "Too many pending payment authorizations",
                     "Locking is not enabled on this registry", "Owed, computed, and never paid",
                     "This is a shared demonstration identity", "nothing was issued", "issuing the certificate failed"):
        assert sentence in joined, sentence


def test_every_caller_sentence_keeps_the_public_wording():
    found = [f"{f}:{line}: {h}" for f, line, t in caller_sentences(_src_root()) for h in hits(t)]
    assert found == [], f"{len(found)} caller sentence(s) fail the public wording:\n" + "\n".join(sorted(set(found)))
