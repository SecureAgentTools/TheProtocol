"""A mail subject that names an amount's unit names THIS frame's unit (core/frame_currency.py's law, on the subject line).

Found 2026-10-10 by agentvault2-09 on sbx-beta, whose mail send failed for an unrelated reason (sbx-beta's registry is
not on the network of the sandbox's mail catcher) and so logged the subject it would have sent: "Your AVT Funding Request Has Been Approved", on a frame whose
unit is SBXB. The funding templates already print `{{ frame_currency }}`; only the subjects still said AVT, on every
frame, so an ECU member on EU would read an AVT subject above an ECU amount. The slash notice and the bridge-expiry
notice carried the same literal. The fiat onramp's two subjects stay: that rail sells Frame A's AVT tiers by name
(FIAT_GENESIS_REGISTRY) and is off on every other frame; the allowlist below says so, and its own test fails the day
the reason is gone.
"""
import ast
import pathlib
import re
from decimal import Decimal

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
UNIT = re.compile(r"\b(AVT|BVT|JDAY|ECU|ACU)\b")
ALLOWED = {"routers/fiat_onramp.py"}   # Frame A's fiat tiers are AVT by name; the rail is off on every other frame


def _subject_literals(tree):
    """Every literal text part of a `subject=` keyword argument: a plain string, or an f-string's constant parts."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "subject":
                continue
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                yield node.lineno, v.value
            elif isinstance(v, ast.JoinedStr):
                for p in v.values:
                    if isinstance(p, ast.Constant) and isinstance(p.value, str):
                        yield node.lineno, p.value


def _hits(rel):
    tree = ast.parse((PKG / rel).read_text(encoding="utf-8"), filename=rel)
    return [(line, text) for line, text in _subject_literals(tree) if UNIT.search(text)]


def test_no_mail_subject_names_a_unit_literally():
    files = sorted(p.relative_to(PKG).as_posix() for p in PKG.rglob("*.py"))
    assert len(files) > 300, f"the walk found {len(files)} files: is PKG right? ({PKG})"
    hits = [f"{rel}:{line}: {text!r}" for rel in files if rel not in ALLOWED for line, text in _hits(rel)]
    assert hits == [], "a mail subject names a unit literally; use frame_currency():\n" + "\n".join(hits)


def test_the_walk_sees_a_subject_with_a_unit():
    # the control: the same walk over a known literal must report it, or the gate above cannot fail
    tree = ast.parse('send(subject="Your AVT thing")\nsend(subject=f"{n} AVT moved")\nsend(subject=f"{n} {frame_currency()} moved")\n')
    found = [text for _line, text in _subject_literals(tree) if UNIT.search(text)]
    assert found == ["Your AVT thing", " AVT moved"]


def test_every_allowed_file_still_needs_its_place():
    # an allowlist entry whose reason is gone must go too
    for rel in ALLOWED:
        assert _hits(rel), f"{rel} no longer names a unit in a subject: take it off ALLOWED"


@pytest.mark.asyncio
async def test_funding_mail_subjects_name_the_frames_unit(monkeypatch):
    from agentvault_registry.routers import funding_requests as fr

    sent = []

    async def fake_send(**kw):
        sent.append(kw)

    monkeypatch.setattr(fr, "send_themed_email", fake_send)
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    await fr._send_funding_approval_email("member@example.invalid", 7, "did:theprotocol:x", Decimal("5"), "tx-1")
    await fr._send_funding_rejection_email("member@example.invalid", 8, "did:theprotocol:x", Decimal("5"), "not now")
    assert [k["subject"] for k in sent] == ["Your ECU Funding Request Has Been Approved", "ECU Funding Request Update"]

    # the control: a frame that declares no currency is Frame A, whose unit is AVT
    sent.clear()
    monkeypatch.delenv("FRAME_CURRENCY", raising=False)
    await fr._send_funding_approval_email("member@example.invalid", 9, "did:theprotocol:x", Decimal("5"), None)
    assert [k["subject"] for k in sent] == ["Your AVT Funding Request Has Been Approved"]
