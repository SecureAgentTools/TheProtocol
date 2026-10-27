"""W1/API (agentvault2-69, 2026-10-25): the mail the registry sends keeps the public wording too.

His words that day: "i want the illegal wording completly gone before opening". The refusal sentences are held by
test_refusal_sentences_public_wording.py; this test reads every email template (templates/email/*.j2) with the same rules,
plus the phrases in which a mail called units tokens ("token balances", "issued tokens", "a utility token"), outside the
Jinja expressions (a variable name is an identifier). A credential stays a token ("THIS TOKEN IS SHOWN ONCE").

Measured on 8d384800 before the rewording: the two fiat purchase mails ("AVT is a utility token ... (MiCA-safe utility
model). Use it to ... stake for governance ... earn rewards"), the reinstatement notice ("staking rewards resume"), the
deletion, funding, anonymization and supply-breach mails ("staked", "token balances", "issued tokens"), the beta invite
("earn up to"): this test's rules found 42 hits in 15 templates; 18 sentences in 16 templates were reworded; 0 since.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_refusal_rules", _HERE / "test_refusal_sentences_public_wording.py")
_RULES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RULES)

TEMPLATES = _HERE.parent / "src" / "agentvault_registry" / "templates" / "email"
UNITS_AS_TOKENS = re.compile(r"\b(?:token balances?|issued tokens|the tokens have been|token transfer|utility tokens?|MiCA)\b", re.I)
JINJA = re.compile(r"\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}|\{#[\s\S]*?#\}")


def hits(text: str) -> list[str]:
    out = _RULES.hits(text)
    for line in (text or "").split("\n"):
        for m in UNITS_AS_TOKENS.finditer(line):
            out.append(f"[units-as-tokens] {m.group(0)!r} in: {line.strip()[:120]}")
    return out


def test_the_rules_catch_what_they_are_for():
    for bad in ("Use it to pay agent service fees, stake for governance, fund disputes, earn rewards.",
                "AVT is a utility token: buy-only, no fiat redemption (MiCA-safe utility model).",
                "The tokens have been deposited to your agent's liquid balance.",
                "Suspended balances and staked positions are unchanged; staking rewards resume on the next distribution cycle."):
        assert hits(bad), bad
    for good in ("These units are platform-internal: bought only, never paid out in money.",
                 "THIS TOKEN IS SHOWN ONCE AND CANNOT BE RECOVERED.",
                 "docker login images.example -u name -p <token>",
                 "Suspended balances and locked positions are unchanged; payouts on locked units, where this registry makes "
                 "them, resume on the next cycle."):
        assert not hits(good), good


def test_the_reader_reads_the_templates():
    # a control for the reader: a glob that matched nothing would pass the last test for the wrong reason
    files = sorted(TEMPLATES.glob("*.j2"))
    assert len(files) > 50, len(files)
    assert any("platform-internal" in f.read_text(encoding="utf-8") for f in files)


def test_every_mail_template_keeps_the_public_wording():
    found = []
    for f in sorted(TEMPLATES.glob("*.j2")):
        prose = JINJA.sub(" ", f.read_text(encoding="utf-8"))
        found += [f"{f.name}: {h}" for h in hits(prose)]
    assert found == [], f"{len(found)} mail sentence(s) fail the public wording:\n" + "\n".join(found)
